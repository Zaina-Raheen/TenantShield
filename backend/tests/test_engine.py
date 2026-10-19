"""Verdict logic (pure), failure modes (timeouts/errors/malformed), run exception-safety, migrations."""
import asyncio
import json

import httpx
import pytest
from sqlalchemy import create_engine, inspect, text

from app import engine
from app.migrations import SCHEMA_VERSION, migrate
from app.models import Finding, FindingOccurrence, TestResult, TestRun
from .conftest import arun, by_key, mock_client, run_suite, set_mode, tracked_demo_client

XYZ = {"id": "doc_xyz_001", "owner_tenant_id": "tenant_xyz", "title": "t", "content": "XYZ-DEMO-MARKER | x"}
ABC = {"id": "doc_abc_001", "owner_tenant_id": "tenant_abc", "title": "t", "content": "ABC-DEMO-MARKER | x"}
ABC_ITEM = {"id": "doc_abc_001", "owner_tenant_id": "tenant_abc", "title": "t"}
XYZ_ITEM = {"id": "doc_xyz_001", "owner_tenant_id": "tenant_xyz", "title": "t"}
MAL = "<html>oops</html>"


def ev(key, status, body=None, raw=None, parse=None):
    raw = raw if raw is not None else ("" if body is None else json.dumps(body))
    parse = parse or ("ok" if body is not None else "empty")
    return engine.evaluate(engine.SUITE_BY_KEY[key], status, body, raw, parse)[0]


CROSS, OWN, LIST = "abc_reads_xyz", "abc_reads_own", "abc_list_scoped"


@pytest.mark.parametrize("args, expected", [
    # --- cross-tenant reads
    ((CROSS, 200, XYZ), "finding"),
    ((CROSS, 200, {**XYZ, "id": "doc_xyz_999"}), "finding"),                    # altered resource id, still foreign
    ((CROSS, 200, {"id": "doc_xyz_001", "content": "XYZ-DEMO-MARKER"}), "finding"),   # no owner metadata, marker proves it
    ((CROSS, 200, {"id": "doc_xyz_001", "content": "x"}), "inconclusive"),      # no owner, no marker: cannot conclude
    ((CROSS, 200, {**XYZ, "content": "no marker here"}), "finding"),            # owner proves exposure even w/o marker
    ((CROSS, 200, None, MAL, "malformed"), "inconclusive"),
    ((CROSS, 200, None, "garbage XYZ-DEMO-MARKER", "malformed"), "finding"),
    ((CROSS, 404, {"error": {"message": "Document not found"}}), "passed"),
    ((CROSS, 404, None, MAL, "malformed"), "passed"),
    ((CROSS, 403, None), "passed"),
    ((CROSS, 404, XYZ), "finding"),                                             # denial status but leaked data
    ((CROSS, 403, None, "XYZ-DEMO-MARKER leaked", "malformed"), "finding"),
    ((CROSS, 200, ABC), "failed"),                                              # got own doc: unexpected, no leak
    ((CROSS, 401, {"error": {}}), "failed"),
    ((CROSS, 302, None), "failed"),
    ((CROSS, 500, {"error": {}}), "inconclusive"),
    ((CROSS, 503, None), "inconclusive"),
    ((CROSS, None, None), "inconclusive"),
    # --- same-tenant reads
    ((OWN, 200, ABC), "passed"),
    ((OWN, 200, {**ABC, "content": "no marker"}), "failed"),                    # marker mismatch
    ((OWN, 200, {**ABC, "content": "XYZ-DEMO-MARKER"}), "failed"),
    ((OWN, 200, {**ABC, "owner_tenant_id": "tenant_xyz"}), "failed"),
    ((OWN, 200, {"id": "doc_abc_001", "content": "ABC-DEMO-MARKER"}), "failed"),      # missing owner metadata
    ((OWN, 200, {**ABC, "id": "doc_other"}), "failed"),                         # altered resource id
    ((OWN, 200, None, MAL, "malformed"), "inconclusive"),
    ((OWN, 404, {"error": {}}), "failed"),
    ((OWN, 500, None), "inconclusive"),
    # --- list endpoint
    ((LIST, 200, {"items": [ABC_ITEM]}), "passed"),
    ((LIST, 200, {"items": [ABC_ITEM, XYZ_ITEM]}), "finding"),
    ((LIST, 200, {"items": [{"id": "doc_abc_001", "title": "t"}]}), "inconclusive"),   # no owner metadata
    ((LIST, 200, {"items": [XYZ_ITEM, {"id": "doc_abc_001"}]}), "finding"),
    ((LIST, 200, {"items": []}), "failed"),
    ((LIST, 200, {"items": "nope"}), "failed"),
    ((LIST, 200, ["a"]), "inconclusive"),
    ((LIST, 200, None, MAL, "malformed"), "inconclusive"),
    ((LIST, 403, {"error": {}}), "failed"),
    ((LIST, 500, None), "inconclusive"),
])
def test_evaluate_matrix(args, expected):
    assert ev(*args) == expected


