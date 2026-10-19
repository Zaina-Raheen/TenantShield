"""Deterministic test engine. Verdicts come ONLY from explicit assertions on HTTP status plus resource
identity, owner tenant and unique content markers. No AI, and the demo's vulnerable/fixed mode is never consulted.

The engine can only talk to the bundled demo API, in-process (see make_demo_client)."""
import asyncio
import copy
import json
import logging
import time
from typing import Literal

import httpx
from pydantic import BaseModel, ConfigDict, Field, ValidationError, model_validator
from sqlalchemy.orm import Session

from . import config
from .demo_api import DEMO_TENANTS, DEMO_USERS, SEED_DOCUMENTS
from .models import (Finding, FindingOccurrence, RegressionRun, RegressionTest, TestResult, TestRun, utcnow)

log = logging.getLogger("tenantshield")
DENIED = (403, 404)
REQUEST_TIMEOUT_S = 5.0
MAX_BODY_CHARS = 200_000
run_lock = asyncio.Lock()  # one suite/regression execution at a time (single process)


class InvalidDefinition(ValueError):
    """A stored or supplied test definition is not an approved demo test."""


class CaseDefinition(BaseModel):
    """Strict schema for a runnable test. Only GET requests to the demo document endpoints are expressible."""
    model_config = ConfigDict(extra="forbid")

    key: str = Field(pattern=r"^[a-z0-9_]{1,60}$")
    name: str = Field(min_length=1, max_length=200)
    kind: Literal["same_tenant_read", "cross_tenant_read", "list_scoped"]
    identity: str
    requesting_tenant_id: str
    method: Literal["GET"]
    path: str = Field(max_length=120)
    resource_id: str | None = Field(default=None, pattern=r"^doc_[a-z0-9_]{1,40}$")
    resource_owner_tenant_id: str | None = None
    resource_marker: str | None = None
    expected_outcome: str = Field(min_length=1, max_length=500)
    severity: Literal["critical", "high", "medium", "low"] | None = None
    title: str | None = Field(default=None, max_length=200)

    @model_validator(mode="after")
    def _consistent(self):
        user = DEMO_USERS.get(self.identity)
        if user is None or user["tenant_id"] != self.requesting_tenant_id:
            raise ValueError("identity does not belong to the requesting tenant")
        if self.kind == "list_scoped":
            if self.path != "/api/demo/documents" or self.resource_id is not None:
                raise ValueError("list test must target /api/demo/documents")
            return self
        if self.resource_id is None or self.path != f"/api/demo/documents/{self.resource_id}":
            raise ValueError("path must be /api/demo/documents/<resource_id>")
        owner = DEMO_TENANTS.get(self.resource_owner_tenant_id or "")
        if owner is None or self.resource_marker != owner["marker"]:
            raise ValueError("resource owner / marker not recognised")
        if (self.kind == "same_tenant_read") != (self.resource_owner_tenant_id == self.requesting_tenant_id):
            raise ValueError("kind does not match resource ownership")
        return self


def parse_definition(raw: object) -> dict:
    try:
        return CaseDefinition.model_validate(raw).model_dump(exclude_none=True)
    except ValidationError as exc:  # details deliberately not propagated
        raise InvalidDefinition("Test definition is invalid or not an approved demo test") from exc


def _case(**kw) -> dict:
    return parse_definition(kw)


