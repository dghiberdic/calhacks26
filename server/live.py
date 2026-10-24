"""D10c live paths: `POST /api/inject` and `POST /api/flights/{id}/challenge`.

Inject: text → `Source` (trust tier by kind) → Reader (`llm.reader.Reader`, 8 s timeout; its own regex fallback
when the LLM is unavailable) → verified Facts on the trace → the engine re-decides every affected flight (a new
decision commit each time, linked to the facts) → entitlements, Books recode, questions → trace events (SSE).
- `fallback_used` is true only when the Reader timed out or raised (or reported its own fallback) and the regex
  fallback produced the facts.
- Instructions inside a source are data: a prompt-injection email yields 0 facts, and any "approved" in external
  text is checked by the ACL broker and denied (external parties never satisfy an internal approval).
- Email and manufacturer text about a decided flight is a challenge (tier 4 / tier 2): it routes, never flips.
- Claims and CRM lines are checked against the coupon's entitlement and known claims (duplicate, limitation,
  weather, UK261 on an EU departure); a clean owed claim is assessed by Books at face value.
- **Never a 500.** Every stage is guarded: an exception from the Reader, Drafter, engine or Books on user input
  becomes a recorded, low-confidence Ops escalation, and its exception class is committed to the trace.
"""
from __future__ import annotations

import concurrent.futures as cf
import hashlib
import logging
import re
from datetime import date, datetime, timedelta
from typing import TYPE_CHECKING, Any

from contracts.models import (
    ChallengeResponse, Claim, Confidence, Draft, Evidence, Fact, FlightDecision, InjectRequest, InjectResponse,
    Question, Role, Source, SourceKind, TraceEvent,
)

from . import compose
from .impls import _module

if TYPE_CHECKING:
    from .runtime import Runtime

log = logging.getLogger("stormcheck.server")
_POOL = cf.ThreadPoolExecutor(max_workers=4, thread_name_prefix="stormcheck-llm")
MAX_TEXT = 20_000
KIND = {"tech_log": (SourceKind.TECH_LOG, 1, ["maintenance"]), "occ_log": (SourceKind.OCC_LOG, 3, ["ops"]),
        "crm": (SourceKind.CRM, 3, ["pii", "finance"]), "claim": (SourceKind.CLAIM, 4, ["pii"]),
        "email": (SourceKind.EMAIL, 4, ["pii"]), "manufacturer": (SourceKind.MANUFACTURER, 2, ["maintenance"])}
CAUSE_PATTERN = {"knock_on": "knock_on_return", "concurrent": "concurrent_causes", "unknown": "cause_unknown",
                 "crew": "crew", "atc": "atc"}
INJECTION_RE = re.compile(r"ignore (all |any )?(previous|prior) instructions|^\s*SYSTEM\s*:|you are now|"
                          r"disregard the above", re.IGNORECASE | re.MULTILINE)
APPROVED_RE = re.compile(r"\bapprov(?:e|ed|al|es|ing)\b", re.IGNORECASE)
SEAT_RE = re.compile(r"(?:passenger|seat|pax)\s+(\d{1,2}[A-K])\b", re.IGNORECASE)
COUPON_RE = re.compile(r"\b([A-Z]{2}\d{1,4}@\d{4}-\d{2}-\d{2}:\d{1,2}[A-K])\b")
FLIGHT_RE = re.compile(r"\b(NS) ?(\d{1,4})\b")
MONEY_RE = re.compile(r"(€|EUR ?|£|GBP ?)(\d[\d,]*(?:\.\d{1,2})?)", re.IGNORECASE)
DATE_RE = re.compile(r"\b(\d{1,2}) (Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)[a-z]* (\d{4})\b", re.IGNORECASE)
MONTHS = {m: i for i, m in enumerate(("jan", "feb", "mar", "apr", "may", "jun", "jul", "aug", "sep", "oct", "nov",
                                      "dec"), start=1)}
LIMITATION_YEARS = 6        # Ireland (C-139/11 Moré)


def clean_text(text: str) -> tuple[str, bool]:
    """Valid UTF-8, no NULs, at most MAX_TEXT characters (the rest is kept out of the LLM and the trace)."""
    t = (text or "").encode("utf-8", "replace").decode("utf-8", "replace").replace("\x00", "")
    return (t[:MAX_TEXT], True) if len(t) > MAX_TEXT else (t, False)