def test_evaluate_evidence_never_contains_bodies():
    _, _, e = engine.evaluate(engine.SUITE_BY_KEY[CROSS], 200, XYZ, json.dumps(XYZ), "ok")
    assert "XYZ-DEMO-MARKER" not in json.dumps(e) and "content" not in e
    assert e["foreign_marker_present"] is True and e["owner_tenant_id"] == "tenant_xyz"


# ---------------------------------------------------------------- transport failures
def _exec(handler, key=CROSS):
    async def go():
        c = mock_client(handler)
        try:
            return await engine.execute_case(c, engine.SUITE_BY_KEY[key])
        finally:
            await c.aclose()
    return arun(go())


def test_timeout_connection_error_and_server_error_are_inconclusive(monkeypatch):
    def raise_timeout(request): raise httpx.ReadTimeout("slow", request=request)
    def raise_conn(request): raise httpx.ConnectError("down", request=request)
    out = _exec(raise_timeout)
    assert out["status"] == "inconclusive" and out["evidence"]["response"]["error_class"] == "ReadTimeout"
    assert _exec(raise_conn)["status"] == "inconclusive"
    assert _exec(lambda r: httpx.Response(500, text="boom"))["status"] == "inconclusive"

    monkeypatch.setattr(engine, "REQUEST_TIMEOUT_S", 0.05)
    async def slow(request):
        await asyncio.sleep(1)
        return httpx.Response(200, json=XYZ)
    out = _exec(slow)
    assert out["status"] == "inconclusive" and out["evidence"]["response"]["error_class"] == "TimeoutError"


def test_malformed_json_from_server_is_handled():
    out = _exec(lambda r: httpx.Response(200, text="{not json", headers={"content-type": "application/json"}))
    assert out["status"] == "inconclusive" and out["evidence"]["response"]["body_parse"] == "malformed"


def test_unavailable_target_run_is_inconclusive_never_secure(client, monkeypatch):
    def down(request): raise httpx.ConnectError("down", request=request)
    monkeypatch.setattr(engine, "make_demo_client", lambda: mock_client(down))
    run = run_suite(client)
    assert run["status"] == "inconclusive" and run["inconclusive_count"] == 5 and run["passed_count"] == 0
    assert client.get("/api/findings").json()["data"] == []
    assert client.get("/api/demo/status").json()["data"]["reachable"] is False


def test_verdicts_ignore_the_demo_mode_label(client, monkeypatch):
    """A target that LABELS itself 'fixed' but leaks must still produce findings."""
    def leaky(request):
        p = request.url.path
        if p == "/api/demo/health":
            return httpx.Response(200, json={"status": "ok", "mode": "fixed"})
        if p == "/api/demo/documents":
            return httpx.Response(200, json={"items": [ABC_ITEM]})
        return httpx.Response(200, json=ABC if p.endswith("abc_001") else XYZ)
    monkeypatch.setattr(engine, "make_demo_client", lambda: mock_client(leaky))
    run = run_suite(client)
    assert run["demo_mode"] == "fixed" and run["finding_count"] == 2 and run["passed_count"] == 3


# ---------------------------------------------------------------- exception safety
def test_exception_mid_suite_still_finalizes_run(client, monkeypatch):
    set_mode(client, "fixed")
    real, calls = engine.execute_case, {"n": 0}

    async def flaky(c, case):
        calls["n"] += 1
        if calls["n"] == 3:
            raise RuntimeError("boom-secret /tmp/internal")
        return await real(c, case)
    monkeypatch.setattr(engine, "execute_case", flaky)
    monkeypatch.setattr(engine, "make_demo_client", tracked_demo_client)

    r = client.post("/api/test-runs")
    assert r.status_code == 201
    run = client.get(f"/api/test-runs/{r.json()['data']['id']}").json()["data"]
    assert run["status"] == "inconclusive" and run["completed_at"] is not None
    assert "interrupted" in run["error_summary"] and "boom" not in json.dumps(run) and "/tmp" not in json.dumps(run)
    assert (run["passed_count"], run["inconclusive_count"], run["total_tests"]) == (2, 3, 5)
    assert sum(run[k] for k in ("passed_count", "finding_count", "failed_count", "inconclusive_count")) == run["total_tests"]
    res = by_key(run)
    assert len(res) == 5 and res["abc_reads_own"]["result_status"] == "passed"      # earlier results preserved
    assert "Not executed" in res["xyz_reads_own"]["observed_outcome"]
    assert tracked_demo_client.__globals__["TrackedClient"].closed is True           # HTTP client closed
    monkeypatch.setattr(engine, "execute_case", real)
    assert run_suite(client)["status"] == "passed"                                    # lock released; next run is fine


