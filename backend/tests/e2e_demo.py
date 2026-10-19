#!/usr/bin/env python3
"""Live end-to-end walk-through of the full Test → Prove → Preserve → Verify workflow.

Default: starts its OWN server on a free loopback port with a throw-away temp database, runs everything,
stops the server and deletes only that temp directory. It never touches backend/data/.
Optional: --base-url http://127.0.0.1:8000 runs against an already-running local server (any DB state; all IDs come
from API responses and nothing is deleted or reset except by the demo's own mode toggle).
"""
import argparse, os, shutil, socket, subprocess, sys, tempfile, time
from pathlib import Path

import httpx

BACKEND = Path(__file__).resolve().parents[1]
FAILURES = []


def check(label, cond, detail=""):
    print(f"[{'PASS' if cond else 'FAIL'}] {label}" + (f"  ({detail})" if detail and not cond else ""))
    if not cond:
        FAILURES.append(label)
        raise SystemExit(f"E2E FAILED at: {label} {detail}")


def expect(resp, status, label):
    check(f"{label} -> HTTP {status}", resp.status_code == status, f"got {resp.status_code}: {resp.text[:200]}")
    return resp.json()


def free_port():
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def start_server():
    tmp = tempfile.mkdtemp(prefix="tenantshield-e2e-")
    port = free_port()
    env = {**os.environ, "TENANTSHIELD_DATABASE_URL": f"sqlite:///{tmp}/e2e.db", "TENANTSHIELD_ENV": "development",
           "TENANTSHIELD_ENABLE_VULNERABLE_DEMO": "1"}
    env.pop("TENANTSHIELD_DEMO_API_BASE_URL", None)
    proc = subprocess.Popen([sys.executable, "-m", "uvicorn", "app.main:app", "--host", "127.0.0.1", "--port", str(port),
                             "--no-proxy-headers", "--log-level", "warning"], cwd=BACKEND, env=env)
    base = f"http://127.0.0.1:{port}"
    for _ in range(100):
        if proc.poll() is not None:
            raise SystemExit("E2E: server exited during startup")
        try:
            if httpx.get(base + "/api/health", timeout=1).status_code == 200:
                return proc, base, tmp
        except httpx.HTTPError:
            time.sleep(0.15)
    proc.terminate()
    raise SystemExit("E2E: server did not become healthy in time")


