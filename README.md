# TENANTSHIELD

**Know when your tenant boundaries break. Prove when they are fixed.**

A local prototype that runs tenant-aware API checks against a bundled synthetic SaaS API, shows redacted evidence for any
cross-tenant exposure, saves the failing check as a regression test, and proves the fix by rerunning it.
**Test → Prove → Preserve → Verify.**

> A passing run means the *configured checks* passed. It is not a security audit and does not show the application is free
> of tenant-isolation bugs. This is an independent implementation, not affiliated with Kestra's similarly named
> "TenantShield" blueprint (check naming before any public release).

## Quick start

Requirements: Python 3.11+, Node 18+.

```bash
pip install -r backend/requirements.txt
cd frontend && npm install && npm run build && cd ..
python run.py                  # UI + API at http://127.0.0.1:8000
```

| Command | What it does |
|---|---|
| `python run.py` | backend on `127.0.0.1:8000` serving the built UI (`frontend/dist`) |
| `python run.py --dev` | backend + Vite hot-reload UI at `http://localhost:5173` |
| `python run.py --api-only` | backend only (`/docs` for the OpenAPI UI) |
| `python run.py --safe` | start **without** the vulnerable demo (API behaves as fixed) |
| `python run.py --port 8010` | other backend port (Vite is pointed at it) |

`run.py` starts children without a shell, in their own process groups, reports a child that dies, and shuts everything down on
Ctrl+C/SIGTERM. It exits with a clear message if `frontend/dist` is missing. Windows process-tree termination uses `taskkill`
and has not been exercised in this project's test runs.

Manual start (note the explicit opt-ins; without them the app runs in safe production mode):
```bash
cd backend
TENANTSHIELD_ENV=development TENANTSHIELD_ENABLE_VULNERABLE_DEMO=1 \
  python -m uvicorn app.main:app --host 127.0.0.1 --port 8000 --no-proxy-headers
cd frontend && npm run dev          # VITE_API_BASE_URL in frontend/.env.development
```

### Commands
```bash
cd backend && python -m pytest -q              # unit + API + security tests (isolated temp DB)
cd backend && python tests/e2e_demo.py         # full workflow; starts its own server + temp DB, then cleans up
cd backend && python tests/e2e_demo.py --base-url http://127.0.0.1:8000   # against a running local server (any DB state)
cd frontend && npm run build                   # tsc type-check + production build
```

## Safety model (read this)

| Control | Enforcement |
|---|---|
| Vulnerable path | exists only if `TENANTSHIELD_ENV=development` **and** `TENANTSHIELD_ENABLE_VULNERABLE_DEMO=1`; otherwise the demo API always behaves as *fixed*, even if internal state says otherwise. Default env is `production`. |
| Dev endpoints (`/api/demo/dev/*`, `/api/dev/reset-history`) | development env **and** loopback client address, else `403`. History reset also needs `{"confirm":"DELETE_HISTORY"}`. |
| Whole `/api/*` surface | loopback clients only (`403` otherwise). Optional `TENANTSHIELD_ALLOW_REMOTE_READS=1` permits remote **GET** only; writes stay local-only. |
| Origin header | **not authentication.** For state-changing requests, a foreign/`null` `Origin` is rejected as a CSRF defence; requests with no Origin (curl, scripts) pass only because the loopback check already applies. A `Host` allow-list blocks DNS rebinding. |
| Test target | the engine talks to the bundled demo app **in-process** (ASGI). There is no target URL/port. `TENANTSHIELD_DEMO_API_BASE_URL` is rejected at startup; `TENANTSHIELD_DEMO_TARGET` only accepts `inprocess`. Test definitions are validated by a strict schema (GET to `/api/demo/documents[/<id>]` only, consistent tenant/identity/marker) before every execution. |
| Evidence | bearer tokens are never stored; no raw bodies are stored; only status, IDs, owner tenant and boolean marker flags. Errors return generic messages (details only in the server log). Demo credentials are synthetic and clearly labelled demo-only. |
| Deleting a regression test | soft delete (`confirm=true` required). History and the finding are retained. |

