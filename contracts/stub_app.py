"""StormCheck contract stub (D0a): every CONTRACTS.md §3 route under /api, each with response_model.

Serves the hand-written fixtures in contracts/fixtures/api/ (built by scripts/build_stub_fixtures.py).
Run: make stub  (uvicorn contracts.stub_app:app --port 8001 --reload)

Stub behaviour worth knowing (see contracts/DECISIONS.md):
- In-memory state: answers, confirmed rules, approvals, locks and the clock live until POST /api/reset or a restart.
- Auth: POST /api/session returns an HMAC-signed token; send `Authorization: Bearer <token>`. No or bad token = judge.
- GET /api/stream replays trace.json every STUB_SSE_INTERVAL seconds (default 2) with `id: <seq>`, honours
  Last-Event-ID, then keeps looping with fresh seqs (STUB_SSE_LOOP=0 stops after one pass). Heartbeat is an SSE
  comment every 15 s. Events created by POSTs (answer, inject, ...) are streamed too.
"""
from __future__ import annotations

import asyncio
import base64
import hashlib
import hmac
import json
import os
import re
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Any, AsyncIterator

import airportsdata
from fastapi import FastAPI, Query, Request
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from pydantic import TypeAdapter
from sse_starlette.sse import EventSourceResponse
from starlette.exceptions import HTTPException as StarletteHTTPException

from contracts.models import (
    AccessDecision, AccessMatrix, Airport, AnswerRequest, AnswerResponse, Blame, CfoMetrics, ChallengeRequest,
    ChallengeResponse, ClaimCurve, ClockRequest, ClockResponse, Commit, Confidence, ConfirmResponse, ControlMapping,
    DeskRequest, Draft, EffortEstimate, ErrorBody, ErrorEnvelope, EstimateCard, EvalReport, Fact, FlightFile, Health,
    InjectRequest, InjectResponse, Injection, InvariantResult, JournalEntry, LearningStep, LockResponse,
    MonthEndResponse,
    OkResponse, PeriodRequest, Question, RejectRequest, ReplayDiff, ReplayFlip, Role, Rollforward, Rule, RuleAction,
    RuleProposal, Ruling, Session, SessionRequest, SessionResponse, Source, SourceKind, StormRun, StormSummary,
    TraceEvent,
)

FIXTURES = Path(__file__).resolve().parent / "fixtures" / "api"
UTC = timezone.utc
DEMO_START = datetime(2025, 1, 25, 6, 0, tzinfo=UTC)     # "the morning after" Éowyn
STUB_SECRET = b"stormcheck-stub-not-a-secret"
APPROVER_ROLES = {Role.CONTROLLER, Role.CFO, Role.CLAIMS_LEAD}
AGENT_ROLES = {Role.READER, Role.DRAFTER, Role.ENGINE, Role.CRM_BOT}
ROLE_LABEL = {Role.CLAIMS_LEAD: "Claims Lead", Role.LEGAL: "Legal", Role.CONTROLLER: "Controller", Role.OPS: "Ops",
              Role.CFO: "CFO", Role.JUDGE: "Judge"}


def label(role: Role) -> str:
    return ROLE_LABEL.get(role, role.value)


SSE_SETTINGS: dict[str, Any] = {
    "interval": float(os.environ.get("STUB_SSE_INTERVAL", "2")),
    "loop": os.environ.get("STUB_SSE_LOOP", "1") != "0",
    "ping": 15,
}


# ---------------------------------------------------------------- fixtures
def load(name: str, tp: Any) -> Any:
    return TypeAdapter(tp).validate_json((FIXTURES / name).read_bytes())


HEALTH: Health = load("health.json", Health)
STORMS: list[StormSummary] = load("storms.json", list[StormSummary])
STORM_RUNS: dict[str, StormRun] = {s.id: load(f"storm_{s.id}.json", StormRun) for s in STORMS}
FLIGHT_FILES: dict[str, FlightFile] = {
    p.stem.removeprefix("flight_"): load(p.name, FlightFile) for p in sorted(FIXTURES.glob("flight_*.json"))}
QUESTIONS: list[Question] = load("questions.json", list[Question])
TRACE: list[TraceEvent] = load("trace.json", list[TraceEvent])
RULES: list[Rule] = load("rules.json", list[Rule])
COMMITS: list[Commit] = load("commits.json", list[Commit])
BLAME: Blame = load("blame.json", Blame)
AUDIT: dict[str, Any] = load("audit.json", dict[str, Any])
ROLLFORWARDS: dict[str, Rollforward] = {
    p.stem.removeprefix("rollforward_"): load(p.name, Rollforward) for p in FIXTURES.glob("rollforward_*.json")}
ESTIMATE: EstimateCard = load("estimate.json", EstimateCard)
JOURNAL: list[JournalEntry] = load("journal.json", list[JournalEntry])
MONTH_END_JE: JournalEntry = load("month_end_je.json", JournalEntry)
CURVES: dict[str, ClaimCurve] = {
    p.stem.removeprefix("curve_"): load(p.name, ClaimCurve) for p in FIXTURES.glob("curve_*.json")}
CFO: CfoMetrics = load("cfo.json", CfoMetrics)
INVARIANTS: list[InvariantResult] = load("invariants.json", list[InvariantResult])
ACCESS_MATRIX: AccessMatrix = load("access_matrix.json", AccessMatrix)
ACCESS_LOG: list[AccessDecision] = load("access_log.json", list[AccessDecision])
CONTROLS: list[ControlMapping] = load("controls.json", list[ControlMapping])
INJECTIONS: list[Injection] = load("injections.json", list[Injection])
EVAL: EvalReport = load("eval.json", EvalReport)
STORM_ID = "EIDW@2025-01-24"
EU_COUNTRIES = {"AT", "BE", "BG", "HR", "CY", "CZ", "DK", "EE", "FI", "FR", "DE", "GR", "HU", "IE", "IT", "LV",
                "LT", "LU", "MT", "NL", "PL", "PT", "RO", "SK", "SI", "ES", "SE", "IS", "LI", "NO", "CH"}  # EU27+EEA+CH


