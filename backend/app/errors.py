"""Uniform, non-leaking error responses for every FastAPI app in this project."""
import logging

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException

log = logging.getLogger("tenantshield")


def error_body(status: int, message: str) -> dict:
    return {"error": {"status": status, "message": message}}


def install_error_handlers(app: FastAPI) -> None:
    @app.exception_handler(StarletteHTTPException)
    async def http_error(_: Request, exc: StarletteHTTPException):
        return JSONResponse(error_body(exc.status_code, str(exc.detail)), status_code=exc.status_code)

    @app.exception_handler(RequestValidationError)
    async def validation_error(_: Request, exc: RequestValidationError):
        # Only field location + rule text; never echo submitted values.
        msg = "; ".join(f"{'.'.join(str(p) for p in e['loc'] if p != 'body')}: {e['msg']}" for e in exc.errors())
        return JSONResponse(error_body(422, f"Invalid request: {msg}"), status_code=422)

    @app.exception_handler(Exception)
    async def unhandled(request: Request, exc: Exception):
        # Details go to the server log only. The client gets nothing about paths, stack frames or secrets.
        log.error("Unhandled error on %s %s", request.method, request.url.path, exc_info=exc)
        return JSONResponse(error_body(500, "Internal server error"), status_code=500)
