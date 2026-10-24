"""D10b: the full API on the real pipeline (sessions, questions, rulings → rules, books, trace, access).

Signatures (path and query parameter names, defaults, constraints) are copied from `contracts/stub_app.py`, so the
real OpenAPI stays a superset of `contracts/openapi.json`.
"""
from __future__ import annotations

import re
from datetime import UTC, datetime, timedelta
from typing import Any, Callable

from fastapi import FastAPI, Query, Request

from contracts import stub_app as stub
from contracts.models import (
    AccessDecision, AccessMatrix, AnswerRequest, AnswerResponse, Blame, CfoMetrics, ClaimCurve, Commit,
    ConfirmResponse, ControlMapping, EstimateCard, EvalReport, Injection, InvariantResult, JournalEntry,
    LockResponse, MonthEndResponse, PeriodRequest, Question, RejectRequest, ReplayDiff, Role, Rollforward, Rule,
    RuleProposal, Session, SessionRequest, SessionResponse, TraceEvent,
)
from contracts.stub_app import ERRORS, ERRORS_AUTH, ApiError

from . import compose
from .auth import AGENT_ROLES
from .blame import audit as audit_je
from .config import ROOT
from .impls import _module
from .lifecycle import LifecycleError, base_id

SCOPED_ROLES = (Role.CLAIMS_LEAD, Role.LEGAL, Role.CONTROLLER, Role.OPS)
PII_SOURCE_HINTS = ("CLM", "CLAIM", "CRM", "CALLNOTE", "EMAIL", "PNR", "MANIFEST")
PERIOD_RE = re.compile(r"^\d{4}-\d{2}$")
EVAL_PATH = ROOT / "eval" / "proof.json"


def books_error(exc: Exception) -> ApiError:
    code = getattr(exc, "code", None)
    msg = getattr(exc, "message", None) or str(exc)
    if code == "not_found" or isinstance(exc, KeyError):
        return ApiError(404, "not_found", msg)
    if code in ("sod_violation", "forbidden"):
        return ApiError(403, code, msg)
    return ApiError(422, "validation", msg)


def period_end(period: str) -> datetime:
    y, m = (int(x) for x in period.split("-"))
    nxt = datetime(y + (m == 12), 1 if m == 12 else m + 1, 1, tzinfo=UTC)
    return nxt - timedelta(seconds=1)