_ABC, _XYZ = DEMO_TENANTS["tenant_abc"]["marker"], DEMO_TENANTS["tenant_xyz"]["marker"]
# Severity: critical = cross-tenant write/delete or credential exposure; high = confirmed cross-tenant read
# (detail or list); medium = metadata-only exposure; low = hardening gap.
SUITE = [
    _case(key="abc_reads_own", name="ABC reads its own document", kind="same_tenant_read", identity="alice_abc",
          requesting_tenant_id="tenant_abc", method="GET", path="/api/demo/documents/doc_abc_001",
          resource_id="doc_abc_001", resource_owner_tenant_id="tenant_abc", resource_marker=_ABC,
          expected_outcome="200 OK; resource doc_abc_001 owned by tenant_abc"),
    _case(key="abc_reads_xyz", name="ABC attempts to read XYZ's document", kind="cross_tenant_read",
          identity="alice_abc", requesting_tenant_id="tenant_abc", method="GET", path="/api/demo/documents/doc_xyz_001",
          resource_id="doc_xyz_001", resource_owner_tenant_id="tenant_xyz", resource_marker=_XYZ, severity="high",
          title="Cross-tenant document read (ABC → XYZ)",
          expected_outcome="Access denied (403 or 404); no resource owned by tenant_xyz returned"),
    _case(key="xyz_reads_own", name="XYZ reads its own document", kind="same_tenant_read", identity="bob_xyz",
          requesting_tenant_id="tenant_xyz", method="GET", path="/api/demo/documents/doc_xyz_001",
          resource_id="doc_xyz_001", resource_owner_tenant_id="tenant_xyz", resource_marker=_XYZ,
          expected_outcome="200 OK; resource doc_xyz_001 owned by tenant_xyz"),
    _case(key="xyz_reads_abc", name="XYZ attempts to read ABC's document", kind="cross_tenant_read",
          identity="bob_xyz", requesting_tenant_id="tenant_xyz", method="GET", path="/api/demo/documents/doc_abc_001",
          resource_id="doc_abc_001", resource_owner_tenant_id="tenant_abc", resource_marker=_ABC, severity="high",
          title="Cross-tenant document read (XYZ → ABC)",
          expected_outcome="Access denied (403 or 404); no resource owned by tenant_abc returned"),
    _case(key="abc_list_scoped", name="Document list respects tenant boundaries", kind="list_scoped",
          identity="alice_abc", requesting_tenant_id="tenant_abc", method="GET", path="/api/demo/documents",
          severity="high", title="Cross-tenant leakage in document list",
          expected_outcome="200 OK; list contains only tenant_abc documents (doc_abc_001)"),
]
SUITE_BY_KEY = {c["key"]: c for c in SUITE}


def make_demo_client() -> httpx.AsyncClient:
    """Client bound in-process to the bundled demo app. There is no network target to misconfigure."""
    config.validate_target_config()
    from .demo_api import demo_app
    transport = httpx.ASGITransport(app=demo_app, raise_app_exceptions=False, client=("127.0.0.1", 0))
    return httpx.AsyncClient(transport=transport, base_url="http://demo.internal", timeout=REQUEST_TIMEOUT_S)


# ---------------------------------------------------------------- evaluation
def _clip(v):
    if v is None:
        return None
    return v[:100] if isinstance(v, str) else str(v)[:100]


def _is2xx(status: int) -> bool:
    return 200 <= status < 300