def scenario(base):
    c = httpx.Client(base_url=base, timeout=15)
    D = lambda r: r["data"]

    def mode(m):
        r = expect(c.post("/api/demo/dev/mode", json={"mode": m}), 200, f"switch demo to {m}")
        check(f"mode confirmed as {m}", r["mode"] == m)

    h = D(expect(c.get("/api/health"), 200, "health"))
    check("health payload", h["service"] == "tenantshield" and h["status"] == "ok")
    st = D(expect(c.get("/api/demo/status"), 200, "demo status"))
    check("demo reachable and vulnerable demo enabled", st["reachable"] and st["vulnerable_demo_enabled"])
    tenants = D(expect(c.get("/api/demo/tenants"), 200, "tenants"))
    check("two synthetic tenants", sorted(t["id"] for t in tenants) == ["tenant_abc", "tenant_xyz"])

    # error contract
    e = expect(c.get("/api/findings/987654321"), 404, "unknown finding")
    check("error payload shape", set(e["error"]) == {"status", "message"})
    expect(c.post("/api/demo/dev/mode", json={"mode": "bogus"}), 422, "invalid mode rejected")
    expect(c.post("/api/test-runs", headers={"Origin": "https://evil.example"}), 403, "cross-origin run blocked")

    # 1-3 vulnerable: run + confirm findings
    mode("vulnerable")
    run1 = D(expect(c.post("/api/test-runs"), 201, "run suite (vulnerable)"))
    d1 = D(expect(c.get(f"/api/test-runs/{run1['id']}"), 200, "run detail"))
    res = {r["test_case_key"]: r for r in d1["results"]}
    check("cross-tenant reads are findings", res["abc_reads_xyz"]["result_status"] == "finding"
          and res["xyz_reads_abc"]["result_status"] == "finding")
    check("same-tenant + list checks pass", all(res[k]["result_status"] == "passed" for k in ("abc_reads_own", "xyz_reads_own", "abc_list_scoped")))
    check("run counters consistent", d1["passed_count"] + d1["finding_count"] + d1["failed_count"] + d1["inconclusive_count"] == d1["total_tests"] == len(d1["results"]))
    fid = res["abc_reads_xyz"]["finding_id"]
    check("finding id returned by API", isinstance(fid, int))
    f0 = D(expect(c.get(f"/api/findings/{fid}"), 200, "finding detail"))
    ev = f0["original"]["evidence"]
    check("evidence is redacted and minimal", ev["request"]["headers"]["Authorization"] == "Bearer ********"
          and "demo-token" not in c.get(f"/api/findings/{fid}").text and ev["response"]["owner_tenant_id"] == "tenant_xyz")
    n0 = f0["occurrence_count"]

    # 4 save regression (reuse an existing one if running on a non-clean DB)
    if f0["regression"]:
        tid = f0["regression"]["id"]; print("[INFO] reusing existing regression test", tid)
    else:
        tid = D(expect(c.post(f"/api/findings/{fid}/regression-tests"), 201, "save regression test"))["id"]
    expect(c.post(f"/api/findings/{fid}/regression-tests"), 409, "duplicate save rejected")

    # 5-6 fixed: retest passes
    mode("fixed")
    rr = D(expect(c.post(f"/api/regression-tests/{tid}/runs"), 201, "retest in fixed mode"))
    check("retest passes after fix", rr["result_status"] == "passed" and rr["actual_status_code"] in (403, 404))

    # 7 history intact
    old = D(expect(c.get(f"/api/test-runs/{run1['id']}"), 200, "original run still readable"))
    check("original failed run unchanged", old["status"] == "findings")
    f1 = D(expect(c.get(f"/api/findings/{fid}"), 200, "finding after fix"))
    check("original evidence/time unchanged", f1["original"]["evidence"] == ev and f1["created_at"] == f0["created_at"])
    check("occurrence history preserved", f1["occurrence_count"] >= n0 >= 1)
    check("latest regression result is passed", f1["latest_regression_result"]["status"] == "passed")

    # 8 full suite in fixed mode
    run2 = D(expect(c.post("/api/test-runs"), 201, "run suite (fixed)"))
    d2 = D(expect(c.get(f"/api/test-runs/{run2['id']}"), 200, "fixed run detail"))
    check("all 5 checks pass in fixed mode", d2["status"] == "passed" and d2["passed_count"] == 5 and d2["finding_count"] == 0)

    # 9 reintroduce vulnerability
    mode("vulnerable")
    rr2 = D(expect(c.post(f"/api/regression-tests/{tid}/runs"), 201, "retest after reintroducing vulnerability"))
    check("regression test detects it again", rr2["result_status"] == "finding")
    f2 = D(expect(c.get(f"/api/findings/{fid}"), 200, "finding after reintroduction"))
    check("new occurrence appended, original untouched", f2["occurrence_count"] == f1["occurrence_count"] + 1
          and f2["latest_occurrence"]["source"] == "regression" and f2["original"]["evidence"] == ev)
    hist = D(expect(c.get(f"/api/regression-tests/{tid}"), 200, "regression history"))["runs"]
    check("history keeps both the pass and the later failure", [r["result_status"] for r in hist][:2] == ["finding", "passed"])
    mode("fixed")   # leave the demo in the safe state


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--base-url", help="use an already-running local server instead of starting a temp one")
    a = ap.parse_args()
    proc = tmp = None
    try:
        if a.base_url:
            base = a.base_url
        else:
            proc, base, tmp = start_server()
        scenario(base)
        print("ALL E2E STEPS PASSED")
    finally:
        if proc:
            proc.terminate()
            try:
                proc.wait(timeout=10)
            except subprocess.TimeoutExpired:
                proc.kill()
        if tmp:
            shutil.rmtree(tmp, ignore_errors=True)  # only the temp dir this script created