# ---------------------------------------------------------------- canned rule proposals (plan §1.4)
def _iso(t: datetime) -> str:
    return t.isoformat().replace("+00:00", "Z")


def _flip_ext(fid: str, delta: int, before: str = "needs_legal", after: str = "extraordinary") -> ReplayFlip:
    return ReplayFlip(entity_id=fid, field="extraordinary", before=before, after=after, delta_cents=delta)


KNOCK_DELTAS = {"NS113@2025-01-24": -1922400, "NS115@2025-01-24": -1987200, "NS117@2025-01-24": -840000}


def canned_proposal(qid: str, ruling: Ruling, at: datetime) -> RuleProposal:
    checks = {"compiles": True, "reproduces_case": True, "no_hard_control": True, "grounded": True,
              "author_has_authority": True, "no_conflict": True}
    if qid == "Q-1":
        rule = Rule(
            id="R-CL-1", version=1, kind="voucher", scope={"flight.departs_eu": "case:true"},
            condition={"all": [{"f": "voucher.in_lieu", "op": "eq", "v": True},
                               {"f": "voucher.signed", "op": "eq", "v": False},
                               {"f": "flight.departs_eu", "op": "eq", "v": True}]},
            action=RuleAction.DENY_OFFSET, tier="claims_lead_ruling", authority_required=Role.CLAIMS_LEAD,
            origin_ruling_id=ruling.id, origin_example="NS31@2025-01-24:14C",
            grounding={"voucher.signed=false": "No signed acceptance", "action=deny_offset": "no offset",
                       "voucher.in_lieu=true": "the voucher stays as goodwill"},
            valid_from=None, recorded_at=at, status="proposed",
            title="No signed acceptance, no offset: pay cash; the voucher stays as goodwill "
                  "(every flight leaving the EU)")
        diff = ReplayDiff(rule_ref="R-CL-1@1", known_at=at, total_delta_cents=0, flips=[
            ReplayFlip(entity_id="NS31@2025-01-24:14C", field="status", before="needs_ruling", after="owed")])
        return RuleProposal(rule=rule, checks=checks, would_flip=diff,
                            widen_next={"remove": "flight.departs_eu",
                                        "question": "Also flights arriving into the EU (e.g. BOS→DUB)?"})
    if qid == "Q-2":
        rule = Rule(
            id="R-LEG-1", version=1, kind="cause", scope={"rotation.prev_cause": "case:weather"},
            condition={"all": [{"f": "flight.is_return_sector", "op": "eq", "v": True},
                               {"f": "rotation.prev_cancelled", "op": "eq", "v": True},
                               {"f": "spare.available_within_h", "op": "gt", "v": 3},
                               {"f": "pax.reroute_earliest_offered", "op": "eq", "v": True}]},
            action=RuleAction.SET_EXTRAORDINARY, tier="legal_ruling", authority_required=Role.LEGAL,
            origin_ruling_id=ruling.id, origin_example="NS117@2025-01-24",
            grounding={"3": "within 3 h of STD", "flight.is_return_sector=true": "A return sector",
                       "rotation.prev_cancelled=true": "storm-cancelled rotation",
                       "pax.reroute_earliest_offered=true": "offered the earliest reroute on any carrier"},
            valid_from=None, recorded_at=at, status="proposed",
            title="A return sector of a storm-cancelled rotation is extraordinary only if no aircraft and crew "
                  "could operate it within 3 h of STD and passengers were offered the earliest reroute (C-74/19)")
        diff = ReplayDiff(rule_ref="R-LEG-1@1", known_at=at, total_delta_cents=sum(KNOCK_DELTAS.values()),
                          flips=[_flip_ext(k, v) for k, v in KNOCK_DELTAS.items()])
        return RuleProposal(rule=rule, checks=checks, would_flip=diff,
                            widen_next={"remove": "rotation.prev_cause",
                                        "question": "Any cancelled previous rotation, not only weather?"})
    # Q-3: the Controller's rejection becomes a rule
    rule = Rule(
        id="R-CTL-1", version=1, kind="release", scope={"cohort": "case:EIDW@2024-01-21"},
        condition={"all": [{"f": "cohort.age_months", "op": "ge", "v": 12},
                           {"f": "cohort.limitation_expired", "op": "eq", "v": False}]},
        action=RuleAction.KEEP_TAIL, tier="controller_ruling", authority_required=Role.CONTROLLER,
        origin_ruling_id=ruling.id, origin_example="EIDW@2024-01-21",
        grounding={"12": "At M12", "cohort.limitation_expired=false": "until the six-year limitation",
                   "action=keep_tail": "Never release the tail"},
        valid_from=at, recorded_at=at, status="proposed",
        title="Never release the tail: at M12 keep (ultimate − M12 rate) × entitlement until the six-year limitation")
    diff = ReplayDiff(rule_ref="R-CTL-1@1", known_at=at, total_delta_cents=0, flips=[
        ReplayFlip(entity_id="EIDW@2024-01-21", field="release_proposed_cents", before=360000, after=0)])
    return RuleProposal(rule=rule, checks=checks, would_flip=diff,
                        widen_next={"remove": "cohort", "question": "All storm cohorts?"})


RULE_TO_QUESTION = {"R-CL-1": "Q-1", "R-LEG-1": "Q-2", "R-CTL-1": "Q-3"}


