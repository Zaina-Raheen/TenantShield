"""Core product workflow, history integrity, evidence handling. All IDs come from API responses."""
from .conftest import ALICE, BOB, by_key, run_suite, set_mode


def finding_for(client, key_resource):
    return next(f for f in client.get("/api/findings").json()["data"] if f["resource_id"] == key_resource)


def test_same_tenant_and_list_pass_in_both_modes(client):
    for mode in ("vulnerable", "fixed"):
        set_mode(client, mode)
        res = by_key(run_suite(client))
        for k in ("abc_reads_own", "xyz_reads_own", "abc_list_scoped"):
            assert res[k]["result_status"] == "passed", (mode, k)


def test_vulnerable_mode_detects_both_leaks(client):
    set_mode(client, "vulnerable")
    run = run_suite(client)
    res = by_key(run)
    assert res["abc_reads_xyz"]["result_status"] == "finding" and res["xyz_reads_abc"]["result_status"] == "finding"
    assert (run["passed_count"], run["finding_count"], run["failed_count"], run["inconclusive_count"]) == (3, 2, 0, 0)
    assert run["status"] == "findings" and run["error_summary"] is None
    assert len(client.get("/api/findings").json()["data"]) == 2


def test_fixed_mode_denies_and_returns_no_foreign_data(client):
    set_mode(client, "fixed")
    run = run_suite(client)
    assert run["status"] == "passed" and run["passed_count"] == 5 and run["finding_count"] == 0
    r = client.get("/api/demo/documents/doc_xyz_001", headers=ALICE)
    assert r.status_code == 404 and "XYZ-DEMO-MARKER" not in r.text
    assert client.get("/api/findings").json()["data"] == []


def test_evidence_is_minimal_and_redacted(client):
    set_mode(client, "vulnerable")
    run = run_suite(client)
    fid = by_key(run)["abc_reads_xyz"]["finding_id"]
    f = client.get(f"/api/findings/{fid}").json()["data"]
    ev = f["evidence"]
    assert ev["request"]["headers"] == {"Authorization": "Bearer ********"}
    assert ev["response"]["status_code"] == 200 and ev["response"]["owner_tenant_id"] == "tenant_xyz"
    assert ev["response"]["foreign_marker_present"] is True and ev["response"]["content_returned"] is True
    blob = client.get(f"/api/test-runs/{run['id']}").text + client.get(f"/api/findings/{fid}").text
    assert "demo-token" not in blob                      # no bearer tokens, redacted or not
    assert "Synthetic marksheet" not in blob             # no raw response bodies / document text
    assert "XYZ-DEMO-MARKER" not in blob                 # markers are reported as booleans, not stored text


def test_full_workflow_with_history_and_reintroduction(client):
    set_mode(client, "vulnerable")
    run1 = run_suite(client)
    fid = by_key(run1)["abc_reads_xyz"]["finding_id"]
    reg = client.post(f"/api/findings/{fid}/regression-tests")
    assert reg.status_code == 201
    tid = reg.json()["data"]["id"]
    assert reg.json()["data"]["definition"]["path"] == "/api/demo/documents/doc_xyz_001"
    assert client.post(f"/api/findings/{fid}/regression-tests").status_code == 409

    def retest():
        r = client.post(f"/api/regression-tests/{tid}/runs")
        assert r.status_code == 201
        return r.json()["data"]["result_status"]

    assert retest() == "finding"            # regression verdict is independent of the toggle
    set_mode(client, "fixed")
    assert retest() == "passed"
    run2 = run_suite(client)
    assert run2["status"] == "passed" and run2["passed_count"] == 5
    set_mode(client, "vulnerable")
    assert retest() == "finding"            # reintroduced vulnerability is detected again
    set_mode(client, "fixed")
    assert retest() == "passed"

    detail = client.get(f"/api/regression-tests/{tid}").json()["data"]
    assert [r["result_status"] for r in detail["runs"]] == ["passed", "finding", "passed", "finding"]
    old = client.get(f"/api/test-runs/{run1['id']}").json()["data"]
    assert old["status"] == "findings" and by_key(old)["abc_reads_xyz"]["result_status"] == "finding"
    f = client.get(f"/api/findings/{fid}").json()["data"]
    assert f["regression_status"] == "passed" and f["latest_regression_result"]["status"] == "passed"
    assert [h["result_status"] for h in f["regression_history"]] == ["passed", "finding", "passed", "finding"]