def evaluate(case: dict, status: int | None, body, raw: str, parse: str) -> tuple[str, str, dict]:
    """Return (result_status, observed_outcome, minimal_response_evidence). Pure and deterministic.

    parse is "ok" | "malformed" | "empty". raw is used only to look for markers and is never stored."""
    req, kind = case["requesting_tenant_id"], case["kind"]
    ev: dict = {"status_code": status, "body_parse": parse}
    if status is None:
        return "inconclusive", "Request could not be completed", ev
    if status >= 500:
        return "inconclusive", f"Server error ({status}); no reliable conclusion", ev

    is_dict = isinstance(body, dict)
    foreign_markers = [t["marker"] for tid, t in DEMO_TENANTS.items() if tid != req]
    foreign_marker = any(m in raw for m in foreign_markers)
    ev["foreign_marker_present"] = foreign_marker
    owner = body.get("owner_tenant_id") if is_dict else None
    owner_foreign = isinstance(owner, str) and bool(owner) and owner != req
    if is_dict:
        ev.update(resource_id=_clip(body.get("id")), owner_tenant_id=_clip(owner), content_returned=bool(body.get("content")))

    if kind == "same_tenant_read":
        own_marker = case["resource_marker"]
        ev["expected_marker_present"] = own_marker in raw
        if status != 200:
            return "failed", f"Legitimate same-tenant access returned {status}", ev
        if parse != "ok" or not is_dict:
            return "inconclusive", "200 OK but the body was not a valid JSON object; cannot verify", ev
        if owner is None or body.get("id") is None:
            return "failed", "200 OK but the response lacked required id/owner metadata", ev
        if body.get("id") == case["resource_id"] and owner == req and own_marker in raw and not foreign_marker:
            return "passed", f"200 OK; resource {case['resource_id']} owned by {req}; marker verified", ev
        return "failed", "200 OK but resource, owner or content marker did not match the expected policy", ev

    if kind == "cross_tenant_read":
        exp_owner = case["resource_owner_tenant_id"]
        id_match = is_dict and body.get("id") == case["resource_id"]
        ev["resource_id_matches_expected"] = bool(id_match)
        leak = foreign_marker or (id_match and owner == exp_owner) or (_is2xx(status) and owner_foreign)
        if leak:
            what = case["resource_id"] if id_match else (_clip(body.get("id")) if is_dict else "foreign content")
            return "finding", (f"{status}; response exposed {what} owned by {owner or exp_owner} "
                               f"(foreign marker present: {'yes' if foreign_marker else 'no'})"), ev
        if status in DENIED:
            return "passed", f"Denied with {status}; no foreign resource data returned", ev
        if _is2xx(status):
            if parse != "ok" or not is_dict:
                return "inconclusive", f"{status} with an unreadable body; cannot rule out a leak", ev
            if owner is None:
                return "inconclusive", f"{status} without owner metadata; cannot rule out a leak", ev
            return "failed", f"Unexpected {status}: returned a resource other than the foreign one, no leak confirmed", ev
        return "failed", f"Unexpected status {status} (not an expected denial; no leak confirmed)", ev

    if kind == "list_scoped":
        if status != 200:
            return "failed", f"List endpoint returned {status}", ev
        if parse != "ok" or not is_dict:
            return "inconclusive", "200 OK but the list body was not a valid JSON object", ev
        items = body.get("items")
        if not isinstance(items, list):
            return "failed", "List response had an unexpected shape", ev
        rows = [i for i in items if isinstance(i, dict)]
        ev["ids_returned"] = [_clip(i.get("id")) for i in rows[:20]]
        foreign = [i for i in rows if isinstance(i.get("owner_tenant_id"), str) and i["owner_tenant_id"] != req]
        ev["foreign_ids"] = [_clip(i.get("id")) for i in foreign[:20]]
        if foreign or foreign_marker:
            if foreign:
                ev.update(resource_id=_clip(foreign[0].get("id")), owner_tenant_id=_clip(foreign[0].get("owner_tenant_id")))
            return "finding", f"List exposed {max(len(foreign), 1)} resource(s) owned by another tenant", ev
        if len(rows) != len(items) or any(not isinstance(i.get("owner_tenant_id"), str) for i in rows):
            return "inconclusive", "List items lacked ownership metadata; cannot verify scoping", ev
        expected = sorted(d["id"] for d in SEED_DOCUMENTS if d["owner_tenant_id"] == req)
        if sorted(i.get("id") for i in rows) != expected:
            return "failed", "List did not contain exactly the tenant's own documents", ev
        return "passed", f"List contained only {req} documents", ev

    return "inconclusive", "Unknown test kind", ev


def _redact_request(case: dict) -> dict:
    return {"method": case["method"], "path": case["path"], "identity": case["identity"],
            "requesting_tenant_id": case["requesting_tenant_id"], "headers": {"Authorization": "Bearer ********"}}


