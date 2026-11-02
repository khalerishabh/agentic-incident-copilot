import logging
import os
import time
import uuid

import httpx
from fastapi import APIRouter, FastAPI, Header, HTTPException, Request
from fastapi.responses import JSONResponse, PlainTextResponse
from prometheus_client import CONTENT_TYPE_LATEST, generate_latest

from .chaos import SUPPORTED_FAULTS, InjectedFailure, chaos
from .logging_setup import setup_logging
from .metrics import LATENCY, REQUESTS, UPSTREAM_ERRORS

SILENT_PREFIXES = ("/metrics", "/chaos", "/healthz")


def create_app(service: str, router: APIRouter) -> FastAPI:
    log = setup_logging(service)
    app = FastAPI(title=service)
    app.state.http = httpx.AsyncClient(timeout=2.0)

    @app.middleware("http")
    async def instrument(request: Request, call_next):
        path = request.url.path
        if path.startswith(SILENT_PREFIXES):
            return await call_next(request)

        request_id = request.headers.get("x-request-id", uuid.uuid4().hex[:16])
        request.state.request_id = request_id
        route = path
        start = time.perf_counter()
        status = 500
        try:
            await chaos.before_request()
            response = await call_next(request)
            status = response.status_code
            route_obj = request.scope.get("route")
            route = getattr(route_obj, "path", path)
            return response
        except InjectedFailure as exc:
            status = exc.status
            log.error(exc.message, extra={"request_id": request_id, "route": route})
            return JSONResponse({"detail": exc.message}, status_code=status)
        except Exception as exc:
            log.exception("unhandled error", extra={"request_id": request_id, "error": str(exc)})
            return JSONResponse({"detail": "internal error"}, status_code=500)
        finally:
            elapsed = time.perf_counter() - start
            REQUESTS.labels(service, route, request.method, str(status)).inc()
            LATENCY.labels(service, route).observe(elapsed)
            level = logging.WARNING if status >= 500 or elapsed > 1.0 else logging.INFO
            log.log(
                level,
                "request handled",
                extra={
                    "request_id": request_id,
                    "route": route,
                    "method": request.method,
                    "status": status,
                    "duration_ms": round(elapsed * 1000, 1),
                },
            )

    @app.get("/healthz")
    async def healthz():
        return {"service": service, "ok": True}

    @app.get("/metrics")
    async def metrics():
        return PlainTextResponse(generate_latest(), media_type=CONTENT_TYPE_LATEST)

    admin_token = os.getenv("CHAOS_ADMIN_TOKEN", "change-me")

    def _check(token: str | None):
        if token != admin_token:
            raise HTTPException(403, "bad chaos token")

    @app.get("/chaos")
    async def chaos_list(x_chaos_token: str | None = Header(default=None)):
        _check(x_chaos_token)
        return {"active": chaos.active, "supported": SUPPORTED_FAULTS}

    @app.post("/chaos/{fault}")
    async def chaos_enable(fault: str, params: dict | None = None,
                           x_chaos_token: str | None = Header(default=None)):
        _check(x_chaos_token)
        try:
            return {"enabled": fault, "params": chaos.enable(fault, params)}
        except KeyError:
            raise HTTPException(404, f"unknown fault {fault}")

    @app.delete("/chaos/{fault}")
    async def chaos_disable(fault: str, x_chaos_token: str | None = Header(default=None)):
        _check(x_chaos_token)
        chaos.disable(fault)
        return {"disabled": fault}

    app.include_router(router)
    return app


async def call_upstream(request: Request, method: str, url: str, upstream: str,
                        service: str, **kwargs) -> httpx.Response:
    log = logging.getLogger(service)
    headers = {"x-request-id": getattr(request.state, "request_id", "")}
    try:
        resp = await request.app.state.http.request(method, url, headers=headers, **kwargs)
        if resp.status_code >= 500:
            UPSTREAM_ERRORS.labels(service, upstream).inc()
            log.error(f"{upstream} returned {resp.status_code}",
                      extra={"upstream": upstream, "status": resp.status_code,
                             "request_id": headers["x-request-id"]})
        return resp
    except httpx.HTTPError as exc:
        UPSTREAM_ERRORS.labels(service, upstream).inc()
        log.error(f"call to {upstream} failed",
                  extra={"upstream": upstream, "error": type(exc).__name__,
                         "request_id": headers["x-request-id"]})
        raise HTTPException(502, f"{upstream} unavailable")
