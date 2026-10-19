import logging
from contextlib import asynccontextmanager
from pathlib import Path
from urllib.parse import urlparse

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles
from starlette.middleware.trustedhost import TrustedHostMiddleware

from . import config, demo_api, engine, routes
from .db import SessionLocal, init_db
from .errors import error_body, install_error_handlers

log = logging.getLogger("tenantshield")
SAFE_METHODS = {"GET", "HEAD", "OPTIONS"}


@asynccontextmanager
async def lifespan(_: FastAPI):
    config.validate_target_config()  # refuse to start with an unsupported target configuration
    init_db()
    with SessionLocal() as db:
        n = engine.recover_interrupted_runs(db)
        if n:
            log.warning("Recovered %d interrupted run(s) left in 'running' state", n)
    if config.vulnerable_demo_enabled():
        log.warning("VULNERABLE DEMO ENABLED (development only). Keep this server on loopback.")
    yield


app = FastAPI(title="TENANTSHIELD", version="1.1.0", lifespan=lifespan,
              description="Tenant-boundary verification and regression testing (local prototype).")
install_error_handlers(app)


@app.middleware("http")
async def request_guard(request: Request, call_next):
    """Defence in depth for the control API (innermost middleware).

    1. Client address must be loopback (real boundary; independent of any header). Optional read-only remote GETs.
    2. State-changing requests carrying an Origin header must come from an allowed origin (CSRF defence only;
       Origin is client-supplied and is NOT treated as authentication). Requests without Origin (curl, scripts)
       are allowed only because rule 1 already restricted them to local clients.
    """
    if request.url.path.startswith("/api/"):
        local = request.client is not None and config.is_loopback(request.client.host)
        safe = request.method in SAFE_METHODS
        if not local and not (safe and config.allow_remote_reads()):
            return JSONResponse(error_body(403, "This service only accepts requests from the local machine"), status_code=403)
        if not safe:
            origin = request.headers.get("origin")
            if origin is not None and origin not in config.cors_origins() \
                    and urlparse(origin).netloc != request.headers.get("host"):
                return JSONResponse(error_body(403, "Cross-origin request blocked"), status_code=403)
    return await call_next(request)


app.add_middleware(CORSMiddleware, allow_origins=config.cors_origins(), allow_methods=["*"], allow_headers=["*"])
app.add_middleware(TrustedHostMiddleware, allowed_hosts=config.allowed_hosts())  # outermost: DNS-rebinding guard

app.include_router(demo_api.router)
app.include_router(routes.router)

_dist = Path(__file__).resolve().parents[2] / "frontend" / "dist"
if _dist.is_dir():  # single-process mode: serve the built UI at /
    app.mount("/", StaticFiles(directory=_dist, html=True), name="ui")