# ---------------------------------------------------------------- in-memory state
class StubState:
    def __init__(self) -> None:
        self.clock = DEMO_START
        self.trace: list[TraceEvent] = [e.model_copy() for e in TRACE]
        self.replayed: set[int] = set()
        self.rulings: dict[str, Ruling] = {}            # question_id -> ruling
        self.proposals: dict[str, RuleProposal] = {}    # rule id -> latest proposal
        self.rules: dict[str, Rule] = {r.id: r.model_copy() for r in RULES}
        self.journal: dict[str, JournalEntry] = {j.id: j.model_copy() for j in JOURNAL}
        self.access_log: list[AccessDecision] = [a.model_copy() for a in ACCESS_LOG]
        self.locked: list[str] = []
        self.counter = 0

    def next_id(self, prefix: str) -> str:
        self.counter += 1
        return f"{prefix}-{self.counter:04d}"

    def emit(self, kind: str, actor: str, summary: str, chip: str, ref: str | None = None,
             amount: int | None = None) -> TraceEvent:
        ev = TraceEvent(seq=self.trace[-1].seq + 1 if self.trace else 1, at=self.clock, kind=kind, actor=actor,
                        summary=summary, ref=ref, chip=chip, amount_cents=amount)
        self.trace.append(ev)
        return ev

    def replay_next(self) -> TraceEvent:
        """Append a copy of the next fixture event with a fresh seq (keeps ids unique and monotonic)."""
        src = TRACE[len(self.replayed) % len(TRACE)]
        ev = src.model_copy(update={"seq": self.trace[-1].seq + 1})
        self.trace.append(ev)
        self.replayed.add(ev.seq)
        return ev

    def after(self, seq: int) -> TraceEvent | None:
        return next((e for e in self.trace if e.seq > seq), None)

    def question_status(self, q: Question) -> str:
        if q.id in self.rulings:
            return "answered"
        if q.remind_at is not None and self.clock >= q.remind_at:
            return "reminded"
        return "open"

    def questions(self) -> list[Question]:
        return [q.model_copy(update={"status": self.question_status(q)}) for q in QUESTIONS]


STATE = StubState()


# ---------------------------------------------------------------- errors
class ApiError(Exception):
    def __init__(self, status: int, code: str, message: str) -> None:
        super().__init__(message)
        self.status, self.code, self.message = status, code, message


def envelope(status: int, code: str, message: str) -> JSONResponse:
    return JSONResponse(status_code=status,
                        content=ErrorEnvelope(error=ErrorBody(code=code, message=message)).model_dump(mode="json"))


ERRORS: dict[int | str, dict[str, Any]] = {
    404: {"model": ErrorEnvelope, "description": "Not found"},
    422: {"model": ErrorEnvelope, "description": "Bad input (plain message)"},
}
ERRORS_AUTH: dict[int | str, dict[str, Any]] = {**ERRORS, 403: {"model": ErrorEnvelope, "description": "Forbidden"}}


# ---------------------------------------------------------------- auth
def _b64(b: bytes) -> str:
    return base64.urlsafe_b64encode(b).decode().rstrip("=")


def make_token(s: Session) -> str:
    payload = _b64(s.model_dump_json().encode())
    sig = hmac.new(STUB_SECRET, payload.encode(), hashlib.sha256).hexdigest()[:32]
    return f"{payload}.{sig}"


def session_of(request: Request) -> Session:
    """Fail closed: a missing, malformed or forged token is the read-only judge."""
    judge = Session(principal="judge", role=Role.JUDGE, name="Judge", issued_at=STATE.clock)
    auth = request.headers.get("authorization", "")
    if not auth.lower().startswith("bearer "):
        return judge
    token = auth.split(" ", 1)[1].strip()
    try:
        payload, sig = token.rsplit(".", 1)
        good = hmac.new(STUB_SECRET, payload.encode(), hashlib.sha256).hexdigest()[:32]
        if not hmac.compare_digest(sig, good):
            return judge
        return Session.model_validate_json(base64.urlsafe_b64decode(payload + "=" * (-len(payload) % 4)))
    except Exception:
        return judge


def deny(principal: str, action: str, resource: str, code: str, reason: str) -> ApiError:
    STATE.access_log.append(AccessDecision(at=STATE.clock, principal=principal, action=action, resource=resource,
                                           allowed=False, reason=reason))
    STATE.emit("access_denied", principal, f"{principal} {action} → DENIED · {reason}", "DENIED", resource)
    return ApiError(403, code, reason)


# ---------------------------------------------------------------- app
app = FastAPI(title="StormCheck API (contract stub)", version="2.0.0",
              description="Contract stub for CONTRACTS.md §3. Fixtures: contracts/fixtures/api/.")
app.add_middleware(CORSMiddleware, allow_origins=["http://localhost:5173", "http://127.0.0.1:5173"],
                   allow_credentials=True, allow_methods=["*"], allow_headers=["*"], expose_headers=["*"])


@app.exception_handler(ApiError)
async def _api_error(_: Request, exc: ApiError) -> JSONResponse:
    return envelope(exc.status, exc.code, exc.message)


@app.exception_handler(RequestValidationError)
async def _validation_error(_: Request, exc: RequestValidationError) -> JSONResponse:
    errs = exc.errors()
    if errs:
        loc = ".".join(str(x) for x in errs[0].get("loc", ()) if x not in ("body", "query", "path"))
        msg = f"{loc}: {errs[0].get('msg', 'invalid value')}" if loc else errs[0].get("msg", "invalid value")
    else:
        msg = "The request could not be read."
    return envelope(422, "validation", msg)


@app.exception_handler(StarletteHTTPException)
async def _http_error(_: Request, exc: StarletteHTTPException) -> JSONResponse:
    code = {404: "not_found", 401: "forbidden", 403: "forbidden"}.get(exc.status_code, "validation")
    return envelope(exc.status_code, code, str(exc.detail))


