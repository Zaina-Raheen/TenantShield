"""Bundled synthetic college-management SaaS API (the system under test).

DEMO-ONLY: all data and credentials are synthetic. The vulnerable path exists only when
TENANTSHIELD_ENV=development AND TENANTSHIELD_ENABLE_VULNERABLE_DEMO=1; the toggle/reset endpoints
additionally accept only loopback clients. Outside that, the API always behaves as "fixed".
Tenant identity is derived from the validated bearer token; client-supplied tenant headers are ignored.
"""
import copy
import threading
from typing import Literal

from fastapi import APIRouter, Depends, FastAPI, Header, HTTPException, Request
from pydantic import BaseModel

from . import config
from .errors import install_error_handlers

DEMO_TENANTS = {
    "tenant_abc": {"id": "tenant_abc", "name": "ABC Engineering College", "marker": "ABC-DEMO-MARKER"},
    "tenant_xyz": {"id": "tenant_xyz", "name": "XYZ Engineering College", "marker": "XYZ-DEMO-MARKER"},
}

# DEMO-ONLY synthetic credentials. They protect nothing real and are the only tokens the demo API accepts.
DEMO_USERS = {
    "alice_abc": {"user_id": "alice_abc", "display_name": "Alice", "tenant_id": "tenant_abc", "token": "demo-token-alice-abc"},
    "bob_xyz": {"user_id": "bob_xyz", "display_name": "Bob", "tenant_id": "tenant_xyz", "token": "demo-token-bob-xyz"},
}
_TOKEN_INDEX = {u["token"]: u for u in DEMO_USERS.values()}

SEED_DOCUMENTS = [
    {"id": "doc_abc_001", "owner_tenant_id": "tenant_abc", "title": "Semester 5 marksheet (synthetic student A)",
     "content": "ABC-DEMO-MARKER | Synthetic marksheet. All data fictional."},
    {"id": "doc_xyz_001", "owner_tenant_id": "tenant_xyz", "title": "Semester 5 marksheet (synthetic student B)",
     "content": "XYZ-DEMO-MARKER | Synthetic marksheet. All data fictional."},
]


class _State:
    def __init__(self) -> None:
        self.lock = threading.Lock()
        self.mode: str = "vulnerable"
        self.documents: dict[str, dict] = {}
        self.reset_documents()

    def reset_documents(self) -> None:
        with self.lock:
            self.documents = {d["id"]: copy.deepcopy(d) for d in SEED_DOCUMENTS}


state = _State()


def effective_mode() -> str:
    """The vulnerable path is unreachable unless explicitly enabled for the local demo."""
    return state.mode if config.vulnerable_demo_enabled() else "fixed"

router = APIRouter(prefix="/api/demo", tags=["demo-saas-api"])


def current_user(authorization: str | None = Header(default=None)) -> dict:
    # NOTE: X-Tenant-ID or similar headers are deliberately never read.
    if not authorization or not authorization.lower().startswith("bearer "):
        raise HTTPException(401, "Authentication required")
    user = _TOKEN_INDEX.get(authorization[7:].strip())
    if not user:
        raise HTTPException(401, "Invalid credentials")
    return user


def require_local_dev(request: Request) -> None:
    """Dev-only endpoints: development environment AND a loopback client.

    The Origin header is NOT authentication; the client address is checked here, and the Origin guard in
    main.py is only a CSRF defence. Limitation: behind a same-host reverse proxy every client looks local.
    """
    if not config.dev_controls_enabled():
        raise HTTPException(403, "Development controls are disabled outside the development environment")
    if request.client is None or not config.is_loopback(request.client.host):
        raise HTTPException(403, "Development controls are restricted to local clients")


@router.get("/health")
def health():
    return {"status": "ok", "mode": effective_mode(), "environment": config.environment(),
            "vulnerable_demo_enabled": config.vulnerable_demo_enabled()}


@router.get("/me")
def me(user: dict = Depends(current_user)):
    t = DEMO_TENANTS[user["tenant_id"]]
    return {"user_id": user["user_id"], "display_name": user["display_name"],
            "tenant_id": t["id"], "tenant_name": t["name"]}


@router.get("/documents")
def list_documents(user: dict = Depends(current_user)):
    docs = [d for d in state.documents.values() if d["owner_tenant_id"] == user["tenant_id"]]
    return {"items": [{"id": d["id"], "owner_tenant_id": d["owner_tenant_id"], "title": d["title"]} for d in docs]}


@router.get("/documents/{document_id}")
def get_document(document_id: str, user: dict = Depends(current_user)):
    doc = state.documents.get(document_id)
    if doc is None:
        raise HTTPException(404, "Document not found")
    if effective_mode() == "fixed" and doc["owner_tenant_id"] != user["tenant_id"]:
        # Documented denial behaviour: 404, indistinguishable from "does not exist".
        raise HTTPException(404, "Document not found")
    # In "vulnerable" mode the ownership check above is deliberately skipped.
    return doc


class ModeBody(BaseModel):
    mode: Literal["vulnerable", "fixed"]


@router.post("/dev/mode", dependencies=[Depends(require_local_dev)])
def set_mode(body: ModeBody):
    if body.mode == "vulnerable" and not config.vulnerable_demo_enabled():
        raise HTTPException(403, "The vulnerable demo is not enabled. Set TENANTSHIELD_ENABLE_VULNERABLE_DEMO=1 "
                                 "(development environment only).")
    state.mode = body.mode
    return {"mode": effective_mode()}


@router.post("/dev/reset", dependencies=[Depends(require_local_dev)])
def reset_demo():
    state.reset_documents()
    return {"status": "reset", "documents": len(state.documents), "mode": effective_mode()}


# Separate app object containing ONLY the demo routes. The test engine talks to this app in-process via an
# ASGI transport, so it can physically reach nothing else (no sockets, no configurable target URL).
demo_app = FastAPI(title="Bundled demo SaaS API (internal)", docs_url=None, redoc_url=None, openapi_url=None)
demo_app.include_router(router)
install_error_handlers(demo_app)