def test_persistence_failure_mid_suite_is_contained(client, monkeypatch):
    set_mode(client, "vulnerable")
    real, calls = engine._record_result, {"n": 0}

    def flaky(db, run, case, out):
        calls["n"] += 1
        if calls["n"] == 2:
            raise RuntimeError("db exploded")
        return real(db, run, case, out)
    monkeypatch.setattr(engine, "_record_result", flaky)
    run = run_suite(client)
    assert run["status"] != "running" and run["error_summary"] and len(run["results"]) == 5
    assert run["passed_count"] + run["finding_count"] + run["failed_count"] + run["inconclusive_count"] == 5


def test_overlapping_run_rejected_and_lock_released(client):
    arun(engine.run_lock.acquire())
    try:
        r = client.post("/api/test-runs")
        assert r.status_code == 409 and "already in progress" in r.json()["error"]["message"]
    finally:
        engine.run_lock.release()
    assert client.post("/api/test-runs").status_code == 201


def test_stuck_running_runs_are_recovered(client, db):
    run = TestRun(status="running", total_tests=5, demo_mode="vulnerable")
    db.add(run)
    db.commit()
    assert engine.recover_interrupted_runs(db) == 1
    db.refresh(run)
    assert run.status == "inconclusive" and run.completed_at and "interrupted" in run.error_summary
    assert run.inconclusive_count == 5
    assert db.query(TestResult).filter_by(run_id=run.id).count() == 5
    assert engine.recover_interrupted_runs(db) == 0


# ---------------------------------------------------------------- migrations
def test_legacy_database_is_upgraded_without_data_loss(tmp_path):
    e = create_engine(f"sqlite:///{tmp_path}/legacy.db")
    from app.db import Base
    Base.metadata.create_all(e)
    with e.begin() as c:   # recreate the pre-upgrade (v1) schema
        c.exec_driver_sql("DROP TABLE finding_occurrences")
        c.exec_driver_sql("ALTER TABLE test_runs DROP COLUMN error_summary")
        c.exec_driver_sql("ALTER TABLE regression_tests DROP COLUMN deleted_at")
        c.exec_driver_sql("PRAGMA user_version = 0")
        t = "2026-01-01 10:00:00.000000"
        ev = json.dumps({"response": {"status_code": 200}})
        c.execute(text("INSERT INTO test_runs (id,started_at,completed_at,status,demo_mode,total_tests,passed_count,finding_count,failed_count,inconclusive_count) VALUES (1,:t,:t,'findings','vulnerable',5,3,2,0,0)"), {"t": t})
        c.execute(text("INSERT INTO findings (id,test_case_key,title,severity,endpoint,requesting_tenant_id,resource_owner_tenant_id,resource_id,expected_behavior,actual_behavior,evidence_json,first_detected_run_id,created_at) VALUES (1,'abc_reads_xyz','T','high','/p','tenant_abc','tenant_xyz','doc_xyz_001','exp','act',:ev,1,:t)"), {"ev": ev, "t": t})
        c.execute(text("INSERT INTO test_results (id,run_id,test_case_key,test_name,requesting_tenant_id,resource_id,endpoint,expected_outcome,actual_status_code,observed_outcome,result_status,finding_id,duration_ms,evidence_json) VALUES (1,1,'abc_reads_xyz','n','tenant_abc','doc_xyz_001','/p','e',200,'o','finding',1,1,:ev)"), {"ev": ev})
        c.execute(text("INSERT INTO regression_tests (id,name,source_finding_id,test_definition_json,expected_policy,created_at) VALUES (1,'R',1,'{}','p',:t)"), {"t": t})
        c.execute(text("INSERT INTO regression_runs (id,regression_test_id,run_at,demo_mode,result_status,actual_status_code,observed_outcome,duration_ms,evidence_json) VALUES (1,1,:t,'vulnerable','finding',200,'o',1,:ev)"), {"t": t, "ev": ev})
        c.execute(text("INSERT INTO regression_runs (id,regression_test_id,run_at,demo_mode,result_status,actual_status_code,observed_outcome,duration_ms,evidence_json) VALUES (2,1,:t,'fixed','passed',404,'o',1,:ev)"), {"t": t, "ev": ev})

    migrate(e)
    migrate(e)   # idempotent
    cols = lambda tbl: {c["name"] for c in inspect(e).get_columns(tbl)}
    assert "error_summary" in cols("test_runs") and "deleted_at" in cols("regression_tests")
    with e.connect() as c:
        assert c.exec_driver_sql("PRAGMA user_version").scalar() == SCHEMA_VERSION
        assert c.exec_driver_sql("SELECT count(*) FROM test_runs").scalar() == 1
        assert c.exec_driver_sql("SELECT count(*) FROM regression_runs").scalar() == 2
        assert c.exec_driver_sql("SELECT created_at, actual_behavior FROM findings").one() == (t, "act")
        rows = c.exec_driver_sql("SELECT source, run_id, regression_run_id FROM finding_occurrences ORDER BY id").all()
    assert rows == [("suite", 1, None), ("regression", None, 1)]       # backfilled once, passed retest not counted