class SSEResponse(EventSourceResponse):
    media_type = "text/event-stream"   # class-level, so OpenAPI documents the stream's content type


# ================================================================ reads
@app.get("/api/health", response_model=Health)
def health() -> Health:
    return HEALTH


@app.get("/api/storms", response_model=list[StormSummary])
def list_storms() -> list[StormSummary]:
    open_ = sum(1 for q in STATE.questions() if q.status != "answered")
    return [s.model_copy(update={"questions": open_}) if s.id == STORM_ID else s for s in STORMS]


@app.get("/api/storms/{storm_id}", response_model=StormRun, responses=ERRORS)
def get_storm(storm_id: str) -> StormRun:
    run = STORM_RUNS.get(storm_id)
    if run is None:
        raise ApiError(404, "not_found", f"No storm run {storm_id}. Known: {', '.join(STORM_RUNS)}.")
    live = [e for e in STATE.trace if e.seq > TRACE[-1].seq and e.seq not in STATE.replayed]
    return run.model_copy(update={"questions": STATE.questions(), "feed": [*run.feed, *live]})


@app.get("/api/flights/{flight_id}", response_model=FlightFile, responses=ERRORS)
def get_flight(flight_id: str) -> FlightFile:
    ff = FLIGHT_FILES.get(flight_id)
    if ff is not None:
        return ff
    run = STORM_RUNS[STORM_ID]
    if any(r.flight.id == flight_id for r in run.flights):
        raise ApiError(404, "not_found", f"{flight_id} operated normally, so there is no decision to show.")
    raise ApiError(404, "not_found", f"No flight {flight_id}. IDs look like NS31@2025-01-24.")


@app.get("/api/questions", response_model=list[Question])
def list_questions(request: Request, status: str | None = Query(None, description="open | answered | reminded; "
                                                                "open also returns reminded (both unanswered)")
                   ) -> list[Question]:
    s = session_of(request)
    qs = STATE.questions()
    if s.role in (Role.CLAIMS_LEAD, Role.LEGAL, Role.CONTROLLER, Role.OPS):
        qs = [q for q in qs if q.routed_to == s.role]
    if status == "open":
        qs = [q for q in qs if q.status in ("open", "reminded")]
    elif status:
        qs = [q for q in qs if q.status == status]
    return qs


@app.get("/api/rules", response_model=list[Rule])
def list_rules() -> list[Rule]:
    return list(STATE.rules.values())


@app.get("/api/trace", response_model=list[TraceEvent])
def get_trace(since: int = Query(0, ge=0)) -> list[TraceEvent]:
    return [e for e in STATE.trace if e.seq > since]


async def trace_stream(after: int = 0, *, interval: float | None = None, loop: bool | None = None,
                       state: StubState | None = None) -> AsyncIterator[dict[str, str]]:
    """SSE payloads: every `interval` s the next event after `after`; when the log is exhausted, replay."""
    st = state or STATE
    interval = SSE_SETTINGS["interval"] if interval is None else interval
    loop = SSE_SETTINGS["loop"] if loop is None else loop
    cursor = after
    while True:
        ev = st.after(cursor)
        if ev is None:
            if not loop:
                return
            ev = st.replay_next()
        cursor = ev.seq
        yield {"event": "trace", "id": str(ev.seq), "data": ev.model_dump_json()}
        await asyncio.sleep(interval)


@app.get("/api/stream", response_model=TraceEvent, response_class=SSEResponse,
         responses={200: {"description": "text/event-stream; each `data:` line is one TraceEvent (JSON)"}},
         description="SSE: `event: trace`, `id: <seq>`, `data: TraceEvent` JSON. Send `Last-Event-ID` to resume. "
                     "Heartbeat: an SSE comment every 15 s.")
async def stream(request: Request) -> EventSourceResponse:
    try:
        after = int(request.headers.get("last-event-id", "0") or 0)
    except ValueError:
        after = 0
    return SSEResponse(trace_stream(after), ping=SSE_SETTINGS["ping"])


@app.get("/api/commits", response_model=list[Commit])
def list_commits(limit: int = Query(100, ge=1, le=1000)) -> list[Commit]:
    return COMMITS[:limit]


@app.get("/api/blame", response_model=Blame, responses=ERRORS)
def blame(target: str = Query(..., description="any id: JE line, entitlement, coupon, flight, rule")) -> Blame:
    if target.startswith(("NS31@2025-01-24", "JE-000101")):
        return BLAME.model_copy(update={"target": target})
    return Blame(target=target, steps=[])


@app.get("/api/audit/{je_id}", response_model=dict[str, Any], responses=ERRORS)
def audit(je_id: str) -> dict[str, Any]:
    if je_id == AUDIT["je"]["id"]:
        return AUDIT
    je = STATE.journal.get(je_id)
    if je is None:
        raise ApiError(404, "not_found", f"No journal entry {je_id}.")
    return {"je": je.model_dump(mode="json"), "register": [], "decision_commits": [],
            "sources": [], "blame_target": f"{je_id}:1"}


@app.get("/api/books/rollforward", response_model=Rollforward)
def rollforward(period: str = Query("2025-02", pattern=r"^\d{4}-\d{2}$")) -> Rollforward:
    rf = ROLLFORWARDS.get(period)
    if rf is not None:
        return rf
    return Rollforward(period=period, rows=[], closing_total_cents=0, gl_balance_cents=0, ties_to_gl=True)


@app.get("/api/books/estimate", response_model=EstimateCard, responses=ERRORS)
def estimate(cohort: str = Query(STORM_ID)) -> EstimateCard:
    if cohort != ESTIMATE.cohort:
        raise ApiError(404, "not_found", f"No estimate card for cohort {cohort}. Try {ESTIMATE.cohort}.")
    return ESTIMATE


