#!/usr/bin/env python3
"""Single launcher (no shell, loopback only).

  python run.py                 backend on 127.0.0.1:8000 serving the built UI (frontend/dist)
  python run.py --dev           backend + Vite hot-reload UI (http://localhost:5173)
  python run.py --api-only      backend only
  python run.py --safe          do NOT enable the vulnerable demo (API behaves as fixed; toggle disabled)
  python run.py --port 8010     different backend port (Vite is pointed at it automatically)

The launcher sets TENANTSHIELD_ENV=development and TENANTSHIELD_ENABLE_VULNERABLE_DEMO=1 for the child
processes ONLY (explicit, local demo). Never expose this server to a network.
"""
import argparse
import os
import shutil
import signal
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent
BACKEND, FRONTEND = ROOT / "backend", ROOT / "frontend"


POSIX = os.name == "posix"


def spawn(cmd: list[str], **kw) -> subprocess.Popen:
    """Start a child in its OWN process group so the whole tree (npm -> node -> esbuild) can be stopped."""
    if POSIX:
        return subprocess.Popen(cmd, start_new_session=True, **kw)
    return subprocess.Popen(cmd, creationflags=subprocess.CREATE_NEW_PROCESS_GROUP, **kw)


def _signal_tree(p: subprocess.Popen, force: bool) -> None:
    try:
        if POSIX:
            os.killpg(p.pid, signal.SIGKILL if force else signal.SIGTERM)
        elif force or p.poll() is None:
            subprocess.run(["taskkill", "/PID", str(p.pid), "/T", "/F"], capture_output=True)
    except (ProcessLookupError, PermissionError):
        pass


def stop(procs: list[subprocess.Popen]) -> None:
    for p in procs:
        _signal_tree(p, force=False)
    deadline = time.time() + 8
    for p in procs:
        try:
            p.wait(timeout=max(0.1, deadline - time.time()))
        except subprocess.TimeoutExpired:
            pass
    for p in procs:           # sweep: anything left in the group (e.g. a stray esbuild) is killed
        _signal_tree(p, force=True)
        p.wait()


def fail(msg: str, code: int = 2):
    print(f"ERROR: {msg}", file=sys.stderr)
    sys.exit(code)


def main() -> int:
    ap = argparse.ArgumentParser(description="Launch TENANTSHIELD locally.")
    ap.add_argument("--dev", action="store_true", help="also run the Vite dev server")
    ap.add_argument("--api-only", action="store_true", help="run only the backend")
    ap.add_argument("--safe", action="store_true", help="do not enable the vulnerable demo")
    ap.add_argument("--port", type=int, default=8000, help="backend port (default 8000)")
    a = ap.parse_args()
    if a.dev and a.api_only:
        fail("--dev and --api-only are mutually exclusive")

    npm = None
    if a.dev:
        npm = shutil.which("npm")
        if not npm:
            fail("npm was not found on PATH. Install Node 18+ (https://nodejs.org) or run without --dev.")
        if not (FRONTEND / "node_modules").is_dir():
            fail("frontend/node_modules is missing. Run: cd frontend && npm install")
    elif not a.api_only and not (FRONTEND / "dist" / "index.html").is_file():
        fail("frontend/dist not found, so there is no UI to serve.\n"
             "  Build it:  cd frontend && npm install && npm run build\n"
             "  or run:    python run.py --dev      (hot-reload UI)\n"
             "  or run:    python run.py --api-only (API + /docs only)")

    env = {**os.environ, "TENANTSHIELD_ENV": "development"}
    env.pop("TENANTSHIELD_DEMO_API_BASE_URL", None)   # unsupported; the engine tests the bundled demo in-process
    if a.safe:
        env.pop("TENANTSHIELD_ENABLE_VULNERABLE_DEMO", None)
    else:
        env["TENANTSHIELD_ENABLE_VULNERABLE_DEMO"] = "1"

    procs: list[subprocess.Popen] = []
    names: dict[int, str] = {}
    try:
        backend = spawn(
            [sys.executable, "-m", "uvicorn", "app.main:app", "--host", "127.0.0.1", "--port", str(a.port),
             "--no-proxy-headers"], cwd=BACKEND, env=env)
        procs.append(backend); names[backend.pid] = "backend"
        if a.dev:
            venv = {**env, "VITE_API_BASE_URL": f"http://127.0.0.1:{a.port}"}
            ui = spawn([npm, "run", "dev"], cwd=FRONTEND, env=venv)
            procs.append(ui); names[ui.pid] = "frontend"
        url = "http://localhost:5173" if a.dev else f"http://127.0.0.1:{a.port}"
        print(f"TENANTSHIELD running at {url}  (loopback only; Ctrl+C to stop)")
        print("Vulnerable demo:", "DISABLED (--safe)" if a.safe else "enabled for this local demo session")

        while True:
            for p in procs:
                code = p.poll()
                if code is not None:
                    print(f"ERROR: the {names[p.pid]} process exited unexpectedly (code {code}). Stopping the rest.",
                          file=sys.stderr)
                    stop(procs)
                    return code or 1
            time.sleep(0.5)
    except KeyboardInterrupt:
        print("\nStopping…")
        stop(procs)
        return 0
    finally:
        stop(procs)


def _interrupt(*_):
    raise KeyboardInterrupt


if __name__ == "__main__":
    # Explicit handlers: Ctrl+C / SIGTERM always trigger an orderly shutdown of both child processes,
    # even if this process inherited an ignored SIGINT (e.g. started as a background job).
    signal.signal(signal.SIGINT, _interrupt)
    signal.signal(signal.SIGTERM, _interrupt)
    sys.exit(main())