async def execute_case(client: httpx.AsyncClient, case: dict) -> dict:
    token = DEMO_USERS[case["identity"]]["token"]  # demo-only synthetic credential; never stored
    started = time.perf_counter()
    status, body, raw, parse, err = None, None, "", "empty", None
    try:
        resp = await asyncio.wait_for(
            client.request(case["method"], case["path"], headers={"Authorization": f"Bearer {token}"}),
            timeout=REQUEST_TIMEOUT_S)
        status, raw = resp.status_code, resp.text[:MAX_BODY_CHARS]
        if raw.strip():
            try:
                body, parse = json.loads(raw), "ok"
            except ValueError:
                parse = "malformed"
    except (httpx.HTTPError, asyncio.TimeoutError) as exc:
        err = type(exc).__name__
    result_status, observed, resp_ev = evaluate(case, status, body, raw, parse)
    if err:
        observed, resp_ev["error_class"] = f"Request failed ({err})", err
    evidence = {"request": _redact_request(case), "response": resp_ev, "expected": case["expected_outcome"],
                "timestamp": utcnow().isoformat() + "Z"}  # raw body is dropped here: never persisted
    return {"status": result_status, "observed": observed, "status_code": status, "evidence": evidence,
            "duration_ms": int((time.perf_counter() - started) * 1000)}


async def observed_mode(client: httpx.AsyncClient) -> str:
    """Display metadata only. Never used to decide a verdict."""
    try:
        r = await asyncio.wait_for(client.get("/api/demo/health"), timeout=REQUEST_TIMEOUT_S)
        return str(r.json().get("mode", "unknown"))
    except Exception:
        return "unknown"


# ---------------------------------------------------------------- persistence
def run_status(counts: dict) -> str:
    if counts["finding"]:
        return "findings"
    if counts["inconclusive"]:
        return "inconclusive"
    if counts["failed"]:
        return "failed"
    return "passed"


def _record_result(db: Session, run: TestRun, case: dict, out: dict) -> None:
    """Persist one result (and finding + occurrence) atomically."""
    res = TestResult(
        run_id=run.id, test_case_key=case["key"], test_name=case["name"],
        requesting_tenant_id=case["requesting_tenant_id"], resource_id=case.get("resource_id"), endpoint=case["path"],
        expected_outcome=case["expected_outcome"], actual_status_code=out["status_code"],
        observed_outcome=out["observed"], result_status=out["status"], duration_ms=out["duration_ms"],
        evidence_json=out["evidence"])
    db.add(res)
    db.flush()
    if out["status"] == "finding":
        finding = db.query(Finding).filter_by(test_case_key=case["key"]).order_by(Finding.id).first()
        if finding is None:  # original detection: evidence/time are written once and never updated
            r = out["evidence"]["response"]
            finding = Finding(
                test_case_key=case["key"], title=case["title"], severity=case["severity"], endpoint=case["path"],
                requesting_tenant_id=case["requesting_tenant_id"], resource_owner_tenant_id=r.get("owner_tenant_id"),
                resource_id=r.get("resource_id") or case.get("resource_id"), expected_behavior=case["expected_outcome"],
                actual_behavior=out["observed"], evidence_json=out["evidence"], first_detected_run_id=run.id)
            db.add(finding)
            db.flush()
        res.finding_id = finding.id
        db.add(FindingOccurrence(finding_id=finding.id, source="suite", run_id=run.id, result_id=res.id,
                                 demo_mode=run.demo_mode, evidence_json=out["evidence"]))
    db.commit()