def install(app: FastAPI, rt: Any) -> None:
    lc = rt.lifecycle

    def sess(request: Request) -> Session:
        return rt.signer.session_of(request.headers.get("authorization"), rt.now)

    def deny(s: Session, action: str, resource: str, code: str, reason: str) -> ApiError:
        rt.deny(s.principal, action, resource, reason)
        return ApiError(403, code, reason)

    def guarded(fn: Callable[[], Any]) -> Any:
        try:
            return fn()
        except LifecycleError as exc:
            raise ApiError(exc.status, exc.code, exc.message) from exc

    def need_books() -> Any:
        if rt.books is None:
            raise ApiError(422, "upstream", "Books is not available on this server.")
        return rt.books

    def stubbed() -> bool:
        """No world (stub pipeline) or no Books: the books screens are served from the stub's fixtures."""
        return rt.pipeline == "stub" or rt.books is None

    # ================================================================ reads
    @app.get("/api/questions", response_model=list[Question])
    def list_questions(request: Request, status: str | None = Query(None, description="open | answered | reminded; "
                                                                    "open also returns reminded (both unanswered)")
                       ) -> list[Question]:
        s = sess(request)
        qs = rt.questions()
        if s.role in SCOPED_ROLES:
            qs = [q for q in qs if q.routed_to == s.role]
        if status == "open":
            qs = [q for q in qs if q.status in ("open", "reminded")]
        elif status:
            qs = [q for q in qs if q.status == status]
        return [redact(rt, q, s) for q in qs]

    @app.get("/api/rules", response_model=list[Rule])
    def list_rules() -> list[Rule]:
        return lc.rules_view()

    @app.get("/api/trace", response_model=list[TraceEvent])
    def get_trace(since: int = Query(0, ge=0)) -> list[TraceEvent]:
        return rt.store.trace(since)

    @app.get("/api/commits", response_model=list[Commit])
    def list_commits(limit: int = Query(100, ge=1, le=1000)) -> list[Commit]:
        return list(rt.trace.log(limit))

    @app.get("/api/blame", response_model=Blame, responses=ERRORS)
    def blame(request: Request, target: str = Query(..., description="any id: JE line, entitlement, coupon, flight, "
                                                                     "rule")) -> Blame:
        return rt.blamer.blame(target, sess(request))

    @app.get("/api/audit/{je_id}", response_model=dict[str, Any], responses=ERRORS)
    def audit(je_id: str) -> dict[str, Any]:
        if stubbed():
            return stub.audit(je_id)
        out = audit_je(rt, je_id)
        if out is None:
            raise ApiError(404, "not_found", f"No journal entry {je_id}.")
        return out

    @app.get("/api/books/rollforward", response_model=Rollforward)
    def rollforward(period: str = Query("2025-02", pattern=r"^\d{4}-\d{2}$")) -> Rollforward:
        if stubbed():
            return stub.rollforward(period)
        try:
            return need_books().rollforward(period)
        except ApiError:
            raise
        except Exception as exc:
            raise books_error(exc) from exc

    @app.get("/api/books/estimate", response_model=EstimateCard, responses=ERRORS)
    def estimate(cohort: str = Query(stub.STORM_ID)) -> EstimateCard:
        if stubbed():
            return stub.estimate(cohort)
        try:
            return need_books().estimate_card(cohort, rt.now)
        except ApiError:
            raise
        except Exception as exc:
            raise books_error(exc) from exc

    @app.get("/api/books/journal", response_model=list[JournalEntry])
    def journal(period: str | None = Query(None), status: str | None = Query(None)) -> list[JournalEntry]:
        if period and not PERIOD_RE.match(period):
            raise ApiError(422, "validation", f"period must look like 2025-02, got {period!r}.")
        if stubbed():
            return stub.journal(period, status)
        try:
            return need_books().journal(period, status)
        except ApiError:
            raise
        except Exception as exc:
            raise books_error(exc) from exc

    @app.get("/api/books/curve", response_model=ClaimCurve, responses=ERRORS)
    def curve(segment: str = Query("long_haul_gt3500",
                                   description="long_haul_gt3500 | medium_1500_3500 | short_le1500")) -> ClaimCurve:
        if stubbed():
            return stub.curve(segment)
        try:
            return need_books().curve(segment)
        except ApiError:
            raise
        except Exception as exc:
            raise ApiError(422, "validation", f"Unknown segment {segment}. Use one of: long_haul_gt3500, "
                                              "medium_1500_3500, short_le1500.") from exc

    @app.get("/api/books/cfo", response_model=CfoMetrics)
    def cfo() -> CfoMetrics:
        if stubbed():
            return stub.cfo()
        try:
            return need_books().cfo_metrics(rt.now)
        except ApiError:
            raise
        except Exception as exc:
            raise books_error(exc) from exc

    @app.get("/api/books/invariants", response_model=list[InvariantResult])
    def invariants() -> list[InvariantResult]:
        if stubbed():
            return stub.invariants()
        try:
            out = list(need_books().invariants())
        except ApiError:
            raise
        except Exception as exc:
            raise books_error(exc) from exc
        verify = getattr(rt.trace, "verify", None)
        if verify is not None:
            v = verify()
            out.append(InvariantResult(id="INV-T1", description="Commit hash chain verifies (engine.trace)",
                                       ok=bool(v.ok), detail=v.summary()))
        return out

    @app.get("/api/access/matrix", response_model=AccessMatrix)
    def access_matrix() -> AccessMatrix:
        acl = _module("engine.acl")
        fn = (getattr(acl, "access_matrix", None) or getattr(acl, "matrix", None)) if acl else None
        if fn is not None:
            try:
                out = fn()
                if isinstance(out, AccessMatrix):
                    return out
            except Exception:
                pass
        return stub.ACCESS_MATRIX

    @app.get("/api/access/log", response_model=list[AccessDecision])
    def access_log() -> list[AccessDecision]:
        return rt.store.access_log()

    @app.get("/api/controls", response_model=list[ControlMapping])
    def controls() -> list[ControlMapping]:
        return stub.CONTROLS

    @app.get("/api/injections", response_model=list[Injection])
    def injections() -> list[Injection]:
        return stub.INJECTIONS

    @app.get("/api/eval", response_model=EvalReport)
    def eval_report() -> EvalReport:
        if EVAL_PATH.exists():
            try:
                return EvalReport.model_validate_json(EVAL_PATH.read_bytes())
            except Exception:
                pass
        return stub.EVAL

    # ================================================================ writes
    @app.post("/api/session", response_model=SessionResponse, responses=ERRORS)
    def create_session(req: SessionRequest) -> SessionResponse:
        token, s = rt.signer.issue(req.role, req.name, rt.now)
        rt.allow(s.principal, "session", s.role.value, f"token issued ({rt.signer.kind})")
        return SessionResponse(token=token, session=s)

    @app.post("/api/questions/{question_id}/answer", response_model=AnswerResponse, responses=ERRORS_AUTH)
    def answer(question_id: str, req: AnswerRequest, request: Request) -> AnswerResponse:
        q = next((x for x in rt.questions() if x.id == question_id), None)
        if q is None:
            raise ApiError(404, "not_found", f"No question {question_id}.")
        s = sess(request)
        if s.role != q.routed_to:
            raise deny(s, "answer", question_id, "forbidden",
                       f"{question_id} is routed to {compose.label(q.routed_to)}; sign in as that role to answer")
        with rt.lock:
            prior = rt.store.get("ruling_for", question_id)
            if prior is not None:
                from contracts.models import Ruling
                ruling = Ruling.model_validate(rt.store.get("ruling", prior["ruling_id"]))
                return AnswerResponse(ruling=ruling, proposal=next(
                    (lc.proposal(r) for r in rt.store.keys("proposal")
                     if (lc.proposal(r) and lc.proposal(r).rule.origin_ruling_id == ruling.id)), None))
            ruling, proposal = guarded(lambda: lc.answer(q, s.role, s.name, s.principal, req.decision,
                                                         req.explanation))
        return AnswerResponse(ruling=ruling, proposal=proposal)

    @app.post("/api/proposals/{rule_id}/confirm", response_model=ConfirmResponse, responses=ERRORS_AUTH)
    def confirm(rule_id: str, request: Request) -> ConfirmResponse:
        s = sess(request)
        with rt.lock:
            p = lc.proposal(rule_id) or guarded(lambda: lc.canned_for(base_id(rule_id)))
            if p is not None and s.role != p.rule.authority_required:
                raise deny(s, "confirm_rule", rule_id, "forbidden",
                           f"{base_id(rule_id)} automates {compose.label(p.rule.authority_required)} authority; only "
                           f"the {compose.label(p.rule.authority_required)} can confirm it")
            rule, diff = guarded(lambda: lc.confirm(rule_id, s.principal))
        return ConfirmResponse(rule=rule, replay=diff)

    @app.post("/api/rules/{rule_id}/reject", response_model=AnswerResponse, responses=ERRORS_AUTH)
    def reject(rule_id: str, req: RejectRequest, request: Request) -> AnswerResponse:
        s = sess(request)
        target = lc.rules().get(base_id(rule_id)) or (p.rule if (p := lc.proposal(rule_id)) else None)
        need = target.authority_required if target is not None else Role.CONTROLLER
        if s.role in AGENT_ROLES or s.role in (Role.JUDGE,) or (target is not None and s.role != need
                                                                 and s.role != Role.CONTROLLER):
            raise deny(s, "reject_rule", rule_id, "forbidden",
                       f"only the {compose.label(need)} can reject {base_id(rule_id)}")
        with rt.lock:
            ruling, proposal = guarded(lambda: lc.reject(rule_id, s.role, s.name, s.principal, req.explanation))
        return AnswerResponse(ruling=ruling, proposal=proposal)

    @app.post("/api/rules/{rule_id}/widen", response_model=RuleProposal, responses=ERRORS)
    def widen(rule_id: str) -> RuleProposal:
        with rt.lock:
            return guarded(lambda: lc.widen(rule_id))

    @app.post("/api/rules/{rule_id}/revert", response_model=ReplayDiff, responses=ERRORS)
    def revert(rule_id: str, request: Request) -> ReplayDiff:
        s = sess(request)
        rule = lc.rules().get(base_id(rule_id))
        if rule is not None and s.role not in (rule.authority_required, Role.CONTROLLER):
            raise deny(s, "revert_rule", rule_id, "forbidden",
                       f"only the {compose.label(rule.authority_required)} can revert {rule.id}")
        with rt.lock:
            return guarded(lambda: lc.revert(rule_id, s.principal))

    @app.post("/api/books/journal/{je_id}/approve", response_model=JournalEntry, responses=ERRORS_AUTH)
    def approve(je_id: str, request: Request) -> JournalEntry:
        if stubbed():
            return stub.approve(je_id, request)
        need_books()
        return approve_je(rt, sess(request), je_id)

    @app.post("/api/books/month-end", response_model=MonthEndResponse, responses=ERRORS_AUTH)
    def month_end(req: PeriodRequest) -> MonthEndResponse:
        if not PERIOD_RE.match(req.period):
            raise ApiError(422, "validation", f"period must look like 2025-02, got {req.period!r}.")
        if stubbed():
            return stub.month_end(req)
        books = need_books()
        if req.period in (books.locked_periods() if hasattr(books, "locked_periods") else []):
            raise ApiError(403, "forbidden", f"Period {req.period} is locked; nothing is written to it.")
        with rt.lock:
            end = period_end(req.period)
            if rt.now < end:
                rt.advance(end, "month-end")
            try:
                entries = list(books.month_end(req.period, rt.now))
                rf = books.rollforward(req.period)
                est = books.estimate_card(primary_cohort(rt), rt.now)
            except Exception as exc:
                raise books_error(exc) from exc
            for je in rt.commit_journal(entries, "agent.books", rt.now):
                amt = sum(line.cr_cents - line.dr_cents for line in je.lines if line.account == "2140")
                rt.emit("journal", "agent.books", f"Month end {req.period} · drafted {je.id} · "
                        f"{'+' if amt >= 0 else '−'}{compose.eur(abs(amt))} change in estimate · Controller "
                        "approval required", "DRAFTED", je.id, amt)
            lc.refresh_runs()
        return MonthEndResponse(entries=entries, rollforward=rf, estimate=est)

    @app.post("/api/books/lock", response_model=LockResponse, responses=ERRORS_AUTH)
    def lock(req: PeriodRequest, request: Request) -> LockResponse:
        if not PERIOD_RE.match(req.period):
            raise ApiError(422, "validation", f"period must look like 2025-01, got {req.period!r}.")
        if stubbed():
            return stub.lock(req, request)
        books = need_books()
        s = sess(request)
        with rt.lock:
            access_check(s, "lock_period", req.period)
            try:
                books.lock_period(req.period, s)
            except Exception as exc:
                err = books_error(exc)
                if err.status == 403:
                    rt.deny(s.principal, "lock_period", req.period, err.message)
                raise err from exc
            rt.record("record_period_lock", req.period, s.principal, rt.now)   # the IAS 8 test needs the real time
            rt.emit("info", s.principal, f"Period {req.period} locked", "LOCKED", req.period)
        return LockResponse(locked=req.period)

    def access_check(s: Session, action: str, resource: str, *, preparer: str | None = None) -> None:
        check_approval(rt, s, action, resource, preparer=preparer)


