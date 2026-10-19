# TENANTSHIELD audit report

All results below were observed by running the commands in this environment (Linux, Python 3.12, Node/npm available).

## Results
| Command | Result |
|---|---|
| `cd backend && python -m pytest -q` | **88 passed** (test_engine 47, test_security 30, test_workflow 11) |
| `cd frontend && npm run build` (tsc + Vite) | **clean**, 1510 modules |
| `cd backend && python tests/e2e_demo.py` (own server + temp DB) | **45/45 checks, ALL E2E STEPS PASSED**; `backend/data/` not created |
| `python tests/e2e_demo.py --base-url ...` run twice on one live server | both passed (second run on a non-empty DB) |
| Real browser (Playwright) through the Vite origin `localhost:5173` | run, save regression, switch mode, retest all worked from the UI |
| Launcher: `--dev` and default, SIGINT and SIGTERM | exit 0, ports closed, **0 surviving child processes** |
| Mutation spot-check (4 deliberate breakages: loopback guard, vulnerable flag, run finalization, occurrence logging) | each caught by a test |

Not run: no linter is configured in the project (none added); Windows launcher path (`taskkill`) untested; mobile layout
was not re-reviewed this round; Google Fonts cannot load in the sandbox (UI falls back to system fonts).

## Defects found and fixed
1. **Dev controls gated only by `ENV`** and default env was development-like → now default `production`; vulnerable path needs
   `ENV=development` **and** `TENANTSHIELD_ENABLE_VULNERABLE_DEMO=1`; otherwise the demo always behaves as fixed.
2. **Dev/destructive endpoints reachable by any client** → loopback-only dependency; whole `/api/*` loopback-only; Origin check
   kept purely as CSRF defence (not auth); no-Origin requests handled; Host allow-list added.
3. **Engine target = env URL checked by hostname only** → in-process ASGI client bound to a demo-only app; URL variable
   rejected at startup; `TENANTSHIELD_DEMO_TARGET` accepts only `inprocess`; strict schema for test definitions.
4. **`evaluate()` relied on id+owner only** → also uses unique markers (searched in raw text, never stored); distinguishes
   finding / passed / failed / inconclusive for malformed JSON, missing owner metadata, altered ids, 3xx/401, 5xx, timeouts.
5. **Finding reuse lost history** → append-only `finding_occurrences`; original evidence/time immutable; API returns
   `original`, `latest_occurrence`, `latest_regression_result`, `regression_history`.
6. **Runs could stay `running`** → `finally` finalization, honest "Not executed" inconclusive rows, `error_summary`, counters derived
   from rows, startup recovery, in-process lock released on error.
7. **Regression test deletion cascaded away history** → soft delete (`confirm=true`); rename keeps history; names trimmed, 1–120 chars.
8. **Stored definitions executed unvalidated** → re-validated before every run (`422`, nothing executed).
9. **e2e assumed clean DB / run id 1** → self-contained temp server, IDs from responses, status/payload assertions, works on non-clean DB.
10. **Launcher** → no `shell=True`, loopback bind, `--no-proxy-headers`, child-failure detection, clear missing-build message.
    *Found during verification:* Vite grandchildren survived shutdown (port 5173 stayed bound) → fixed with per-child process groups.
11. **Error handling** → one handler set for both apps; generic 500s, validation errors never echo input.

## Tests added (all new files; the old suite was replaced)
Workflow/history (11): both modes, detection, fixed denial, redacted/minimal evidence, full lifecycle with reintroduction,
immutable original + occurrences, rename/soft-delete retention, name validation, header-trust, error shape, resets.
Security (30): production/default-env gating, explicit opt-in, remote clients (read/write), Origin ≠ auth, optional remote reads,
loopback parsing incl. IPv6, Origin matrix (none/allowed/evil/`null`), Host header, invalid target config (6 values + legacy var),
startup refusal, approved target reaches only the demo app, 15 invalid definitions, corrupted stored definition never executes,
500 leak check. Engine (47): 39-row verdict matrix, no-body evidence, timeout/connection/5xx/malformed, unavailable target,
verdict ignores demo label, exception mid-suite (state, counters, secrets, client closed, lock released), persistence failure,
overlap 409, stuck-run recovery, legacy-DB migration (idempotent, no loss).

## Remaining limitations
- **No authentication/authorization.** Single-user local tool. Network exposure needs real authN/authZ first. Isolation relies on
  binding `127.0.0.1`; a same-host reverse proxy makes all clients look local.
- Single backend process only (run lock is in-process). SQLite only (migrations are additive/idempotent, not Alembic).
- Findings dedupe per test case, so a recurrence is an occurrence, not a new finding (by design).
- Five synthetic cases prove the workflow, not accuracy on real applications.
- Starlette emits a deprecation warning about `httpx` in `TestClient` (harmless).

## Files needing manual work
None required. Optional: a CI workflow, a Windows run of `run.py --dev`, and authentication if ever deployed beyond localhost.