def _finalize(db: Session, run_id: int, error: str | None) -> None:
    """Drive a run to a final state no matter what happened. Counters are derived from stored rows."""
    try:
        db.rollback()
        run = db.get(TestRun, run_id)
        existing = {r.test_case_key for r in db.query(TestResult).filter_by(run_id=run_id)}
        for case in SUITE:  # honest placeholders for checks that never executed
            if case["key"] not in existing:
                db.add(TestResult(
                    run_id=run_id, test_case_key=case["key"], test_name=case["name"],
                    requesting_tenant_id=case["requesting_tenant_id"], resource_id=case.get("resource_id"),
                    endpoint=case["path"], expected_outcome=case["expected_outcome"], actual_status_code=None,
                    observed_outcome="Not executed: the run was interrupted before this check",
                    result_status="inconclusive", duration_ms=0,
                    evidence_json={"request": _redact_request(case), "response": {"status_code": None},
                                   "expected": case["expected_outcome"], "timestamp": utcnow().isoformat() + "Z"}))
        db.flush()
        counts = {"passed": 0, "finding": 0, "failed": 0, "inconclusive": 0}
        for r in db.query(TestResult).filter_by(run_id=run_id):
            counts[r.result_status] += 1
        interrupted = error is not None or len(existing) < len(SUITE)
        run.passed_count, run.finding_count = counts["passed"], counts["finding"]
        run.failed_count, run.inconclusive_count = counts["failed"], counts["inconclusive"]
        run.status, run.completed_at = run_status(counts), utcnow()
        run.error_summary = error or ("Run was interrupted before completion" if interrupted else None)
        db.commit()
    except Exception:
        log.exception("Could not finalize run %s normally; applying fallback", run_id)
        db.rollback()
        run = db.get(TestRun, run_id)
        if run is not None:
            run.status, run.completed_at = "failed", utcnow()
            run.error_summary = "Run could not be finalized"
            db.commit()


async def run_suite(db: Session, client: httpx.AsyncClient) -> TestRun:
    run = TestRun(demo_mode=await observed_mode(client), status="running", total_tests=len(SUITE))
    db.add(run)
    db.commit()
    error = None
    try:
        for case in SUITE:
            out = await execute_case(client, case)
            _record_result(db, run, case, out)
    except Exception:
        log.exception("Run %s interrupted by an internal error", run.id)
        error = "Run interrupted by an internal error; remaining checks were not executed"
    finally:  # also reached on cancellation: a run never stays "running"
        _finalize(db, run.id, error)
    db.refresh(run)
    return run


def recover_interrupted_runs(db: Session) -> int:
    """Startup recovery: runs left 'running' by a crash or kill become 'inconclusive'."""
    ids = [r.id for r in db.query(TestRun).filter_by(status="running")]
    for rid in ids:
        _finalize(db, rid, "Run was interrupted (server stopped before it finished)")
    return len(ids)


def create_regression_test(db: Session, finding: Finding, name: str | None) -> RegressionTest:
    base = SUITE_BY_KEY.get(finding.test_case_key)
    if base is None:
        raise InvalidDefinition("This finding does not map to an approved test")
    case = copy.deepcopy(base)  # preserve the actual request scenario
    rt = RegressionTest(name=name or f"Regression: {finding.title}"[:120], source_finding_id=finding.id,
                        test_definition_json=case, expected_policy=case["expected_outcome"])
    db.add(rt)
    db.commit()
    return rt


async def run_regression(db: Session, client: httpx.AsyncClient, rt: RegressionTest) -> RegressionRun:
    case = parse_definition(rt.test_definition_json)  # re-validated before every execution
    mode = await observed_mode(client)
    out = await execute_case(client, case)
    rr = RegressionRun(regression_test_id=rt.id, demo_mode=mode, result_status=out["status"],
                       actual_status_code=out["status_code"], observed_outcome=out["observed"],
                       duration_ms=out["duration_ms"], evidence_json=out["evidence"])
    db.add(rr)
    db.flush()
    rt.last_run_at, rt.last_result_status = utcnow(), out["status"]
    if out["status"] == "finding" and db.get(Finding, rt.source_finding_id) is not None:
        db.add(FindingOccurrence(finding_id=rt.source_finding_id, source="regression", regression_run_id=rr.id,
                                 demo_mode=mode, evidence_json=out["evidence"]))
    db.commit()
    return rr
