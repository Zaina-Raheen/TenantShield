"""Access-control, environment gating, target validation, and definition validation."""
import pytest
from fastapi.testclient import TestClient

from app import config, engine
from app.main import app
from .conftest import ALICE, REMOTE, arun, set_mode


# ---------------------------------------------------------------- environment gating
def test_production_disables_dev_controls_and_vulnerable_path(client, monkeypatch):
    set_mode(client, "vulnerable")
    monkeypatch.setenv("TENANTSHIELD_ENV", "production")
    for path, body in (("/api/demo/dev/mode", {"mode": "fixed"}), ("/api/demo/dev/reset", None),
                       ("/api/dev/reset-history", {"confirm": "DELETE_HISTORY"})):
        r = client.post(path, json=body) if body else client.post(path)
        assert r.status_code == 403, path
    h = client.get("/api/demo/health").json()
    assert h["mode"] == "fixed" and h["vulnerable_demo_enabled"] is False
    r = client.get("/api/demo/documents/doc_xyz_001", headers=ALICE)   # state says vulnerable; still denied
    assert r.status_code == 404 and "XYZ-DEMO-MARKER" not in r.text
    status = client.get("/api/demo/status").json()["data"]
    assert status["dev_controls_enabled"] is False and status["vulnerable_demo_enabled"] is False


def test_unset_environment_defaults_to_safe_production(client, monkeypatch):
    monkeypatch.delenv("TENANTSHIELD_ENV")
    assert config.environment() == "production"
    assert client.post("/api/demo/dev/mode", json={"mode": "fixed"}).status_code == 403


def test_vulnerable_mode_requires_explicit_opt_in(client, monkeypatch):
    monkeypatch.delenv("TENANTSHIELD_ENABLE_VULNERABLE_DEMO")
    r = client.post("/api/demo/dev/mode", json={"mode": "vulnerable"})
    assert r.status_code == 403 and "TENANTSHIELD_ENABLE_VULNERABLE_DEMO" in r.json()["error"]["message"]
    assert client.get("/api/demo/health").json()["mode"] == "fixed"
    assert client.get("/api/demo/documents/doc_xyz_001", headers=ALICE).status_code == 404
    assert client.post("/api/demo/dev/mode", json={"mode": "fixed"}).status_code == 200   # safe direction allowed


# ---------------------------------------------------------------- local-only access
@pytest.fixture()
def remote():
    return TestClient(app, client=REMOTE, raise_server_exceptions=False)


def test_remote_clients_are_rejected(client, remote):
    assert remote.get("/api/health").status_code == 403
    for method, path, body in (("post", "/api/test-runs", None), ("post", "/api/demo/dev/mode", {"mode": "vulnerable"}),
                               ("post", "/api/dev/reset-history", {"confirm": "DELETE_HISTORY"}),
                               ("delete", "/api/regression-tests/1?confirm=true", None)):
        r = getattr(remote, method)(path, **({"json": body} if body else {}))
        assert r.status_code == 403 and "local machine" in r.json()["error"]["message"], path


def test_origin_header_is_not_authentication(client, remote):
    r = remote.post("/api/demo/dev/mode", json={"mode": "vulnerable"}, headers={"Origin": "http://localhost:5173"})
    assert r.status_code == 403
    r = remote.post("/api/demo/dev/mode", json={"mode": "vulnerable"}, headers={"Origin": "http://testserver"})
    assert r.status_code == 403


def test_optional_remote_reads_never_allow_writes(client, remote, monkeypatch):
    monkeypatch.setenv("TENANTSHIELD_ALLOW_REMOTE_READS", "1")
    assert remote.get("/api/health").status_code == 200
    assert remote.post("/api/test-runs").status_code == 403
    assert remote.post("/api/demo/dev/mode", json={"mode": "fixed"}).status_code == 403
    assert remote.delete("/api/regression-tests/1?confirm=true").status_code == 403


def test_loopback_variants_accepted():
    for host in ("127.0.0.1", "::1", "::ffff:127.0.0.1"):
        assert config.is_loopback(host)
    for host in ("203.0.113.9", "0.0.0.0", "localhost", "", None, "not-an-ip"):
        assert not config.is_loopback(host)


# ---------------------------------------------------------------- Origin (CSRF) behaviour
def test_origin_rules_for_state_changes(client):
    body = {"mode": "fixed"}
    assert client.post("/api/demo/dev/mode", json=body).status_code == 200                    # no Origin: local script
    assert client.post("/api/demo/dev/mode", json=body, headers={"Origin": "http://localhost:5173"}).status_code == 200
    assert client.post("/api/demo/dev/mode", json=body, headers={"Origin": "http://testserver"}).status_code == 200
    for evil in ("https://evil.example", "null", "http://localhost:9999"):
        for path, b in (("/api/demo/dev/mode", body), ("/api/test-runs", None),
                        ("/api/dev/reset-history", {"confirm": "DELETE_HISTORY"})):
            r = client.post(path, headers={"Origin": evil}, **({"json": b} if b else {}))
            assert r.status_code == 403 and "Cross-origin" in r.json()["error"]["message"], (evil, path)
    assert client.get("/api/findings", headers={"Origin": "https://evil.example"}).status_code == 200  # reads unaffected