def is_persona(principal: str | None) -> bool:
    personas = _module("llm.personas")
    fn = getattr(personas, "is_persona", None) if personas is not None else None
    if fn is not None:
        return bool(fn(principal))
    return bool(principal) and str(principal).startswith("persona:")


def check_approval(rt: Any, s: Session, action: str, resource: str, *, preparer: str | None = None) -> None:
    """`engine.acl.Broker.check`: agents never approve, only signed internal sessions approve, preparer ≠ approver,
    payouts need the Claims Lead, JEs and locks the Controller; a simulated person (`persona:<role>`) never
    satisfies an approval. The broker commits each denial; the server logs and streams it."""
    if is_persona(s.principal):
        rt.deny(s.principal, action, resource, "External: a simulated persona never satisfies an internal approval")
        raise ApiError(403, "sod_violation", "A simulated persona never approves or pays.")
    broker = rt.broker
    if broker is None:
        if s.role == Role.JUDGE or s.role in AGENT_ROLES:
            code = "sod_violation" if s.role in AGENT_ROLES else "forbidden"
            reason = "SoD: agents never approve" if s.role in AGENT_ROLES else "Judge sessions are read-only"
            rt.deny(s.principal, action, resource, reason)
            raise ApiError(403, code, reason)
        return
    d = broker.check(s, action, resource, preparer=preparer)
    if not d.allowed:
        rt.deny(d.principal, d.action, d.resource, d.reason, committed=True)
        code = "forbidden" if s.role == Role.JUDGE or action == "lock_period" else "sod_violation"
        raise ApiError(403, code, d.reason)