@app.get("/api/books/journal", response_model=list[JournalEntry])
def journal(period: str | None = Query(None), status: str | None = Query(None)) -> list[JournalEntry]:
    out = list(STATE.journal.values())
    if period:
        out = [j for j in out if j.period == period]
    if status:
        out = [j for j in out if j.status == status]
    return out


@app.get("/api/books/curve", response_model=ClaimCurve, responses=ERRORS)
def curve(segment: str = Query("long_haul_gt3500",
                               description="long_haul_gt3500 | medium_1500_3500 | short_le1500")) -> ClaimCurve:
    c = CURVES.get(segment)
    if c is None:
        raise ApiError(422, "validation", f"Unknown segment {segment}. Use one of: {', '.join(sorted(CURVES))}.")
    return c


@app.get("/api/books/cfo", response_model=CfoMetrics)
def cfo() -> CfoMetrics:
    return CFO.model_copy(update={"as_of": STATE.clock})


@app.get("/api/books/invariants", response_model=list[InvariantResult])
def invariants() -> list[InvariantResult]:
    return INVARIANTS


@app.get("/api/access/matrix", response_model=AccessMatrix)
def access_matrix() -> AccessMatrix:
    return ACCESS_MATRIX


@app.get("/api/access/log", response_model=list[AccessDecision])
def access_log() -> list[AccessDecision]:
    return STATE.access_log


@app.get("/api/controls", response_model=list[ControlMapping])
def controls() -> list[ControlMapping]:
    return CONTROLS


@app.get("/api/injections", response_model=list[Injection])
def injections() -> list[Injection]:
    return INJECTIONS


@app.get("/api/eval", response_model=EvalReport)
def eval_report() -> EvalReport:
    return EVAL


# pitch insights (insights-v1): computed by the real server from a run's real data; the stub has no run data to
# compute them from, so it declares the shapes (OpenAPI, web types) and serves nothing
@app.get("/api/runs/{run_id}/effort", response_model=EffortEstimate, responses=ERRORS)
def run_effort(run_id: str) -> EffortEstimate:
    raise ApiError(404, "not_found", f"The effort estimate for {run_id} is computed by the real server (make dev).")


@app.get("/api/learning", response_model=list[LearningStep])
def learning() -> list[LearningStep]:
    return []


# ================================================================ writes
@app.post("/api/session", response_model=SessionResponse, responses=ERRORS)
def create_session(req: SessionRequest) -> SessionResponse:
    slug = re.sub(r"[^a-z0-9]+", "-", req.name.lower()).strip("-") or "anon"
    principal = req.role.value if req.role in AGENT_ROLES or req.role == Role.JUDGE else f"{req.role.value}:{slug}"
    s = Session(principal=principal, role=req.role, name=req.name, issued_at=STATE.clock)
    return SessionResponse(token=make_token(s), session=s)


def _decision_or_404(flight_id: str):
    ff = FLIGHT_FILES.get(flight_id)
    if ff is None:
        raise ApiError(404, "not_found", f"No decision for {flight_id}.")
    return ff.decision


HIDDEN_DEFECT = ("hidden defect", "manufactur", "airbus", "operator notice", "batch")
NEW_FACT = ("tech log", "logged", "photo", "receipt", "attached", "metar")


@app.post("/api/flights/{flight_id}/challenge", response_model=ChallengeResponse, responses=ERRORS)
def challenge(flight_id: str, req: ChallengeRequest) -> ChallengeResponse:
    d = _decision_or_404(flight_id)
    text = req.text.lower()
    tier1 = [e for e in d.evidence if e.trust_tier == 1 and not e.struck][:4]
    if any(k in text for k in HIDDEN_DEFECT):
        q = Question(
            id=STATE.next_id("Q-CH"), case_refs=[flight_id], pattern="new_legal_pattern", routed_to=Role.LEGAL,
            asked_at=STATE.clock, title=f"Does a manufacturer hidden-defect notice make {flight_id} extraordinary?",
            found=f"Challenge on {flight_id}: '{req.text[:160]}'. Challenge facts are trust tier 4.",
            why_flagged="New legal pattern: a hidden manufacturing defect can be extraordinary (C-549/07 ¶26). "
                        "No precedent.",
            recommends="Keep the decision until Legal rules; ask the manufacturer for the notice.",
            recommended_option="Keep the decision; request the notice",
            options=["Keep the decision; request the notice", "Treat as extraordinary", "Not relevant"],
            evidence=tier1, confidence=Confidence(score=0.52, kind="cause", label="cause-finding confidence",
                                                  features={"precedent_count": 0.0, "sources_disagree": 1.0},
                                                  caps=["capped:no-precedent"], calibration_version="cal-v1"),
            reason_tag="new-legal-pattern", holds=[flight_id], status="open",
            remind_at=STATE.clock + timedelta(hours=3))
        STATE.emit("question", "agent.engine", f"Asked Legal: hidden-defect challenge on {flight_id} · confidence "
                   "52% · no precedent", "ASKED", q.id)
        reply = Draft(id=STATE.next_id("DRAFT-CH"), kind="challenge_reply", numbers_verified=True,
                      text="Routed to Legal. A manufacturer's hidden-defect notice is a new legal pattern "
                           "(C-549/07 ¶26). The decision is unchanged until Legal rules.")
        return ChallengeResponse(classification="new_legal_pattern", decision_stands=False, reply=reply, cited=tier1,
                                 question=q)
    cls = "new_fact" if any(k in text for k in NEW_FACT) else "assertion"
    if flight_id == "NS31@2025-01-24":
        body = ("Decision stands. Dublin's storm window closed at 15:00Z; from 16:00Z gusts were 25 kt or less. "
                "11 Northstar departures operated 15:30–17:30Z. EI-NSB was AOG from 23 Jan 21:40Z with no MEL "
                "relief, before the storm.")
    else:
        body = f"Decision stands. {d.reason}"
    STATE.emit("decision", "agent.engine", f"Challenge on {d.flight_id.split('@')[0]} · {cls} · decision stands",
               "INFO", flight_id)
    reply = Draft(id=STATE.next_id("DRAFT-CH"), kind="challenge_reply", text=body, numbers_verified=True,
                  template_fallback=True)
    return ChallengeResponse(classification=cls, decision_stands=True, reply=reply, cited=tier1, question=None)


