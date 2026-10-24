"""D10c live routes: SSE stream, desk, inject, challenge, clock. Signatures copied from `contracts/stub_app.py`.

Non-negotiable 8: user input never produces a 500. Desk input errors are 422 `{"error":{"code","message"}}` with a
plain message; inject and challenge failures become recorded low-confidence escalations.
"""
from __future__ import annotations

import asyncio
import logging
from typing import Any, AsyncIterator

from fastapi import FastAPI, Request

from contracts import stub_app as stub
from contracts.models import (
    ChallengeRequest, ChallengeResponse, ClockRequest, ClockResponse, DeskRequest, Draft, InjectRequest,
    InjectResponse, Source, SourceKind, StormRun, TraceEvent,
)
from contracts.stub_app import ERRORS, ApiError, SSEResponse

from .desk import DeskError, run_desk
from .store import iso

log = logging.getLogger("stormcheck.server")


async def trace_stream(rt: Any, after: int, is_disconnected: Any = None, *, poll_s: float = 0.5,
                       stop_when_idle: bool = False) -> AsyncIterator[dict[str, str]]:
    """Every TraceEvent after `after` (Last-Event-ID), then new ones as they are written. `id` is the event seq."""
    cursor = after
    while True:
        if is_disconnected is not None and await is_disconnected():
            return
        batch = rt.store.trace(cursor, limit=200)
        for ev in batch:
            cursor = ev.seq
            yield {"event": "trace", "id": str(ev.seq), "data": ev.model_dump_json()}
        if not batch:
            if stop_when_idle:
                return
            await asyncio.sleep(poll_s)


def install(app: FastAPI, rt: Any) -> None:
    settings = rt.settings

    def sess(request: Request):
        return rt.signer.session_of(request.headers.get("authorization"), rt.now)

    # ---------------------------------------------------------------- SSE
    @app.get("/api/stream", response_model=TraceEvent, response_class=SSEResponse,
             responses={200: {"description": "text/event-stream; each `data:` line is one TraceEvent (JSON)"}},
             description="SSE: `event: trace`, `id: <seq>`, `data: TraceEvent` JSON. Send `Last-Event-ID` to resume. "
                         "Heartbeat: an SSE comment every 15 s.")
    async def stream(request: Request) -> SSEResponse:
        try:
            after = max(0, int(request.headers.get("last-event-id", "0") or 0))
        except ValueError:
            after = 0
        return SSEResponse(trace_stream(rt, after, request.is_disconnected, poll_s=settings.sse_poll_s),
                           ping=settings.heartbeat_s)

    # ---------------------------------------------------------------- desk
    @app.post("/api/desk", response_model=StormRun, responses=ERRORS)
    def desk(req: DeskRequest) -> StormRun:
        with rt.lock:
            try:
                return run_desk(rt, req.icao, req.date)
            except DeskError as exc:
                raise ApiError(422, exc.code, exc.message) from exc
            except ApiError:
                raise
            except Exception as exc:          # a judge's day must never 500
                log.exception("desk %s %s failed", req.icao, req.date)
                rt.live.failure("desk", exc, f"{req.icao}@{req.date.isoformat()}")
                raise ApiError(422, "upstream", f"That day could not be run ({type(exc).__name__}); try another "
                                                "airport or date.") from exc

    # ---------------------------------------------------------------- inject
    @app.post("/api/inject", response_model=InjectResponse, responses=ERRORS)
    def inject(req: InjectRequest) -> InjectResponse:
        with rt.lock:
            try:
                return rt.live.inject(req)
            except Exception as exc:          # belt and braces (non-negotiable 8)
                log.exception("inject failed")
                ref = f"SRC-INJ-FAILED-{len(rt.store.keys('injected_source')) + 1:04d}"
                rt.live.failure("inject", exc, ref)
                events: list[TraceEvent] = []
                rt.live.ops_question(ref, "Could not read an injected input", f"{type(exc).__name__}", events)
                text = (req.text or "")[:2000].encode("utf-8", "replace").decode("utf-8", "replace")
                src = Source(id=ref, kind=SourceKind.EMAIL, title="Injected input (unread)", text=text, sha256="0" * 64,
                             received_at=rt.now, trust_tier=4, acl_tags=["pii"])
                return InjectResponse(source=src, facts=[], dropped_unverifiable=0, events=events, affected=[],
                                      fallback_used=False, message=f"Could not read this input ({type(exc).__name__}) "
                                                                   "· routed to Ops as a low-confidence question")

    # ---------------------------------------------------------------- challenge
    @app.post("/api/flights/{flight_id}/challenge", response_model=ChallengeResponse, responses=ERRORS)
    def challenge(flight_id: str, req: ChallengeRequest, request: Request) -> ChallengeResponse:
        s = sess(request)
        if s.role.value.startswith("agent."):
            rt.deny(s.principal, "challenge", flight_id, "Least privilege: agents never challenge a decision")
            raise ApiError(403, "forbidden", "Agents never challenge a decision.")
        with rt.lock:
            try:
                return rt.live.challenge(flight_id, req.text)
            except KeyError as exc:
                raise ApiError(404, "not_found", f"No decision for {flight_id}.") from exc
            except Exception as exc:
                log.exception("challenge failed")
                rt.live.failure("challenge", exc, flight_id)
                events: list[TraceEvent] = []
                q = rt.live.ops_question(flight_id, f"Review a challenge to {flight_id.split('@')[0]}",
                                         req.text[:400], events, case_refs=[flight_id], reason_tag="sources-disagree")
                reply = Draft(id=f"DRAFT-CH-{flight_id}", kind="challenge_reply", numbers_verified=True,
                              template_fallback=True, text="Routed for review; the decision is unchanged.")
                return ChallengeResponse(classification="new_fact", decision_stands=True, reply=reply, cited=[],
                                         question=q)

    # ---------------------------------------------------------------- clock
    @app.post("/api/clock", response_model=ClockResponse, responses=ERRORS)
    def set_clock(req: ClockRequest, request: Request) -> ClockResponse:
        s = sess(request)
        with rt.lock:
            prev = rt.now
            try:
                t = rt.advance(req.known_at, s.principal)
            except ValueError as exc:
                raise ApiError(422, "validation", str(exc)) from exc
            if t > prev:
                rt.emit("info", s.principal, f"Clock moved to {iso(t)}", "INFO", "clock")
        return ClockResponse(known_at=rt.now)
