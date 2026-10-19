from typing import Literal

import httpx
from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, field_validator
from sqlalchemy import desc
from sqlalchemy.orm import Session

from . import config, engine
from .db import get_db
from .demo_api import DEMO_TENANTS, DEMO_USERS, require_local_dev, state as demo_state
from .models import (Finding, FindingOccurrence, RegressionRun, RegressionTest, TestResult, TestRun, utcnow)

router = APIRouter(prefix="/api")
NAME_MAX = 120


def ok(data):
    return {"data": data}


def iso(dt):
    return dt.isoformat() + "Z" if dt else None


# ---------- request models ----------
def _clean_name(v: str) -> str:
    v = v.strip()
    if not v:
        raise ValueError("name must not be empty or whitespace")
    if len(v) > NAME_MAX:
        raise ValueError(f"name must be at most {NAME_MAX} characters")
    return v


class SaveRegression(BaseModel):
    name: str | None = None

    @field_validator("name")
    @classmethod
    def _v(cls, v):
        return None if v is None else _clean_name(v)


class Rename(BaseModel):
    name: str

    @field_validator("name")
    @classmethod
    def _v(cls, v):
        return _clean_name(v)


class ResetHistory(BaseModel):
    confirm: Literal["DELETE_HISTORY"]


# ---------- serializers ----------
def s_run(r: TestRun):
    return {"id": r.id, "started_at": iso(r.started_at), "completed_at": iso(r.completed_at), "status": r.status,
            "demo_mode": r.demo_mode, "total_tests": r.total_tests, "passed_count": r.passed_count,
            "finding_count": r.finding_count, "failed_count": r.failed_count,
            "inconclusive_count": r.inconclusive_count, "error_summary": r.error_summary}


def s_result(x: TestResult):
    return {"id": x.id, "run_id": x.run_id, "test_case_key": x.test_case_key, "test_name": x.test_name,
            "requesting_tenant_id": x.requesting_tenant_id, "resource_id": x.resource_id, "endpoint": x.endpoint,
            "expected_outcome": x.expected_outcome, "actual_status_code": x.actual_status_code,
            "observed_outcome": x.observed_outcome, "result_status": x.result_status, "finding_id": x.finding_id,
            "duration_ms": x.duration_ms, "evidence": x.evidence_json}


def s_rrun(r: RegressionRun):
    return {"id": r.id, "run_at": iso(r.run_at), "demo_mode": r.demo_mode, "result_status": r.result_status,
            "actual_status_code": r.actual_status_code, "observed_outcome": r.observed_outcome,
            "duration_ms": r.duration_ms, "evidence": r.evidence_json}


def s_rtest(t: RegressionTest, with_runs=False):
    d = {"id": t.id, "name": t.name, "source_finding_id": t.source_finding_id,
         "endpoint": t.test_definition_json.get("path"), "expected_policy": t.expected_policy,
         "definition": t.test_definition_json, "created_at": iso(t.created_at), "last_run_at": iso(t.last_run_at),
         "last_result_status": t.last_result_status}
    if with_runs:
        d["runs"] = [s_rrun(r) for r in t.runs]
    return d


def s_occ(o: FindingOccurrence, evidence=False):
    d = {"id": o.id, "source": o.source, "run_id": o.run_id, "regression_run_id": o.regression_run_id,
         "detected_at": iso(o.detected_at), "demo_mode": o.demo_mode}
    if evidence:
        d["evidence"] = o.evidence_json
    return d


def active_regression(db: Session, finding_id: int) -> RegressionTest | None:
    return (db.query(RegressionTest).filter(RegressionTest.source_finding_id == finding_id,
                                            RegressionTest.deleted_at.is_(None))
            .order_by(desc(RegressionTest.id)).first())