@app.post("/api/questions/{question_id}/answer", response_model=AnswerResponse, responses=ERRORS_AUTH)
def answer(question_id: str, req: AnswerRequest, request: Request) -> AnswerResponse:
    q = next((x for x in QUESTIONS if x.id == question_id), None)
    if q is None:
        raise ApiError(404, "not_found", f"No question {question_id}.")
    s = session_of(request)
    if s.role != q.routed_to:
        raise deny(s.principal, "answer", question_id, "forbidden",
                   f"{question_id} is routed to {label(q.routed_to)}; sign in as that role to answer")
    kind = "rejection" if question_id == "Q-3" or req.decision.lower().startswith(("reject", "keep")) else "answer"
    ruling = Ruling(id=STATE.next_id("RUL"), question_id=question_id, author_role=s.role, author=s.name, kind=kind,
                    decision=req.decision, explanation=req.explanation, at=STATE.clock)
    STATE.rulings[question_id] = ruling
    proposal = canned_proposal(question_id, ruling, STATE.clock)
    STATE.proposals[proposal.rule.id] = proposal
    STATE.emit("ruling", s.principal, f"{label(s.role)} ruled on {question_id} · rule {proposal.rule.id}@1 proposed",
               "RULED", question_id, q.holds_cents or None)
    return AnswerResponse(ruling=ruling, proposal=proposal)


def _base_id(rule_id: str) -> str:
    return rule_id.split("@", 1)[0]


def _proposal_for(rule_id: str) -> RuleProposal | None:
    rid = _base_id(rule_id)
    if rid in STATE.proposals:
        return STATE.proposals[rid]
    if rid in RULE_TO_QUESTION:   # canned path even before an answer, so every screen can be built
        qid = RULE_TO_QUESTION[rid]
        r = Ruling(id=f"RUL-{qid}", question_id=qid, author_role=next(q.routed_to for q in QUESTIONS if q.id == qid),
                   author="(stub)", kind="rejection" if qid == "Q-3" else "answer",
                   decision="as recommended", explanation="", at=STATE.clock)
        return canned_proposal(qid, r, STATE.clock)
    return None


@app.post("/api/proposals/{rule_id}/confirm", response_model=ConfirmResponse, responses=ERRORS_AUTH)
def confirm(rule_id: str, request: Request) -> ConfirmResponse:
    rid = _base_id(rule_id)
    p = _proposal_for(rid)
    if p is None:
        existing = STATE.rules.get(rid)
        if existing is None:
            raise ApiError(404, "not_found", f"No proposal {rule_id}.")
        return ConfirmResponse(rule=existing, replay=ReplayDiff(rule_ref=f"{rid}@{existing.version}",
                                                                known_at=STATE.clock, flips=[], total_delta_cents=0))
    n = len(p.would_flip.flips)
    rule = p.rule.model_copy(update={"status": "active", "times_cited": n})
    STATE.rules[rid] = rule
    STATE.emit("rule", session_of(request).principal,
               f"Saved as policy {rid}@{rule.version} · never asked again · {n} settled · cited {n}×", "LEARNED",
               f"{rid}@{rule.version}", p.would_flip.total_delta_cents or None)
    return ConfirmResponse(rule=rule, replay=p.would_flip)


@app.post("/api/rules/{rule_id}/reject", response_model=AnswerResponse, responses=ERRORS_AUTH)
def reject(rule_id: str, req: RejectRequest, request: Request) -> AnswerResponse:
    rid = _base_id(rule_id)
    rule = STATE.rules.get(rid) or (p.rule if (p := _proposal_for(rid)) else None)
    if rule is None:
        raise ApiError(404, "not_found", f"No rule or proposal {rule_id}.")
    s = session_of(request)
    ruling = Ruling(id=STATE.next_id("RUL"), question_id=RULE_TO_QUESTION.get(rid), author_role=s.role,
                    author=s.name, kind="rejection", decision="reject", explanation=req.explanation, at=STATE.clock)
    if rid in STATE.rules and not rule.static_card:
        STATE.rules[rid] = rule.model_copy(update={"status": "retired"})
    proposal = canned_proposal("Q-3", ruling, STATE.clock) if rule.kind == "release" or rid == "R-CTL-1" else None
    if proposal:
        STATE.proposals[proposal.rule.id] = proposal
    STATE.emit("ruling", s.principal, f"{label(s.role)} rejected {rid}" + (" · rule R-CTL-1@1 proposed" if proposal
                                                                          else ""), "RULED", rid)
    return AnswerResponse(ruling=ruling, proposal=proposal)