def approve_je(rt: Any, s: Session, je_id: str) -> JournalEntry:
    """Approve a parked journal (JEs: Controller; claim approvals and payouts: Claims Lead). Never posts."""
    books = rt.books
    try:
        head = books.journal_entry(je_id)
    except Exception as exc:
        raise books_error(exc) from exc
    action = "approve_payout" if head.kind in ("claim_approved", "claim_paid") else "approve_je"
    with rt.lock:
        check_approval(rt, s, action, je_id, preparer=head.preparer)
        try:
            je = books.approve(je_id, s)          # Books enforces the same controls again (defence in depth)
        except Exception as exc:
            err = books_error(exc)
            if err.status == 403:
                rt.deny(s.principal, action, je_id, err.message)
            raise err from exc
        rt.allow(s.principal, action, je_id, "approved · parked, not posted")
        rt.commit_journal([je], s.principal, rt.now, event="approved")
        rt.emit("journal", s.principal, f"{je.id} approved by {compose.label(s.role)} · parked, not posted",
                "APPLIED", je.id, sum(line.dr_cents for line in je.lines))
        for fid in {line.dims.get("flight") for line in je.lines} - {None}:
            rt.lifecycle.refresh_flight(fid)
    return je


def primary_cohort(rt: Any) -> str:
    keys = rt.store.keys("storm_run")
    return keys[0] if keys else stub.STORM_ID


def redact(rt: Any, q: Question, viewer: Session) -> Question:
    """Escalation packets are redacted per recipient (`acl.Broker.packet`): only PII readers see passenger data."""
    if rt.broker is not None:
        try:
            return rt.broker.packet(viewer, q, purpose=q.id)
        except Exception:
            pass
    if viewer.role == Role.CLAIMS_LEAD:
        return q
    ev = [e.model_copy(update={"quote": "[redacted:pii]"}) if e.quote and any(h in e.source_id.upper()
                                                                              for h in PII_SOURCE_HINTS) else e
          for e in q.evidence]
    return q.model_copy(update={"evidence": ev})

