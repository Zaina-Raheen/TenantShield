"""Test isolation: every test run uses a throw-away SQLite file in a fresh temp dir that is removed afterwards.
Nothing here can touch backend/data/ or any user database."""
import atexit
import os
import shutil
import tempfile

_TMP = tempfile.mkdtemp(prefix="tenantshield-test-")
atexit.register(lambda: shutil.rmtree(_TMP, ignore_errors=True))
os.environ["TENANTSHIELD_DATABASE_URL"] = f"sqlite:///{_TMP}/test.db"
os.environ["TENANTSHIELD_ENV"] = "development"
os.environ["TENANTSHIELD_ENABLE_VULNERABLE_DEMO"] = "1"
for _v in ("TENANTSHIELD_DEMO_API_BASE_URL", "TENANTSHIELD_DEMO_TARGET", "TENANTSHIELD_ALLOW_REMOTE_READS"):
    os.environ.pop(_v, None)

import asyncio  # noqa: E402

import httpx  # noqa: E402
import pytest  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

from app import engine  # noqa: E402
from app.db import Base, engine as db_engine  # noqa: E402
from app.demo_api import demo_app, state  # noqa: E402
from app.main import app  # noqa: E402
from app.migrations import migrate  # noqa: E402

assert str(db_engine.url).startswith(f"sqlite:///{_TMP}"), "tests must only ever use the temp database"

ALICE = {"Authorization": "Bearer demo-token-alice-abc"}
BOB = {"Authorization": "Bearer demo-token-bob-xyz"}
LOCAL = ("127.0.0.1", 50000)
REMOTE = ("203.0.113.9", 50000)


@pytest.fixture()
def client():
    Base.metadata.drop_all(db_engine)
    migrate(db_engine)
    state.mode = "vulnerable"
    state.reset_documents()
    with TestClient(app, client=LOCAL, raise_server_exceptions=False) as c:
        yield c


@pytest.fixture()
def db():
    from app.db import SessionLocal
    with SessionLocal() as s:
        yield s


def set_mode(client, mode):
    r = client.post("/api/demo/dev/mode", json={"mode": mode})
    assert r.status_code == 200, r.text
    assert r.json()["mode"] == mode


def run_suite(client):
    r = client.post("/api/test-runs")
    assert r.status_code == 201, r.text
    run = client.get(f"/api/test-runs/{r.json()['data']['id']}")
    assert run.status_code == 200
    return run.json()["data"]


def by_key(run):
    return {x["test_case_key"]: x for x in run["results"]}


def mock_client(handler):
    return httpx.AsyncClient(transport=httpx.MockTransport(handler), base_url="http://demo.internal")


class TrackedClient(httpx.AsyncClient):
    closed = False

    async def aclose(self):
        TrackedClient.closed = True
        await super().aclose()


def tracked_demo_client():
    TrackedClient.closed = False
    transport = httpx.ASGITransport(app=demo_app, raise_app_exceptions=False, client=LOCAL)
    return TrackedClient(transport=transport, base_url="http://demo.internal")


def arun(coro):
    return asyncio.run(coro)