@app.post("/api/rules/{rule_id}/widen", response_model=RuleProposal, responses=ERRORS)
def widen(rule_id: str) -> RuleProposal:
    rid = _base_id(rule_id)
    p = _proposal_for(rid)
    rule = STATE.rules.get(rid) or (p.rule if p else None)
    if rule is None:
        raise ApiError(404, "not_found", f"No rule {rule_id}.")
    case_keys = [k for k, v in rule.scope.items() if isinstance(v, str) and v.startswith("case:")]
    if not case_keys:
        raise ApiError(422, "validation", f"{rid} has no case-scoped key left to widen.")
    key = case_keys[0]
    scope = {k: v for k, v in rule.scope.items() if k != key}
    condition = {**rule.condition, "all": [c for c in rule.condition.get("all", []) if c.get("f") != key]}
    title = {"R-CTL-1": "Never release the tail, for all storm cohorts: keep (ultimate − M12 rate) × entitlement "
                        "until the six-year limitation"}.get(rid, rule.title)
    wider = rule.model_copy(update={"version": rule.version + 1, "scope": scope, "condition": condition,
                                    "status": "proposed", "supersedes": f"{rid}@{rule.version}",
                                    "recorded_at": STATE.clock, "title": title})
    rest = [k for k in case_keys if k != key]
    return RuleProposal(rule=wider, checks={"compiles": True, "reproduces_case": True, "no_hard_control": True,
                                            "grounded": True, "author_has_authority": True, "no_conflict": True},
                        would_flip=ReplayDiff(rule_ref=f"{rid}@{wider.version}", known_at=STATE.clock, flips=[],
                                              total_delta_cents=0),
                        widen_next={"remove": rest[0]} if rest else None)


@app.post("/api/rules/{rule_id}/revert", response_model=ReplayDiff, responses=ERRORS)
def revert(rule_id: str, request: Request) -> ReplayDiff:
    rid = _base_id(rule_id)
    rule = STATE.rules.get(rid)
    if rule is None:
        raise ApiError(404, "not_found", f"No rule {rule_id}.")
    STATE.rules[rid] = rule.model_copy(update={"status": "retired"})
    flips = ([_flip_ext(k, -v, before="extraordinary", after="needs_legal") for k, v in KNOCK_DELTAS.items()]
             if rid == "R-LEG-1" else [])
    total = sum(f.delta_cents for f in flips)
    diff = ReplayDiff(rule_ref=f"{rid}@{rule.version}", known_at=STATE.clock, flips=flips, total_delta_cents=total,
                      locked_periods_untouched=list(STATE.locked),
                      adjustment_je_ids=[STATE.next_id("JE-ADJ")] if total else [])
    STATE.emit("replay", session_of(request).principal, f"Reverted {rid}@{rule.version} · flips {len(flips)}"
               + (" · " + ", ".join(STATE.locked) + " locked, untouched" if STATE.locked else ""), "INFO", rid,
               total or None)
    return diff


@app.post("/api/books/journal/{je_id}/approve", response_model=JournalEntry, responses=ERRORS_AUTH)
def approve(je_id: str, request: Request) -> JournalEntry:
    je = STATE.journal.get(je_id)
    if je is None:
        raise ApiError(404, "not_found", f"No journal entry {je_id}.")
    s = session_of(request)
    if s.role in AGENT_ROLES:
        raise deny(s.principal, "approve_je", je_id, "sod_violation", "SoD: agents never approve")
    if s.principal == je.preparer:
        raise deny(s.principal, "approve_je", je_id, "sod_violation", "SoD: preparer ≠ approver")
    if s.role not in APPROVER_ROLES:
        raise deny(s.principal, "approve_je", je_id, "forbidden", f"{label(s.role)} cannot approve journal entries")
    if je.period in STATE.locked:
        raise deny(s.principal, "approve_je", je_id, "forbidden", f"period {je.period} is locked")
    out = je.model_copy(update={"status": "approved", "approver": s.principal})
    STATE.journal[je_id] = out
    STATE.emit("journal", s.principal, f"{je_id} approved by {label(s.role)} · parked, not posted", "APPLIED", je_id,
               sum(line.dr_cents for line in je.lines))
    return out


@app.post("/api/books/month-end", response_model=MonthEndResponse, responses=ERRORS_AUTH)
def month_end(req: PeriodRequest) -> MonthEndResponse:
    if not re.fullmatch(r"\d{4}-\d{2}", req.period):
        raise ApiError(422, "validation", f"period must look like 2025-02, got {req.period!r}.")
    if req.period in STATE.locked:
        raise ApiError(403, "forbidden", f"Period {req.period} is locked; nothing is written to it.")
    rf = ROLLFORWARDS.get(req.period) or ROLLFORWARDS["2025-02"]
    STATE.journal[MONTH_END_JE.id] = MONTH_END_JE
    STATE.emit("journal", "agent.books", "Month end · BF true-up · drafted +€3,990 change in estimate (Dr 4090 / "
               "Cr 2140)", "DRAFTED", MONTH_END_JE.id, 399000)
    return MonthEndResponse(entries=[MONTH_END_JE], rollforward=rf, estimate=ESTIMATE)


@app.post("/api/books/lock", response_model=LockResponse, responses=ERRORS_AUTH)
def lock(req: PeriodRequest, request: Request) -> LockResponse:
    if not re.fullmatch(r"\d{4}-\d{2}", req.period):
        raise ApiError(422, "validation", f"period must look like 2025-01, got {req.period!r}.")
    if req.period not in STATE.locked:
        STATE.locked.append(req.period)
    STATE.emit("info", session_of(request).principal, f"Period {req.period} locked", "LOCKED", req.period)
    return LockResponse(locked=req.period)


_ICAO = airportsdata.load("ICAO")