def timed(fn: Any, timeout_s: float, *args: Any, **kwargs: Any) -> Any:
    """Run `fn` with a hard deadline (the 8 s Reader / Drafter timeout). Raises TimeoutError on the deadline."""
    fut = _POOL.submit(fn, *args, **kwargs)
    try:
        return fut.result(timeout=timeout_s)
    except cf.TimeoutError as exc:
        raise TimeoutError(f"no answer within {timeout_s:.0f} s") from exc


class Live:
    def __init__(self, rt: "Runtime"):
        self.rt = rt

    # ------------------------------------------------------------------ helpers
    def _next(self, kind: str, prefix: str) -> str:
        return f"{prefix}-{len(self.rt.store.keys(kind)) + 1:04d}"

    def _decision(self, fid: str | None) -> FlightDecision | None:
        if not fid:
            return None
        data = self.rt.store.get("decision", fid) or self.rt.store.get("desk_decision", fid)
        return FlightDecision.model_validate(data) if data else None

    def _flight(self, fid: str) -> Any:
        return next((f for f in (self.rt.world.flights if self.rt.world else []) if f.id == fid), None)

    def failure(self, stage: str, exc: BaseException, ref: str) -> None:
        """Commit the exception class (never the payload) so the failure is on the record."""
        cls = type(exc).__name__
        log.warning("inject %s: %s failed: %s: %s", ref, stage, cls, exc)
        self.rt.record("commit", "fact", {"source_id": ref, "stage": stage, "error": cls}, "agent.engine", [],
                       self.rt.now, ref=ref, message=f"{ref} · {stage} failed · {cls} · escalated to Ops")

    def ops_question(self, ref: str, title: str, found: str, events: list[TraceEvent],
                     case_refs: list[str] | None = None, reason_tag: str = "out-of-scope") -> Question:
        rt = self.rt
        q = Question(
            id=self._next("ops_question", "Q-OPS"), case_refs=case_refs or [ref], pattern="unresolved_subject",
            routed_to=Role.OPS, asked_at=rt.now, title=title, found=found[:600],
            why_flagged="The input could not be tied to a flight or settled from the evidence; the engine asks "
                        "instead of guessing.",
            recommends="Ops to identify the flight or coupon and attach the log.",
            recommended_option="Attach the flight / coupon", options=["Attach the flight / coupon", "Not relevant"],
            evidence=[], confidence=Confidence(score=0.3, kind="cause", label="cause-finding confidence",
                                               features={}, caps=["capped:unresolved-subject"],
                                               calibration_version=compose.CAL_VERSION),
            reason_tag=reason_tag, holds=[], holds_cents=0, status="open", remind_at=rt.now + timedelta(hours=3))
        rt.store.put("ops_question", q.id, {"ref": ref}, rt.now)
        self.ask(q, events)
        return q

    def ask(self, q: Question, events: list[TraceEvent]) -> None:
        rt = self.rt
        if rt.store.get("question", q.id) is not None:
            return
        rt.store.put("question", q.id, q, rt.now)
        rt.record("record_question", q, "agent.engine", rt.now, event="asked")
        score = q.confidence.score
        conf = f"confidence {round(score * 100)}%" if score is not None else "uncalibrated"
        events.append(rt.emit("question", "agent.engine", f"Asked {compose.label(q.routed_to)}: {q.title} · {conf} · "
                              f"{q.reason_tag.replace('-', ' ')}", "ASKED", q.id, q.holds_cents or None))

    # ------------------------------------------------------------------ the Reader
    def read(self, source: Source, flight_id: str | None) -> tuple[list[Fact], int, bool, str | None]:
        """(facts, dropped, fallback_used, error class). The Reader's LlmCallRecord, when there is one, is left in
        `self.last_llm` (committed by the caller as an `llm_call` the facts cite)."""
        self.last_llm = None
        rt = self.rt
        reader = rt.impls.reader
        ctx = None
        reader_mod = _module("llm.reader")
        if reader_mod is not None and hasattr(reader_mod, "ReaderContext"):
            f = self._flight(flight_id) if flight_id else None
            try:
                ctx = reader_mod.ReaderContext(
                    flight_id=flight_id if f is not None else None, aircraft=f.aircraft if f is not None else None,
                    flight_ids={x.number: x.id for x in (rt.world.flights if rt.world else [])
                                if f is None or x.date == f.date})
            except Exception:
                ctx = None
        error = None
        if reader is not None:
            try:
                if hasattr(reader, "read") and ctx is not None:
                    res = timed(reader.read, rt.settings.reader_timeout_s, source, ctx)
                    self.last_llm = getattr(res, "record", None)
                    return list(res.facts), int(res.dropped_unverifiable), bool(res.fallback_used), \
                        (res.error or None)
                facts, dropped = timed(reader.extract, rt.settings.reader_timeout_s, source)
                return list(facts), int(dropped), False, None
            except Exception as exc:
                error = type(exc).__name__
                self.failure("reader", exc, source.id)
        fb = rt.impls.fallback_reader
        if fb is not None and fb is not reader:
            try:
                facts, dropped = timed(fb.extract, rt.settings.reader_timeout_s, source)
                return list(facts), int(dropped), True, error
            except Exception as exc:
                self.failure("regex_fallback", exc, source.id)
        return [], 0, error is not None, error

    # ------------------------------------------------------------------ inject
    def inject(self, req: InjectRequest) -> InjectResponse:
        rt = self.rt
        events: list[TraceEvent] = []
        text, truncated = clean_text(req.text)
        kind, tier, tags = KIND.get(req.kind, (SourceKind.EMAIL, 4, ["pii"]))
        sid = self._next("injected_source", "SRC-INJ")
        source = Source(id=sid, kind=kind, title=f"Injected {req.kind.replace('_', ' ')}"
                        + (" (truncated)" if truncated else ""), text=text,
                        sha256=hashlib.sha256(text.encode()).hexdigest(), received_at=rt.now, trust_tier=tier,
                        acl_tags=tags)
        rt.store.put("injected_source", sid, source, rt.now)
        src_c = rt.record("record_source", source, "agent.reader", rt.now)
        if rt.broker is not None and kind in (SourceKind.EMAIL, SourceKind.CLAIM):
            rt.broker.register_sources([source])
        flight_id = req.flight_id if self._decision(req.flight_id) is not None else None
        messages: list[str] = []

        facts, dropped, fallback, error = self.read(source, flight_id)
        if INJECTION_RE.search(text) and facts:
            dropped += len(facts)                 # instructions inside a source are never facts
            facts = []
        llm_hash = rt.commit_llm(self.last_llm)                 # the Reader's call: one llm_call commit
        fact_cs = []
        if facts:
            for f in facts:
                rt.store.put("injected_fact", f.id, {"source": sid}, rt.now)
            fact_cs = rt.record("record_facts", facts, "agent.reader", rt.now,
                                inputs=[x for x in (llm_hash, src_c.hash if src_c else None) if x])
        links = [c.hash for c in (fact_cs or [])] + ([src_c.hash] if src_c else [])
        events.append(rt.emit("fact", "agent.reader", f"Read injected {req.kind.replace('_', ' ')} · {len(facts)} "
                              f"facts · {dropped} dropped" + (" · regex fallback" if fallback else ""),
                              "INFO", sid))
        if INJECTION_RE.search(text):
            messages.append("Instructions inside a source are data, not commands · 0 facts accepted · nothing "
                            "approved")
        if APPROVED_RE.search(text) and rt.broker is not None:
            d = rt.broker.check(source, "approve_payout", flight_id or sid)
            if not d.allowed:
                rt.deny(d.principal, d.action, d.resource, d.reason, committed=True)
                events.append(rt.store.trace(rt.store.last_seq() - 1)[-1])
                messages.append("external parties never satisfy an internal approval")

        affected: list[str] = []
        try:
            if req.kind in ("email", "manufacturer") and flight_id and not INJECTION_RE.search(text):
                affected, msg = self.challenge_input(flight_id, text, events, facts)
                messages.append(msg)
            elif req.kind in ("claim", "crm"):
                affected, msg = self.claim_input(req.kind, text, flight_id, facts, events, sid)
                messages.append(msg)
            elif not INJECTION_RE.search(text):
                affected = self.redecide(self.affected_flights(facts, flight_id), links, events, sid)
                if affected:
                    messages.append(self.decision_summary(affected))
        except Exception as exc:          # belt and braces: never a 500 for user input (non-negotiable 8)
            self.failure("decide", exc, sid)
            self.ops_question(sid, f"Could not process injected {req.kind.replace('_', ' ')} automatically",
                              f"{type(exc).__name__} while deciding; text: {text[:300]}", events)
            messages.append(f"Could not settle this automatically ({type(exc).__name__}) · routed to Ops as a "
                            "low-confidence question")
        if not affected and not messages:
            self.ops_question(sid, f"Which flight does this {req.kind.replace('_', ' ')} concern?",
                              f"Nothing tied this input to a decided flight. Text: {text[:300]}", events)
            messages.append("Nothing verifiable tied to a flight · routed to Ops as a low-confidence question")
        if error and not messages:
            messages.append(f"Reader unavailable ({error}) · regex fallback used")
        return InjectResponse(source=source, facts=facts, dropped_unverifiable=dropped, events=events,
                              affected=affected, fallback_used=fallback, message=" · ".join(m for m in messages if m)
                              or None)

    def affected_flights(self, facts: list[Fact], flight_id: str | None) -> list[str]:
        rt = self.rt
        decided = set(rt.store.keys("decision"))
        out: list[str] = [flight_id] if flight_id in decided else []
        tails: dict[str, list[str]] = {}
        for f in (rt.world.flights if rt.world else []):
            if f.id in decided:
                tails.setdefault(f.aircraft, []).append(f.id)
        for fact in facts:
            kind, _, ident = fact.subject.partition(":")
            if kind == "flight" and ident in decided:
                out.append(ident)
            elif kind == "aircraft":
                cand = tails.get(ident, [])
                if flight_id in cand:
                    continue
                out += cand
            elif kind == "coupon":
                fid = ident.rsplit(":", 1)[0]
                if fid in decided:
                    out.append(fid)
        return list(dict.fromkeys(out))

    def redecide(self, fids: list[str], links: list[str], events: list[TraceEvent], ref: str) -> list[str]:
        """Re-decide with the injected facts overlaid: a new decision commit per flight, changes posted."""
        rt = self.rt
        lc = rt.lifecycle
        if not fids or rt.world is None or not hasattr(rt.trace, "replay_run"):
            return []
        run = lc.replay(rt.rules(), rule_ref=f"inject:{ref}", fids=fids, flight_level=True)
        if run is None:
            return []
        changed = set(run.changed_flights())
        lc.apply(run, actor="agent.engine", link=links[0] if links else None, rule_ref=None,
                 reason=f"injected {ref}")
        for fid in fids:
            after = run.after.get(fid)
            if after is None:
                continue
            if fid not in changed:                     # re-decided all the same: still a new, linked commit
                d = rt.commit_decision(after, "agent.engine", rt.now, inputs=links)
                rt.store.put("decision", fid, d, rt.now)
                lc.refresh_flight(fid)
            d = FlightDecision.model_validate(rt.store.get("decision", fid))
            num = fid.split("@")[0]
            if fid in changed:
                summary = f"Re-decided {num} · {d.cause.value} · {d.extraordinary.value.replace('_', ' ')}" + (
                    f" · held for {compose.label(d.routed_to)}" if d.outcome == "escalated" else "")
                chip = "HELD" if d.outcome == "escalated" else "APPLIED"
            else:
                summary, chip = f"Re-decided {num} · decision unchanged ({d.cause.value})", "INFO"
            events.append(rt.emit("decision", "agent.engine", summary, chip, fid))
            if d.outcome == "escalated" and d.question_id:
                self.ask_for_decision(d, events)
        lc.refresh_runs(set(fids))
        return fids

    def ask_for_decision(self, d: FlightDecision, events: list[TraceEvent]) -> None:
        qm = _module("engine.questions")
        ents = self.rt.lifecycle.ents(d.flight_id)
        pattern = CAUSE_PATTERN.get(d.cause.value, "new_legal_pattern")
        try:
            qs = qm.flight_questions([d], ents, self.rt.now, {d.flight_id: 0}, {d.flight_id: pattern})
        except Exception:
            qs = compose.group_questions(d.flight_id, [d], {d.flight_id: ents}, self.rt.now)
        for q in qs:
            self.ask(q, events)

    def decision_summary(self, fids: list[str]) -> str:
        parts = []
        for fid in fids:
            d = self._decision(fid)
            if d is None:
                continue
            s = f"{fid.split('@')[0]} → {d.cause.value} / {d.extraordinary.value}"
            if d.outcome == "escalated":
                s += f" · routed to {compose.label(d.routed_to)}" + (" (concurrent causes)"
                                                                       if d.cause.value == "concurrent" else "")
            parts.append(s)
        return " · ".join(parts)

    # ------------------------------------------------------------------ challenges (email / manufacturer)
    def challenge_input(self, fid: str, text: str, events: list[TraceEvent], facts: list[Fact]
                        ) -> tuple[list[str], str]:
        resp = self.challenge(fid, text, events=events)
        if resp.classification == "assertion":
            return [fid], resp.reply.text.split(". ")[0] + "."
        if resp.question is not None:
            score = resp.question.confidence.score
            conf = f"confidence {round(score * 100)}%" if score is not None else "uncalibrated"
            what = "New legal pattern (C-549/07 ¶26)" if resp.classification == "new_legal_pattern" else "New fact"
            return [fid], f"{what} · routed to {compose.label(resp.question.routed_to)} at {conf} · decision unchanged"
        return [fid], "Recorded · decision unchanged"

    def challenge(self, fid: str, text: str, *, events: list[TraceEvent] | None = None) -> ChallengeResponse:
        rt = self.rt
        events = events if events is not None else []
        d = self._decision(fid)
        if d is None:
            raise KeyError(fid)
        text, _ = clean_text(text)
        cls, facts = self.classify(d, text)
        verdict = None
        ch = _module("engine.challenge")
        if ch is not None and rt.world is not None:
            try:
                verdict = ch.challenge(rt.world, d, cls, facts, rt.now,
                                       getattr(rt.impls.engine, "calibration", None))
            except Exception as exc:
                self.failure("challenge", exc, fid)
        cited = list(verdict.cited) if verdict is not None else [e for e in d.evidence if e.trust_tier == 1
                                                                 and not e.struck][:4]
        question = verdict.question if verdict is not None else None
        if verdict is None and cls != "assertion":
            question = self.ops_question(fid, f"Verify the challenge to {fid.split('@')[0]}", text, events,
                                         case_refs=[fid], reason_tag="sources-disagree")
        reply = self.reply(d, cls, cited)
        if cls == "assertion" and not reply.text.startswith("Decision stands."):
            reply = reply.model_copy(update={"text": "Decision stands. " + reply.text})
        sid = "SRC-CHALLENGE-" + hashlib.sha256(f"{fid}:{text}".encode()).hexdigest()[:12]
        src = Source(id=sid, kind=SourceKind.CHALLENGE, title=f"Challenge to {fid}", text=text,
                     sha256=hashlib.sha256(text.encode()).hexdigest(), received_at=rt.now, trust_tier=4,
                     acl_tags=["pii"])
        rt.record("record_source", src, "agent.drafter", rt.now)
        if facts:
            rt.record("record_facts", [f.model_copy(update={"recorded_at": rt.now}) for f in facts],
                      "agent.drafter", rt.now)
        if question is not None:
            self.ask(question, events)
        events.append(rt.emit("decision", "agent.engine", f"Challenge on {fid.split('@')[0]} · {cls} · decision "
                              "stands", "INFO", fid))
        return ChallengeResponse(classification=cls, decision_stands=True, reply=reply, cited=cited,
                                 question=question)

    def _drafters(self) -> list[Any]:
        fakes = _module("contracts.fakes")
        fake = fakes.FakeDrafter() if fakes is not None and hasattr(fakes, "FakeDrafter") else None
        out = [x for x in (self.rt.impls.drafter, fake) if x is not None]
        return list(dict.fromkeys(out))

    def classify(self, d: FlightDecision, text: str) -> tuple[str, list[Fact]]:
        for drafter in self._drafters():
            try:
                cls, facts = timed(drafter.classify_challenge, self.rt.settings.reader_timeout_s, d, text)
                if cls in ("assertion", "new_fact", "new_legal_pattern"):
                    self.rt.commit_llm(self.rt.last_record(drafter))     # the classification call, if any
                    return cls, list(facts)
            except Exception as exc:
                self.failure("classify_challenge", exc, d.flight_id)
        return "new_fact", []

    def reply(self, d: FlightDecision, cls: str, cited: list[Evidence]) -> Draft:
        for drafter in self._drafters():
            try:
                out = timed(drafter.challenge_reply, self.rt.settings.reader_timeout_s, d, cls, cited)
                if isinstance(out, Draft):
                    return self.rt.commit_draft(out, drafter)
            except Exception as exc:
                self.failure("challenge_reply", exc, d.flight_id)
        text = (f"Decision stands. {d.reason}" if cls == "assertion" else
                "Routed for review; the decision is unchanged until it is ruled on.")
        return Draft(id=f"DRAFT-CH-{d.flight_id}", kind="challenge_reply", text=text, numbers_verified=True,
                     template_fallback=True)

    # ------------------------------------------------------------------ claims and CRM lines
    def claim_input(self, kind: str, text: str, flight_id: str | None, facts: list[Fact], events: list[TraceEvent],
                    sid: str) -> tuple[list[str], str]:
        rt = self.rt
        coupon = self._coupon_of(text, facts, flight_id)
        fid = coupon.rsplit(":", 1)[0] if coupon else flight_id
        old = self._too_old(text)
        if old is not None and (fid is None or self._decision(fid) is None):
            self.claims_note(sid, f"Claim for a flight on {old.isoformat()}: after the {LIMITATION_YEARS}-year "
                                  "limitation (Ireland, C-139/11)", text, events)
            return [], (f"After limitation (Ireland {LIMITATION_YEARS} years, C-139/11) · no compensation · Claims "
                        "Lead informed")
        d = self._decision(fid)
        if d is None:
            return [], ""
        ents = {e.coupon_id: e for e in rt.lifecycle.ents(fid)}
        ent = ents.get(coupon) if coupon else None
        num = fid.split("@")[0]
        if kind == "crm":
            if ent is not None and ent.refund_already_initiated and re.search(r"chargeback", text, re.I):
                first = next((c for c in (rt.world.crm if rt.world else []) if c.coupon_id == coupon
                              and c.kind in ("refund_initiated", "bsp_refund")), None)
                when = f" {first.at:%d %b}" if first else ""
                self.claims_note(sid, f"Chargeback on {coupon} after a refund already initiated", text, events,
                                 case=coupon)
                return [fid], (f"Refund already initiated{when} · chargeback flagged as duplicate · Claims Lead")
            return self.redecide([fid], [], events, sid), self.decision_summary([fid]) or "Recorded"
        regime = "UK261" if re.search(r"\bUK261\b|£|GBP", text) else "EU261"
        if d.extraordinary.value == "extraordinary":
            what = "EU261 applies to a DUB departure · " if regime == "UK261" else ""
            return [fid], (f"{what}{num} {d.cause.value} · no compensation; refunds and care still due"
                           + (" · paid once, never under both" if regime == "UK261" else ""))
        if ent is None:
            self.claims_note(sid, f"Claim on {num}: which passenger?", text, events, case=fid)
            return [fid], f"Claim on {num} without a seat or coupon · Claims Lead to match the passenger"
        prior = [c for c in (rt.world.claims if rt.world else []) if c.coupon_id == coupon]
        prior += [x for x in rt.store.all("injected_claim") if x.get("coupon") == coupon]
        agency = bool(re.search(r"on behalf|\bLtd\b|agency|power of attorney", text, re.I))
        if prior:
            first = prior[0]
            ch = getattr(first, "channel", None) or first.get("channel", "direct")
            seat = coupon.rsplit(":", 1)[1]
            self.claims_note(sid, f"Second claim for {seat} on {num}", text, events, case=coupon)
            return [fid], (f"Duplicate of the {ch} claim for {seat} · pay once · "
                           f"{'agency' if agency else 'second'} claim held")
        if ent.status in ("held", "needs_ruling"):
            return [fid], f"{coupon} is {ent.status.replace('_', ' ')} · the claim waits for the ruling"
        if ent.status != "owed":
            return [fid], f"{coupon} · {ent.status.replace('_', ' ')} · no compensation"
        amt = self._amount(text)
        claim = Claim(id=f"CLM-INJ-{len(rt.store.keys('injected_claim')) + 1:04d}", coupon_id=coupon,
                      received_at=rt.now, channel="agency" if agency else "direct", agency=None,
                      authority="poa" if re.search(r"power of attorney|\bPOA\b", text, re.I) else None,
                      amount_claimed_cents=amt or ent.compensation_cents, currency_regime=regime, text=text[:2000])
        rt.store.put("injected_claim", claim.id, {"coupon": coupon, "channel": claim.channel}, rt.now)
        jes = []
        if rt.books is not None:
            jes = list(rt.books.post_claim(claim, ent, rt.now))
            rt.commit_journal(jes, "agent.books", rt.now)
        pay = ent.compensation_cents - ent.voucher_offset_cents
        events.append(rt.emit("journal", "agent.books", f"Claim {claim.id} on {num} assessed at face value "
                              f"{compose.eur(pay)} · drafted, pending Claims Lead approval", "DRAFTED", claim.id, pay))
        return [fid], f"Assessed at face value {compose.eur(pay)} ({ent.article}) · drafted, pending Claims Lead approval"

    def claims_note(self, sid: str, title: str, text: str, events: list[TraceEvent], case: str | None = None) -> None:
        q = Question(
            id=self._next("claims_question", "Q-CL"), case_refs=[case or sid], pattern="claim_dispute",
            routed_to=Role.CLAIMS_LEAD, asked_at=self.rt.now, title=title, found=text[:600],
            why_flagged="A claim dispute is the Claims Lead's call; the engine flags it and never pays twice.",
            recommends="Pay once; hold the duplicate.", recommended_option="Pay once; hold the duplicate",
            options=["Pay once; hold the duplicate", "Reject the claim"], evidence=[],
            confidence=Confidence(score=0.45, kind="claim_validity", label="claim-validity confidence", features={},
                                  caps=["uncalibrated"], calibration_version=compose.CAL_VERSION),
            reason_tag="sources-disagree", holds=[case] if case else [], holds_cents=0, status="open",
            remind_at=self.rt.now + timedelta(hours=3))
        self.rt.store.put("claims_question", q.id, {"ref": sid}, self.rt.now)
        self.ask(q, events)

    def _coupon_of(self, text: str, facts: list[Fact], flight_id: str | None) -> str | None:
        m = COUPON_RE.search(text)
        if m:
            return m.group(1)
        for f in facts:
            if f.subject.startswith("coupon:"):
                return f.subject.split(":", 1)[1]
        seat = SEAT_RE.search(text)
        if seat and flight_id:
            return f"{flight_id}:{seat.group(1).upper()}"
        if seat:
            fm = FLIGHT_RE.search(text)
            dm = DATE_RE.search(text)
            if fm and dm:
                try:
                    day = date(int(dm.group(3)), MONTHS[dm.group(2)[:3].lower()], int(dm.group(1)))
                    return f"NS{fm.group(2)}@{day.isoformat()}:{seat.group(1).upper()}"
                except (ValueError, KeyError):
                    return None
        return None

    def _too_old(self, text: str) -> date | None:
        for m in DATE_RE.finditer(text):
            try:
                day = date(int(m.group(3)), MONTHS[m.group(2)[:3].lower()], int(m.group(1)))
            except (ValueError, KeyError):
                continue
            limit = self.rt.now.date().replace(year=self.rt.now.year - LIMITATION_YEARS)
            if day < limit:
                return day
        return None

    @staticmethod
    def _amount(text: str) -> int | None:
        m = MONEY_RE.search(text)
        if not m:
            return None
        try:
            return int(round(float(m.group(2).replace(",", "")) * 100))
        except ValueError:
            return None