def test_finding_history_original_is_immutable(client):
    set_mode(client, "vulnerable")
    run1 = run_suite(client)
    fid = by_key(run1)["abc_reads_xyz"]["finding_id"]
    first = client.get(f"/api/findings/{fid}").json()["data"]
    assert first["occurrence_count"] == 1

    run2 = run_suite(client)
    assert by_key(run2)["abc_reads_xyz"]["finding_id"] == fid       # same finding, new occurrence
    tid = client.post(f"/api/findings/{fid}/regression-tests").json()["data"]["id"]
    rr = client.post(f"/api/regression-tests/{tid}/runs").json()["data"]
    set_mode(client, "fixed")
    client.post(f"/api/regression-tests/{tid}/runs")

    f = client.get(f"/api/findings/{fid}").json()["data"]
    assert f["occurrence_count"] == 3
    assert f["created_at"] == first["created_at"] and f["first_detected_run_id"] == run1["id"]
    assert f["original"]["evidence"] == first["evidence"] == first["original"]["evidence"]
    assert f["original"]["run_id"] == run1["id"]
    assert f["latest_occurrence"]["source"] == "regression" and f["latest_occurrence"]["regression_run_id"] == rr["id"]
    assert [o["run_id"] for o in f["occurrences"] if o["source"] == "suite"] == [run2["id"], run1["id"]]
    assert f["latest_regression_result"]["status"] == "passed"      # a fix never erases the occurrences
    assert client.get("/api/findings").json()["data"][0]["occurrence_count"] >= 1


def test_rename_and_soft_delete_retain_history(client):
    set_mode(client, "vulnerable")
    fid = by_key(run_suite(client))["abc_reads_xyz"]["finding_id"]
    tid = client.post(f"/api/findings/{fid}/regression-tests").json()["data"]["id"]
    client.post(f"/api/regression-tests/{tid}/runs")
    r = client.patch(f"/api/regression-tests/{tid}", json={"name": "  Renamed  "})
    assert r.status_code == 200 and r.json()["data"]["name"] == "Renamed"
    assert len(client.get(f"/api/regression-tests/{tid}").json()["data"]["runs"]) == 1

    assert client.delete(f"/api/regression-tests/{tid}").status_code == 400          # needs explicit confirm
    d = client.delete(f"/api/regression-tests/{tid}?confirm=true")
    assert d.status_code == 200 and d.json()["data"]["history_retained"] is True
    assert client.get("/api/regression-tests").json()["data"] == []
    assert client.get(f"/api/regression-tests/{tid}").status_code == 404
    assert client.post(f"/api/regression-tests/{tid}/runs").status_code == 404
    f = client.get(f"/api/findings/{fid}").json()["data"]
    assert f["regression"] is None and f["regression_status"] == "not_saved"
    assert len(f["regression_history"]) == 1 and f["regression_history"][0]["test_deleted"] is True
    assert client.post(f"/api/findings/{fid}/regression-tests").status_code == 201   # can save a fresh one


def test_regression_name_validation(client):
    set_mode(client, "vulnerable")
    fid = by_key(run_suite(client))["abc_reads_xyz"]["finding_id"]
    url = f"/api/findings/{fid}/regression-tests"
    for bad in ("", "   ", "\t\n", "x" * 121):
        r = client.post(url, json={"name": bad})
        assert r.status_code == 422 and "name" in r.json()["error"]["message"], bad
    r = client.post(url, json={"name": "  My test  "})
    assert r.status_code == 201 and r.json()["data"]["name"] == "My test"
    tid = r.json()["data"]["id"]
    for bad in ("", "  ", "y" * 121):
        assert client.patch(f"/api/regression-tests/{tid}", json={"name": bad}).status_code == 422
    assert client.patch(f"/api/regression-tests/{tid}", json={"name": "z" * 120}).status_code == 200


def test_client_tenant_header_not_trusted_and_auth_required(client):
    set_mode(client, "fixed")
    r = client.get("/api/demo/documents/doc_xyz_001", headers={**ALICE, "X-Tenant-ID": "tenant_xyz"})
    assert r.status_code == 404
    assert client.get("/api/demo/me", headers=BOB).json()["tenant_id"] == "tenant_xyz"
    assert client.get("/api/demo/documents/doc_abc_001").status_code == 401


def test_errors_have_consistent_shape(client):
    for r in (client.get("/api/findings/99999"), client.get("/api/test-runs/99999"), client.get("/api/nope")):
        assert r.status_code == 404 and set(r.json()["error"]) == {"status", "message"}
    r = client.post("/api/demo/dev/mode", json={"mode": "nope"})
    assert r.status_code == 422 and "mode" in r.json()["error"]["message"] and "nope" not in r.json()["error"]["message"]


def test_reset_demo_data_keeps_history_and_reset_history_needs_confirmation(client):
    set_mode(client, "vulnerable")
    run_suite(client)
    assert client.post("/api/demo/dev/reset").status_code == 200
    assert len(client.get("/api/test-runs").json()["data"]) == 1
    assert client.post("/api/dev/reset-history", json={"confirm": "yes"}).status_code == 422
    assert client.post("/api/dev/reset-history", json={"confirm": "DELETE_HISTORY"}).status_code == 200
    assert client.get("/api/test-runs").json()["data"] == []