def s_finding(f: Finding, db: Session, detail=False):
    occs = db.query(FindingOccurrence).filter_by(finding_id=f.id).order_by(FindingOccurrence.id).all()
    rt = active_regression(db, f.id)
    d = {"id": f.id, "title": f.title, "severity": f.severity, "endpoint": f.endpoint,
         "requesting_tenant_id": f.requesting_tenant_id, "resource_owner_tenant_id": f.resource_owner_tenant_id,
         "resource_id": f.resource_id, "expected_behavior": f.expected_behavior, "actual_behavior": f.actual_behavior,
         "first_detected_run_id": f.first_detected_run_id, "created_at": iso(f.created_at),
         "occurrence_count": len(occs), "last_detected_at": iso(occs[-1].detected_at if occs else f.created_at),
         "regression_test_id": rt.id if rt else None,
         "regression_status": (rt.last_result_status or "saved") if rt else "not_saved"}
    if not detail:
        return d
    first_run = db.get(TestRun, f.first_detected_run_id)
    hist = (db.query(RegressionRun, RegressionTest).join(RegressionTest, RegressionTest.id == RegressionRun.regression_test_id)
            .filter(RegressionTest.source_finding_id == f.id).order_by(desc(RegressionRun.id)).all())
    d.update({
        "evidence": f.evidence_json,  # original detection evidence (unchanged since first detection)
        "original": {"run_id": f.first_detected_run_id, "detected_at": iso(f.created_at),
                     "demo_mode": first_run.demo_mode if first_run else "unknown", "evidence": f.evidence_json},
        "latest_occurrence": s_occ(occs[-1], evidence=True) if occs else None,
        "occurrences": [s_occ(o) for o in reversed(occs[-100:])],
        "latest_regression_result": ({"status": hist[0][0].result_status, "run_at": iso(hist[0][0].run_at),
                                      "regression_test_id": hist[0][1].id} if hist else None),
        "regression_history": [{**s_rrun(r), "regression_test_id": t.id, "test_name": t.name,
                                "test_deleted": t.deleted_at is not None} for r, t in hist],
        "requesting_tenant_name": DEMO_TENANTS.get(f.requesting_tenant_id, {}).get("name"),
        "resource_owner_tenant_name": DEMO_TENANTS.get(f.resource_owner_tenant_id, {}).get("name"),
        "remediation": ("Enforce resource ownership on the server: compare the resource's tenant with the tenant "
                        "derived from the authenticated identity before returning data, and scope collection "
                        "queries by that tenant."),
        "regression": s_rtest(rt, with_runs=True) if rt else None,
        "first_detected_demo_mode": first_run.demo_mode if first_run else "unknown",
    })
    return d


def get_or_404(db, model, ident, label):
    obj = db.get(model, ident)
    if obj is None:
        raise HTTPException(404, f"{label} {ident} not found")
    return obj


def get_regression_or_404(db: Session, test_id: int) -> RegressionTest:
    t = db.get(RegressionTest, test_id)
    if t is None or t.deleted_at is not None:
        raise HTTPException(404, f"Regression test {test_id} not found")
    return t


async def locked(fn):
    """Run fn(client) under the shared run lock; overlapping executions are rejected with 409."""
    if engine.run_lock.locked():
        raise HTTPException(409, "A test run is already in progress")
    async with engine.run_lock:
        client = engine.make_demo_client()
        try:
            return await fn(client)
        finally:
            await client.aclose()


# ---------- health / demo ----------
@router.get("/health")
def health():
    return ok({"service": "tenantshield", "status": "ok", "environment": config.environment()})


@router.get("/demo/status")
async def demo_status():
    data = {"reachable": False, "mode": "unknown"}
    client = engine.make_demo_client()
    try:
        h = await client.get("/api/demo/health")
        h.raise_for_status()
        data = {"reachable": True, "mode": h.json()["mode"]}
    except (httpx.HTTPError, ValueError, KeyError):
        pass
    finally:
        await client.aclose()
    data["dev_controls_enabled"] = config.dev_controls_enabled()
    data["vulnerable_demo_enabled"] = config.vulnerable_demo_enabled()
    return ok(data)


@router.get("/demo/tenants")
def demo_tenants():
    tenants = []
    for t in DEMO_TENANTS.values():
        tenants.append({**t, "users": [{"user_id": u["user_id"], "display_name": u["display_name"]}
                                       for u in DEMO_USERS.values() if u["tenant_id"] == t["id"]],
                        "documents": [{"id": d["id"], "title": d["title"]} for d in demo_state.documents.values()
                                      if d["owner_tenant_id"] == t["id"]]})
    return ok(tenants)


# ---------- test runs ----------
@router.post("/test-runs", status_code=201)
async def create_run(db: Session = Depends(get_db)):
    return ok(s_run(await locked(lambda c: engine.run_suite(db, c))))


@router.get("/test-runs")
def list_runs(db: Session = Depends(get_db)):
    return ok([s_run(r) for r in db.query(TestRun).order_by(desc(TestRun.id)).all()])


@router.get("/test-runs/{run_id}")
def get_run(run_id: int, db: Session = Depends(get_db)):
    r = get_or_404(db, TestRun, run_id, "Run")
    return ok({**s_run(r), "results": [s_result(x) for x in r.results]})