def test_unknown_host_header_rejected(client):
    assert client.get("/api/health", headers={"Host": "attacker.example"}).status_code == 400


# ---------------------------------------------------------------- target validation
def test_invalid_target_configuration_is_rejected(monkeypatch):
    for bad in ("http://127.0.0.1:9000", "https://example.com", "tcp://x", "http://localhost", "", "INPROCESS "):
        monkeypatch.setenv("TENANTSHIELD_DEMO_TARGET", bad)
        with pytest.raises(config.ConfigError):
            engine.make_demo_client()
    monkeypatch.delenv("TENANTSHIELD_DEMO_TARGET")
    monkeypatch.setenv("TENANTSHIELD_DEMO_API_BASE_URL", "http://127.0.0.1:8000")
    with pytest.raises(config.ConfigError):
        engine.make_demo_client()


def test_server_refuses_to_start_with_bad_target(monkeypatch):
    monkeypatch.setenv("TENANTSHIELD_DEMO_TARGET", "http://evil.example")
    with pytest.raises(config.ConfigError):
        with TestClient(app):
            pass


def test_approved_target_works_and_reaches_only_the_demo_app(client):
    async def go():
        c = engine.make_demo_client()
        try:
            ok = await c.get("/api/demo/health")
            other = await c.get("/api/findings")          # a TENANTSHIELD route: not reachable from the engine
            ext = await c.get("/api/test-runs")
            return ok.status_code, ok.json()["status"], other.status_code, ext.status_code
        finally:
            await c.aclose()
    assert arun(go()) == (200, "ok", 404, 404)


# ---------------------------------------------------------------- definition validation
BASE = dict(engine.SUITE_BY_KEY["abc_reads_xyz"])


@pytest.mark.parametrize("patch", [
    {"path": "http://evil.example/api/demo/documents/doc_xyz_001"},
    {"path": "//evil.example/x"},
    {"path": "/api/findings"},
    {"path": "/api/demo/documents/../findings"},
    {"path": "/api/demo/documents/doc_xyz_001?x=1"},
    {"method": "POST"}, {"method": "DELETE"},
    {"identity": "alice_abc", "requesting_tenant_id": "tenant_xyz"},
    {"identity": "mallory"},
    {"kind": "delete_everything"},
    {"resource_id": "../../etc/passwd"},
    {"resource_marker": "XYZ-DEMO-MARKER-FORGED"},
    {"resource_owner_tenant_id": "tenant_abc"},      # cross-tenant test must target a foreign owner
    {"target": "http://evil.example"},               # unknown keys rejected
    {"name": ""},
])
def test_invalid_definitions_rejected(patch):
    with pytest.raises(engine.InvalidDefinition):
        engine.parse_definition({**BASE, **patch})


def test_all_builtin_cases_are_valid_and_normalised():
    for case in engine.SUITE:
        assert engine.parse_definition(case) == case
    assert [c["key"] for c in engine.SUITE] == ["abc_reads_own", "abc_reads_xyz", "xyz_reads_own", "xyz_reads_abc",
                                                "abc_list_scoped"]


def test_corrupted_stored_definition_is_never_executed(client, db):
    from app.models import RegressionRun, RegressionTest
    set_mode(client, "vulnerable")
    fid = client.get("/api/findings").json()["data"] or None
    run = client.post("/api/test-runs").json()["data"]
    detail = client.get(f"/api/test-runs/{run['id']}").json()["data"]
    fid = next(r["finding_id"] for r in detail["results"] if r["finding_id"])
    tid = client.post(f"/api/findings/{fid}/regression-tests").json()["data"]["id"]
    t = db.get(RegressionTest, tid)
    t.test_definition_json = {**t.test_definition_json, "path": "http://evil.example/steal", "method": "POST"}
    db.commit()
    r = client.post(f"/api/regression-tests/{tid}/runs")
    assert r.status_code == 422 and "not executed" in r.json()["error"]["message"]
    assert db.query(RegressionRun).filter_by(regression_test_id=tid).count() == 0


def test_internal_errors_do_not_leak_details(client, monkeypatch):
    def boom():
        raise RuntimeError("secret-token /home/claude/private/path.py")
    monkeypatch.setattr(engine, "make_demo_client", boom)
    r = client.post("/api/test-runs")
    assert r.status_code == 500 and r.json() == {"error": {"status": 500, "message": "Internal server error"}}
    assert "secret" not in r.text and "/home" not in r.text and "Traceback" not in r.text