@app.post("/api/desk", response_model=StormRun, responses=ERRORS)
def desk(req: DeskRequest) -> StormRun:
    icao = req.icao.strip().upper()
    if icao not in _ICAO:
        raise ApiError(422, "unknown_airport", f"We don't know the airport '{req.icao}'. Use an ICAO code like "
                                               "EIDW or EGLL.")
    if req.date > date.today():
        raise ApiError(422, "future_date", f"{req.date.isoformat()} hasn't happened yet, so there is no weather "
                                           "to read. Pick a past date.")
    run_id = f"{icao}@{req.date.isoformat()}"
    STATE.emit("info", "judge", f"Desk ran {run_id}", "INFO", run_id)
    if run_id in STORM_RUNS:
        return get_storm(run_id)
    a = _ICAO[icao]
    ap = Airport(icao=icao, iata=a.get("iata") or icao, name=a["name"], lat=float(a["lat"]), lon=float(a["lon"]),
                 country=a["country"], eu=a["country"] in EU_COUNTRIES, tz=a["tz"])
    return StormRun(id=run_id, station=icao, date=req.date, windows=[], metar=[], flights=[],
                    counters={"passengers": 0, "cancelled": 0, "operated": 0, "drafted": 0, "held": 0,
                              "questions": 0, "people": 0, "repeat_questions": 0, "rules_cited": 0},
                    entitlement_cents=0, liability_drafted_cents=0, learned=[], questions=[], feed=[],
                    message="stub · no storm window (the real server reads this day's METAR)", airports=[ap])


_KIND = {"tech_log": (SourceKind.TECH_LOG, 1, ["maintenance"]), "occ_log": (SourceKind.OCC_LOG, 3, ["ops"]),
         "crm": (SourceKind.CRM, 3, ["pii", "finance"]), "claim": (SourceKind.CLAIM, 4, ["pii"]),
         "email": (SourceKind.EMAIL, 4, ["pii"]), "manufacturer": (SourceKind.MANUFACTURER, 2, ["maintenance"])}
_INJECTION_WORDS = ("ignore previous", "ignore all previous", "system:", "disregard", "you are now")


@app.post("/api/inject", response_model=InjectResponse, responses=ERRORS)
def inject(req: InjectRequest) -> InjectResponse:
    kind, tier, tags = _KIND[req.kind]
    sid = STATE.next_id("SRC-INJ")
    src = Source(id=sid, kind=kind, title=f"Injected {req.kind.replace('_', ' ')}", text=req.text,
                 sha256=hashlib.sha256(req.text.encode()).hexdigest(), received_at=STATE.clock, trust_tier=tier,
                 acl_tags=tags)
    subject = f"flight:{req.flight_id}" if req.flight_id else "unresolved"
    facts: list[Fact] = []
    dropped = 0
    lowered = req.text.lower()
    if any(w in lowered for w in _INJECTION_WORDS):
        dropped = 1
        message = "Instructions inside a source are data, not commands · 0 facts accepted · nothing approved"
    else:
        patterns = [("aog.mel_relief", r"NO MEL RELIEF", False), ("aog.logged_at", r"\b\d{2}:\d{2}Z\b", None),
                    ("claim.amount_cents", r"(?:€|EUR ?|£)\d[\d,]*(?:\.\d{2})?", None)]
        for field, pat, value in patterns:
            m = re.search(pat, req.text)
            if m:
                facts.append(Fact(id=f"{sid}:F{len(facts) + 1}", source_id=sid, subject=subject, field=field,
                                  value=m.group(0) if value is None else value, span=m.group(0),
                                  extractor="fallback:regex@1", extract_conf=0.6, recorded_at=STATE.clock,
                                  acl_tags=tags))
        message = None
    rehearsed = next((i for i in INJECTIONS if i.request.text.strip() == req.text.strip()), None)
    if rehearsed:
        message = f"stub · expected outcome: {rehearsed.expected}"
    elif message is None and not facts:
        message = "Nothing verifiable found · routed to Ops as a low-confidence question"
    ev = STATE.emit("fact", "agent.reader", f"Read injected {req.kind.replace('_', ' ')} · {len(facts)} facts · "
                    f"{dropped} dropped", "INFO", sid)
    events = [ev]
    if req.flight_id:
        events.append(STATE.emit("decision", "agent.engine", f"Re-decided {req.flight_id.split('@')[0]} · decision "
                                 "unchanged (stub)", "INFO", req.flight_id))
    return InjectResponse(source=src, facts=facts, dropped_unverifiable=dropped, events=events,
                          affected=[req.flight_id] if req.flight_id else [], fallback_used=True, message=message)


@app.post("/api/clock", response_model=ClockResponse, responses=ERRORS)
def set_clock(req: ClockRequest) -> ClockResponse:
    t = req.known_at if req.known_at.tzinfo else req.known_at.replace(tzinfo=UTC)
    if t < STATE.clock:
        raise ApiError(422, "validation", f"The clock only moves forward (now {_iso(STATE.clock)}).")
    STATE.clock = t.astimezone(UTC)
    for q in STATE.questions():
        if q.status == "reminded" and not any(e.kind == "reminder" and e.ref == q.id for e in STATE.trace):
            hours = int((STATE.clock - q.asked_at).total_seconds() // 3600)
            STATE.emit("reminder", "agent.engine", f"Waiting on {label(q.routed_to)} {hours}h · reminder sent",
                       "INFO", q.id)
    return ClockResponse(known_at=STATE.clock)


@app.post("/api/reset", response_model=OkResponse)
def reset() -> OkResponse:
    global STATE
    STATE = StubState()
    return OkResponse(ok=True)


_fastapi_openapi = app.openapi


def _openapi() -> dict[str, Any]:
    """FastAPI types an SSE body as `string`; point it at TraceEvent so generated TS types document the payload."""
    if app.openapi_schema is None:
        schema = _fastapi_openapi()
        ok = schema["paths"]["/api/stream"]["get"]["responses"]["200"]
        ok["content"] = {"text/event-stream": {"schema": {"$ref": "#/components/schemas/TraceEvent"}}}
    return app.openapi_schema


app.openapi = _openapi  # type: ignore[method-assign]


def openapi_json() -> str:
    return json.dumps(app.openapi(), indent=2, ensure_ascii=False) + "\n"