# ---------- findings ----------
@router.get("/findings")
def list_findings(db: Session = Depends(get_db)):
    return ok([s_finding(f, db) for f in db.query(Finding).order_by(desc(Finding.id)).all()])


@router.get("/findings/{finding_id}")
def get_finding(finding_id: int, db: Session = Depends(get_db)):
    return ok(s_finding(get_or_404(db, Finding, finding_id, "Finding"), db, detail=True))


@router.post("/findings/{finding_id}/regression-tests", status_code=201)
def save_regression(finding_id: int, body: SaveRegression | None = None, db: Session = Depends(get_db)):
    f = get_or_404(db, Finding, finding_id, "Finding")
    if active_regression(db, f.id):
        raise HTTPException(409, "This finding already has a saved regression test")
    try:
        return ok(s_rtest(engine.create_regression_test(db, f, body.name if body else None)))
    except engine.InvalidDefinition as exc:
        raise HTTPException(422, str(exc))


# ---------- regression tests ----------
@router.get("/regression-tests")
def list_regression(db: Session = Depends(get_db)):
    q = db.query(RegressionTest).filter(RegressionTest.deleted_at.is_(None)).order_by(desc(RegressionTest.id))
    return ok([s_rtest(t) for t in q.all()])


@router.get("/regression-tests/{test_id}")
def get_regression(test_id: int, db: Session = Depends(get_db)):
    return ok(s_rtest(get_regression_or_404(db, test_id), with_runs=True))


@router.patch("/regression-tests/{test_id}")
def rename_regression(test_id: int, body: Rename, db: Session = Depends(get_db)):
    t = get_regression_or_404(db, test_id)
    t.name = body.name  # history is keyed by id, so renaming never touches past results
    db.commit()
    return ok(s_rtest(t))


@router.post("/regression-tests/{test_id}/runs", status_code=201)
async def run_regression(test_id: int, db: Session = Depends(get_db)):
    t = get_regression_or_404(db, test_id)
    try:
        engine.parse_definition(t.test_definition_json)
    except engine.InvalidDefinition:
        raise HTTPException(422, "Stored test definition is invalid; the test was not executed")
    return ok(s_rrun(await locked(lambda c: engine.run_regression(db, c, t))))


@router.delete("/regression-tests/{test_id}")
def delete_regression(test_id: int, confirm: bool = Query(default=False), db: Session = Depends(get_db)):
    """Soft delete: hides the test but RETAINS its retest history and the finding (see README retention policy)."""
    if not confirm:
        raise HTTPException(400, "Deletion must be confirmed explicitly (confirm=true)")
    t = get_regression_or_404(db, test_id)
    t.deleted_at = utcnow()
    db.commit()
    return ok({"deleted": test_id, "history_retained": True})


# ---------- activity / dev ----------
@router.get("/activity")
def activity(db: Session = Depends(get_db)):
    ev = []
    for r in db.query(TestRun).order_by(desc(TestRun.id)).limit(10):
        detail = {"findings": f"{r.finding_count} finding(s) confirmed", "passed": "all configured checks passed",
                  "inconclusive": f"{r.inconclusive_count} check(s) inconclusive",
                  "failed": f"{r.failed_count} test failure(s)"}.get(r.status, r.status)
        ev.append({"at": iso(r.started_at), "text": f"Run #{r.id}: {detail}", "status": r.status})
    for f in db.query(Finding).order_by(desc(Finding.id)).limit(10):
        ev.append({"at": iso(f.created_at), "text": f"Finding detected: {f.title}", "status": "finding"})
    for rr in db.query(RegressionRun).order_by(desc(RegressionRun.id)).limit(10):
        ev.append({"at": iso(rr.run_at), "text": f"Regression test #{rr.regression_test_id} retested: "
                   + {"passed": "passed (fix verified)", "finding": "still vulnerable"}.get(rr.result_status, rr.result_status),
                   "status": rr.result_status})
    ev.sort(key=lambda e: e["at"], reverse=True)
    return ok(ev[:8])


@router.post("/dev/reset-history", dependencies=[Depends(require_local_dev)])
def reset_history(body: ResetHistory, db: Session = Depends(get_db)):
    """Development-only, local-only, explicitly confirmed wipe of ALL history. Not part of normal operation."""
    for m in (FindingOccurrence, RegressionRun, RegressionTest, TestResult, Finding, TestRun):
        db.query(m).delete()
    db.commit()
    return ok({"status": "history_deleted"})
