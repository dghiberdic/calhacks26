"""StormCheck real API server. Run: `uv run uvicorn server.app:app --port 8000` (or `make dev`).

Same routes and `response_model`s as `contracts/stub_app.py` (an OpenAPI-superset test keeps it so). Routes this
server implements on the real pipeline are registered first; every other contract route falls back to the stub's
handler. `web/dist` is served at `/` when it exists. See server/DECISIONS.md.
"""
from __future__ import annotations

import logging
from pathlib import Path
from typing import Any

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse
from fastapi.routing import APIRoute
from starlette.exceptions import HTTPException as StarletteHTTPException

from contracts import stub_app as stub
from contracts.models import FlightFile, Health, OkResponse, StormRun, StormSummary
from contracts.stub_app import ERRORS, ApiError, envelope

from . import routes
from .config import Settings
from .runtime import Runtime

log = logging.getLogger("stormcheck.server")


def _validation_message(exc: RequestValidationError) -> str:
    errs = exc.errors()
    if not errs:
        return "The request could not be read."
    loc = ".".join(str(x) for x in errs[0].get("loc", ()) if x not in ("body", "query", "path"))
    msg = errs[0].get("msg", "invalid value")
    return f"{loc}: {msg}" if loc else msg


def install_errors(app: FastAPI) -> None:
    @app.exception_handler(ApiError)
    async def _api_error(_: Request, exc: ApiError) -> JSONResponse:
        return envelope(exc.status, exc.code, exc.message)

    @app.exception_handler(RequestValidationError)
    async def _validation_error(_: Request, exc: RequestValidationError) -> JSONResponse:
        return envelope(422, "validation", _validation_message(exc))

    @app.exception_handler(StarletteHTTPException)
    async def _http_error(_: Request, exc: StarletteHTTPException) -> JSONResponse:
        code = {404: "not_found", 401: "forbidden", 403: "forbidden"}.get(exc.status_code, "validation")
        return envelope(exc.status_code, code, str(exc.detail))


def add_stub_fallbacks(app: FastAPI) -> list[str]:
    """Append the stub's route for every contract (path, method) this app does not implement yet."""
    taken = {(r.path, m) for r in app.router.routes if isinstance(r, APIRoute) for m in r.methods}
    added = []
    for r in stub.app.router.routes:
        if isinstance(r, APIRoute) and not any((r.path, m) in taken for m in r.methods):
            app.router.routes.append(r)
            added.extend(f"{m} {r.path}" for m in sorted(r.methods))
    return added


def install_web(app: FastAPI, dist: Path) -> bool:
    index = dist / "index.html"
    if not index.exists():
        return False
    root = dist.resolve()

    @app.get("/{path:path}", include_in_schema=False)
    def web(path: str) -> Any:
        if path.startswith("api/") or path == "api":
            raise ApiError(404, "not_found", f"No API route /{path}.")
        target = (root / path).resolve()
        if path and target.is_file() and root in target.parents:
            return FileResponse(target)
        return FileResponse(index)   # SPA: client-side routes get index.html

    return True


def create_app(settings: Settings | None = None) -> FastAPI:
    settings = settings or Settings.from_env()
    rt = Runtime(settings)
    rt.boot()

    app = FastAPI(title="StormCheck API", version="2.0.0",
                  description="StormCheck real server (CONTRACTS.md §3). Routes not yet on the real pipeline fall "
                              "back to the contract stub.")
    app.state.runtime = rt
    app.state.settings = settings
    app.add_middleware(CORSMiddleware, allow_origins=["http://localhost:5173", "http://127.0.0.1:5173"],
                       allow_credentials=True, allow_methods=["*"], allow_headers=["*"], expose_headers=["*"])
    install_errors(app)

    # ============================================================ reads on the real pipeline
    @app.get("/api/health", response_model=Health)
    def health() -> Health:
        return Health(ok=True, mode=settings.mode, impl=rt.health_impl())

    @app.get("/api/storms", response_model=list[StormSummary])
    def list_storms() -> list[StormSummary]:
        return rt.storm_summaries()

    @app.get("/api/storms/{storm_id}", response_model=StormRun, responses=ERRORS)
    def get_storm(storm_id: str) -> StormRun:
        run = rt.storm_run(storm_id)
        if run is None:
            known = ", ".join(s.id for s in rt.storm_summaries()) or "none yet"
            raise ApiError(404, "not_found", f"No storm run {storm_id}. Known: {known}.")
        return run

    @app.get("/api/flights/{flight_id}", response_model=FlightFile, responses=ERRORS)
    def get_flight(flight_id: str) -> FlightFile:
        ff = rt.flight_file(flight_id)
        if ff is not None:
            return ff
        if rt.known_flight(flight_id):
            raise ApiError(404, "not_found", f"{flight_id} operated normally, so there is no decision to show.")
        raise ApiError(404, "not_found", f"No flight {flight_id}. IDs look like NS31@2025-01-24.")

    # ============================================================ writes on the real pipeline
    @app.post("/api/reset", response_model=OkResponse)
    def reset() -> OkResponse:
        rt.reset()
        stub.reset()   # the stub fallbacks keep in-memory state too
        return OkResponse(ok=True)

    routes.install(app, rt)                       # D10b: the rest of the API on the real pipeline
    app.state.stub_routes = add_stub_fallbacks(app)
    app.state.web = install_web(app, settings.web_dist)
    _fix_openapi(app)
    return app


def _fix_openapi(app: FastAPI) -> None:
    """Same SSE content-type fix as the stub, so the OpenAPI stays a superset of contracts/openapi.json."""
    base = app.openapi

    def _openapi() -> dict[str, Any]:
        if app.openapi_schema is None:
            schema = base()
            ok = schema.get("paths", {}).get("/api/stream", {}).get("get", {}).get("responses", {}).get("200")
            if ok is not None:
                ok["content"] = {"text/event-stream": {"schema": {"$ref": "#/components/schemas/TraceEvent"}}}
        return app.openapi_schema

    app.openapi = _openapi  # type: ignore[method-assign]


app = create_app()