**Limits that code cannot guarantee:** the app cannot make a network interface private. Isolation depends on binding
`127.0.0.1` (the default in `run.py`) and `--no-proxy-headers`. Behind a same-host reverse proxy every client appears local,
which would defeat the loopback check. **There is no authentication or per-user authorization**: this is a single-user local
tool, and exposing it on a network would require real authN/authZ first. Only one backend process is supported (the run lock
is in-process).

## How verdicts are decided
Deterministic assertions on status + resource id + owner tenant + unique content marker (`ABC-/XYZ-DEMO-MARKER`); the demo's
vulnerable/fixed label is never consulted.
- **finding**: foreign resource data confirmed (matching id+owner, a foreign owner on a 2xx, or the foreign marker anywhere in the
  response, even on a 403/404).
- **passed**: expected denial (403/404) with no foreign data; or valid same-tenant/scoped-list evidence.
- **failed**: unexpected behaviour with no leak confirmed (wrong status, own-resource mismatch, marker mismatch).
- **inconclusive**: timeout, connection error, 5xx, malformed/unparseable body on a 2xx, or missing ownership metadata. Never reported as secure.

## Findings, occurrences and history
`Finding` holds the **original** detection (evidence, first-run id and time are written once and never updated). Every later
detection (suite run or regression retest) appends a `FindingOccurrence`. The API returns `original`, `latest_occurrence`,
`occurrences`, `latest_regression_result` and `regression_history` separately. Regression runs are append-only; renaming keeps
history; deleting is soft. Schema upgrades are additive and idempotent (`migrations.py`, `PRAGMA user_version`) with an
occurrence backfill for older databases; nothing is dropped.

Runs always reach a final state: an exception mid-suite marks unexecuted checks `inconclusive` ("Not executed"), keeps earlier
results, records a generic `error_summary`, and closes clients. Runs left `running` by a crash are recovered at startup.

## API (TENANTSHIELD responses: `{"data": ...}`; errors: `{"error": {"status", "message"}}`)
| Method & path | Purpose |
|---|---|
| GET `/api/health`, `/api/demo/status`, `/api/demo/tenants` | health, demo status (incl. `vulnerable_demo_enabled`), tenants/documents |
| POST `/api/test-runs` (201; 409 if one is running), GET `/api/test-runs[/{id}]` | execute / list / detail |
| GET `/api/findings[/{id}]` | list / detail with original, latest occurrence, history |
| POST `/api/findings/{id}/regression-tests` (201; 409 duplicate; 422 bad name) | save regression test (`name` trimmed, 1–120 chars) |
| GET/PATCH `/api/regression-tests[/{id}]`, POST `/{id}/runs`, DELETE `/{id}?confirm=true` | manage, rerun, soft-delete |
| POST `/api/demo/dev/mode`, `/api/demo/dev/reset`, `/api/dev/reset-history` | **dev + loopback only** |
| Demo API: GET `/api/demo/health`, `/me`, `/documents`, `/documents/{id}` | system under test (denial = 404) |

## Repository map
`backend/app/` `config.py` (env + loopback), `errors.py`, `demo_api.py` (+ in-process `demo_app`), `engine.py` (verdicts, runs,
definitions), `routes.py`, `models.py`, `migrations.py`, `main.py` (guards). `backend/tests/` pytest + `e2e_demo.py`.
`frontend/src/` React pages. `DEMO_GUIDE.md` (judge script), `AUDIT_REPORT.md` (changes + results).

## Prior art
OWASP Multi-Tenant Security and Authorization Regression Testing cheat sheets, the OWASP API Security Testing Framework, and
Kestra's TenantShield RAG blueprint. No code or designs were copied.
