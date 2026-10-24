"""Fakes for every cross-thread interface (CONTRACTS §2): FakeWorld, FakeReader, FakeDrafter, FakeBooks, FakeEngine.

Deterministic, offline, and built only on contracts/ (golden world, expected/, normalize, parse, calibration):
- FakeWorld: the golden world; METAR from it; `generate_day` only for the golden storm days (else WorldError).
- FakeReader: regex extraction; every fact is span-verified and re-parsed with contracts/parse.py.
- FakeDrafter: templates; `propose_rule` drafts the plan's R-CL-1 / R-LEG-1 / R-CTL-1 from rulings.
- FakeBooks: a small in-memory ledger at the segment rates (35/27/20%), BF month end, SoD.
- FakeEngine: decisions from golden `expected/decisions.json` (by construction of the world), evidence from
  normalize facts, a simple Art. 7 calculator, questions per pattern, and a StormRun.

Selection is by env (`*_IMPL=fake|real`, see `impl()`); the server decides what "real" means.
"""
from __future__ import annotations

import hashlib
import json
import math
import os
import re
from collections import Counter, defaultdict
from collections.abc import Iterable, Sequence
from datetime import UTC, date, datetime, timedelta
from fractions import Fraction
from pathlib import Path
from typing import Any

import orjson

from . import calibration as _cal
from .models import (
    Airport, CfoMetrics, Claim, ClaimCurve, Confidence, Draft, Entitlement, Evidence, Extraordinary, Fact,
    FlightDecision, FlightRow, InvariantResult, JournalEntry, JournalLine, LearnedItem, MetarObs, Question,
    ReplayDiff, ReplayFlip, Role, Rollforward, RollforwardRow, Rule, RuleAction, RuleProposal, Ruling, Session,
    Source, StormRun, StormWindow, TraceEvent, World, EstimateCard,
)
from .normalize import world_to_facts
from .parse import ParseError, parse_aog, parse_ata, parse_eur, parse_mel_relief, parse_money, parse_tail, verify

GOLDEN = Path(__file__).resolve().parent / "fixtures" / "golden"
WORLD_PATH = GOLDEN / "world.json"
EXPECTED = GOLDEN / "expected"
CAL_VERSION_FAKE = "fake"

try:  # world/ owns WorldError (Filip); keep the fakes importable without it
    from world.errors import WorldError  # type: ignore
except Exception:  # pragma: no cover
    class WorldError(Exception):  # type: ignore[no-redef]
        def __init__(self, code: str, message: str) -> None:
            super().__init__(f"{code}: {message}")
            self.code, self.message = code, message


class FakeSoDViolation(PermissionError):
    code = "sod_violation"


class FakeForbidden(PermissionError):
    code = "forbidden"


class FakePeriodLocked(PermissionError):
    code = "forbidden"


def impl(api: str) -> str:
    """`fake` or `real` for READER/DRAFTER/BOOKS/WORLD/ENGINE (env `<API>_IMPL`, default fake)."""
    v = os.environ.get(f"{api.upper()}_IMPL", "fake").strip().lower()
    return v if v in ("fake", "real") else "fake"


def canon_hash(obj: Any) -> str:
    if hasattr(obj, "model_dump"):
        obj = obj.model_dump(mode="json")
    return hashlib.sha256(orjson.dumps(obj, option=orjson.OPT_SORT_KEYS)).hexdigest()


def _iso(t: datetime) -> str:
    return t.astimezone(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")


def _hhmm(t: datetime) -> str:
    return t.strftime("%H:%MZ")


def _eur(cents: int) -> str:
    return f"€{cents / 100:,.0f}" if cents % 100 == 0 else f"€{cents / 100:,.2f}"


_GOLDEN_CACHE: dict[str, World] = {}


def golden_world(path: str | Path = WORLD_PATH) -> World:
    key = str(path)
    if key not in _GOLDEN_CACHE:
        _GOLDEN_CACHE[key] = World.model_validate_json(Path(path).read_text(encoding="utf-8"))
    return _GOLDEN_CACHE[key]


def _expected(name: str) -> dict[str, Any]:
    return json.loads((EXPECTED / name).read_text(encoding="utf-8"))


# ================================================================ reference timeline (plan §1.2 binding definition)
def is_storm_obs(o: MetarObs) -> bool:
    wx = o.wxcodes or ""
    return ((o.gust or 0) >= 35 or (o.sknt or 0) >= 30 or (o.vsby_sm is not None and o.vsby_sm < 0.5)
            or any(c in wx for c in ("SN", "FZ", "TS", "GR")))


def storm_windows(obs: Sequence[MetarObs]) -> list[StormWindow]:
    hits = sorted((o for o in obs if is_storm_obs(o)), key=lambda o: o.valid)
    groups: list[list[MetarObs]] = []
    for o in hits:
        if groups and o.valid - groups[-1][-1].valid < timedelta(hours=2):
            groups[-1].append(o)
        else:
            groups.append([o])
    return [StormWindow(station=g[0].station, start=g[0].valid, end=g[-1].valid,
                        peak_gust_kt=max((o.gust or o.sknt or 0) for o in g), obs_count=len(g)) for g in groups]


def station_obs(world: World, icao: str) -> list[MetarObs]:
    seen, out = set(), []
    for k in sorted(world.metar):
        if k.startswith(icao + "@"):
            for o in world.metar[k]:
                if (o.valid, o.raw) not in seen:
                    seen.add((o.valid, o.raw))
                    out.append(o)
    return sorted(out, key=lambda o: o.valid)


def position(t: datetime, obs: Sequence[MetarObs], windows: Sequence[StormWindow]) -> tuple[str, int | None]:
    """(in|out|unknown, signed margin in minutes: negative inside, positive outside)."""
    if not any(abs(o.valid - t) <= timedelta(minutes=60) for o in obs):
        return "unknown", None
    if not windows:
        return "out", None
    for w in windows:
        if w.start <= t <= w.end:
            return "in", -int(min(t - w.start, w.end - t).total_seconds() // 60)
    return "out", int(min(min(abs(t - w.start), abs(t - w.end)) for w in windows).total_seconds() // 60)


def _icao(world: World, iata: str) -> str:
    for a in world.airports:
        if a.iata == iata:
            return a.icao
    return iata


def _airport(world: World, code: str) -> Airport | None:
    for a in world.airports:
        if code in (a.iata, a.icao):
            return a
    return None


def distance_km(world: World, a: str, b: str) -> float:
    table = world.meta.get("distances_km", {}) if isinstance(world.meta, dict) else {}
    for k in (f"{a}-{b}", f"{b}-{a}"):
        if k in table:
            return float(table[k])
    pa, pb = _airport(world, a), _airport(world, b)
    if pa is None or pb is None:
        raise WorldError("unknown_airport", f"I don't know the airport {a if pa is None else b}.")
    p1, p2 = math.radians(pa.lat), math.radians(pb.lat)
    h = math.sin((p2 - p1) / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(math.radians(pb.lon - pa.lon) / 2) ** 2
    return round(2 * 6371 * math.asin(math.sqrt(h)), 1)


# ================================================================ FakeWorld
class FakeWorld:
    """WorldAPI over the golden world."""

    def __init__(self, path: str | Path = WORLD_PATH):
        self.path = Path(path)

    def load(self, path: str | None = None) -> World:
        return golden_world(path or self.path)

    def fetch_metar(self, icao: str, start: datetime, end: datetime) -> list[MetarObs]:
        obs = [o for o in station_obs(self.load(), icao.upper()) if start <= o.valid < end]
        if not obs:
            raise WorldError("no_metar", f"No METAR for {icao.upper()} between {_iso(start)} and {_iso(end)}.")
        return obs

    def generate_day(self, icao: str, local_day: date, seed: int = 0) -> World:
        w = self.load()
        storm = f"{icao.upper()}@{local_day.isoformat()}"
        if storm in (w.meta.get("storms") or {}):
            return w
        if _airport(w, icao.upper()) is None:
            raise WorldError("unknown_airport", f"I don't know the airport {icao.upper()} (FakeWorld: golden only).")
        raise WorldError("no_metar", f"FakeWorld only has the golden storm days; nothing pinned for {storm}.")

    def airport(self, code: str) -> Airport:
        a = _airport(self.load(), code.upper())
        if a is None:
            raise WorldError("unknown_airport", f"I don't know the airport {code}.")
        return a

    def distance_km(self, a: str, b: str) -> float:
        return distance_km(self.load(), a, b)


# ================================================================ FakeReader (regex fallback, span-verified)
INJECTION_RE = re.compile(r"ignore (all |any )?(previous|prior) instructions|^\s*SYSTEM\s*:|<!--\s*assistant|"
                          r"you are now|disregard the above", re.IGNORECASE | re.MULTILINE)
_COUPON_RE = re.compile(r"\b(NS\d{1,4}@\d{4}-\d{2}-\d{2}:\d{1,2}[A-K])\b")
_SEAT_RE = re.compile(r"(?:seat|passenger)\s+(\d{1,2}[A-K])\b", re.IGNORECASE)
_FLIGHT_RE = re.compile(r"\b(NS ?\d{1,4})\b")
_AMOS_RE = re.compile(r"\b\d{2}(?:JAN|FEB|MAR|APR|MAY|JUN|JUL|AUG|SEP|OCT|NOV|DEC) \d{2}:\d{2}Z")


class FakeReader:
    """ReaderAPI: regex extraction (`fallback:regex@1`). Returns (facts, dropped_unverifiable)."""

    extractor = "fallback:regex@1"

    def __init__(self, clock: Any = None):
        self.clock = clock

    def _fact(self, source: Source, subject: str, field: str, value: Any, span: str, n: int) -> Fact:
        return Fact(id=f"F:{source.id}:{field}:{n}", source_id=source.id, subject=subject, field=field, value=value,
                    span=span, extractor=self.extractor, extract_conf=0.6, valid_at=None,
                    recorded_at=source.received_at, acl_tags=list(source.acl_tags))

    def extract(self, source: Source) -> tuple[list[Fact], int]:
        text = source.text or ""
        if not text.strip():
            return [], 0
        if INJECTION_RE.search(text):
            return [], 1                         # instructions in data are never facts
        cands: list[tuple[str, str, Any, str]] = []   # (subject, field, value, span)
        ref = source.received_at
        kind = source.kind.value
        tail = None
        try:
            tail = parse_tail(text)
        except ParseError:
            pass
        flight = _FLIGHT_RE.search(text)
        coupon = _COUPON_RE.search(text)
        if kind in ("tech_log", "mcc_log", "manufacturer") and tail:
            subj = f"aircraft:{tail}"
            cands.append((subj, "aog.tail", tail, tail))
            m = _AMOS_RE.search(text)
            if m and kind == "tech_log":
                from .parse import parse_time
                cands.append((subj, "aog.logged_at", _iso(parse_time(m.group(0), ref)), m.group(0)))
            for rx, field, fn in ((r"ATA ?\d{2}-?\d{2}", "aog.ata_chapter", parse_ata),
                                  (r"NO MEL RELIEF|MEL [\d-]+ CAT [A-D]( DEFERRED)?", "aog.mel_relief", parse_mel_relief),
                                  (r"A/C AOG|\bAOG\b", "aog.aog", parse_aog)):
                m = re.search(rx, text)
                if m:
                    try:
                        cands.append((subj, field, fn(m.group(0)), m.group(0)))
                    except ParseError:
                        pass
            m = re.search(r"hidden (manufacturing )?defect", text, re.IGNORECASE)
            if m:
                cands.append((subj, "manufacturer.hidden_defect", True, m.group(0)))
        if kind in ("claim", "email", "crm", "bsp"):
            if re.search(r"\bapproved\b", text, re.IGNORECASE):
                m = re.search(r"[^.\n]*\bapproved\b[^.\n]*", text, re.IGNORECASE)
                cands.append((f"source:{source.id}", "email.asserts_approval", True, m.group(0).strip()))
            for m in re.finditer(r"(€|£|EUR|GBP)\s?\d[\d,.]*", text):
                try:
                    cents, cur = parse_money(m.group(0))
                except ParseError:
                    continue
                span = m.group(0).rstrip(".,")
                if kind == "crm" and re.search(r"chargeback", text, re.IGNORECASE):
                    cands.append((f"coupon:{coupon.group(1)}" if coupon else f"source:{source.id}", "crm.chargeback",
                                  parse_eur(span) if cur == "EUR" else cents, span))
                elif cur == "GBP":
                    cands.append((f"claim:{source.id}", "claim.amount_claimed_gbp_pence", cents, span))
                elif kind == "claim":
                    cands.append((f"claim:{source.id}", "claim.amount_claimed_cents", cents, span))
                break
            if kind == "claim":
                if flight:
                    cands.append((f"claim:{source.id}", "claim.flight_number", flight.group(1).replace(" ", ""),
                                  flight.group(1)))
                m = _SEAT_RE.search(text)
                if m:
                    cands.append((f"claim:{source.id}", "claim.seat", m.group(1).upper(), m.group(1)))
                m = re.search(r"\bUK ?261\b", text)
                if m:
                    cands.append((f"claim:{source.id}", "claim.regime", "UK261", m.group(0)))
                m = re.search(r"power of attorney|on behalf of", text, re.IGNORECASE)
                if m:
                    cands.append((f"claim:{source.id}", "claim.channel", "agency", m.group(0)))
                m = re.search(r"I never agreed[^.]*", text, re.IGNORECASE)
                if m:
                    cands.append((f"claim:{source.id}", "claim.voucher_disputed", True, m.group(0)))
        if kind == "occ_log":
            for m in re.finditer(r"(NS\d{1,4})[^.]*?RSN (\d{2})", text):
                cands.append((f"flight:{m.group(1)}", "flight.ops_cause_code", m.group(2), f"RSN {m.group(2)}"))
        facts, dropped = [], 0
        for n, (subj, field, value, span) in enumerate(cands):
            ok, _why = verify(field, value, span, text, ref)
            if ok:
                facts.append(self._fact(source, subj, field, value, span, n))
            else:
                dropped += 1
        return facts, dropped


# ================================================================ FakeDrafter (templates)
LEGAL_BASIS = {
    "weather": ["EU261 Art.5(3)", "EU261 Recital 14", "CJEU C-549/07"],
    "technical": ["EU261 Art.5(3)", "CJEU C-549/07", "CJEU C-257/14"],
    "knock_on": ["EU261 Art.5(3)", "CJEU C-74/19", "CJEU C-549/07"],
    "concurrent": ["EU261 Art.5(3)", "CJEU C-549/07", "CJEU C-74/19"],
    "unknown": ["EU261 Art.5(3)"],
}


class FakeDrafter:
    """DrafterAPI: deterministic templates (`template_fallback=True`)."""

    def _draft(self, kind: str, key: str, text: str) -> Draft:
        return Draft(id=f"DRAFT-{key}-{kind}", kind=kind, text=text, numbers_verified=True, llm_commit=None,
                     template_fallback=True)

    def explain(self, decision: FlightDecision) -> Draft:
        basis = ", ".join(decision.legal_basis)
        return self._draft("explanation", decision.flight_id,
                           f"{decision.reason} Basis: {basis}. {decision.confidence.label} "
                           f"{round((decision.confidence.score or 0) * 100)}%.")

    def rights_notice(self, ent: Entitlement) -> Draft:
        if ent.compensation_cents and ent.status in ("owed", "needs_ruling"):
            amount = _eur(ent.compensation_cents - ent.voucher_offset_cents)
            body = (f"You are entitled to {amount} compensation under Article 7 of Regulation (EC) 261/2004 for the "
                    f"cancellation of your flight, payable in cash or by bank transfer.")
        else:
            body = ("Your flight was cancelled due to extraordinary circumstances (Article 5(3)), so no compensation "
                    "is payable. You remain entitled to a refund or rerouting (Article 8) and to care (Article 9).")
        return self._draft("rights_notice", ent.coupon_id,
                           f"Dear {{{{name}}}},\n\n{body}\n\nThis notice is given under Article 14(2).\n\nNorthstar Air")

    def je_memo(self, je: JournalEntry) -> Draft:
        total = sum(line.dr_cents for line in je.lines)
        return self._draft("je_memo", je.id, f"{je.memo} · {_eur(total)} · {je.kind.replace('_', ' ')} · "
                                             "drafted, pending approval")

    def propose_rule(self, ruling: Ruling, question: Question, case_facts: list[Fact]) -> Rule:
        at = ruling.at
        if question.pattern == "voucher_in_lieu_unsigned":
            return Rule(id="R-CL-1", version=1, kind="voucher",
                        scope={"voucher.in_lieu": True, "voucher.signed": False, "flight.departs_eu": "case:true"},
                        condition={"all": [{"f": "voucher.in_lieu", "op": "eq", "v": True},
                                           {"f": "voucher.signed", "op": "eq", "v": False}]},
                        action=RuleAction.DENY_OFFSET, tier="claims_lead_ruling", authority_required=Role.CLAIMS_LEAD,
                        origin_ruling_id=ruling.id, origin_example=question.case_refs[0] if question.case_refs else None,
                        grounding={"True": "voucher", "False": "No signed acceptance"},
                        valid_from=at, recorded_at=at, status="proposed",
                        title="No signed acceptance, no offset: pay the compensation in cash; the voucher stays goodwill")
        if question.pattern == "knock_on_return":
            return Rule(id="R-LEG-1", version=1, kind="cause",
                        scope={"flight.is_return_sector": True, "rotation.prev_cancelled": True},
                        condition={"all": [{"f": "flight.is_return_sector", "op": "eq", "v": True},
                                           {"f": "rotation.prev_cancelled", "op": "eq", "v": True},
                                           {"f": "spare.available_within_h", "op": "gt", "v": 3},
                                           {"f": "pax.reroute_earliest_offered", "op": "eq", "v": True}]},
                        action=RuleAction.SET_EXTRAORDINARY, tier="legal_ruling", authority_required=Role.LEGAL,
                        origin_ruling_id=ruling.id, origin_example=",".join(question.case_refs),
                        grounding={"True": "return sector of a storm-cancelled rotation", "3": "within 3 h of STD"},
                        valid_from=None, recorded_at=at, status="proposed",
                        title="A storm-cancelled rotation's return is extraordinary only if no aircraft within 3 h and "
                              "the earliest reroute was offered (C-74/19)")
        if question.pattern == "cohort_release":
            return Rule(id="R-CTL-1", version=1, kind="release", scope={"cohort": f"case:{question.case_refs[0]}"},
                        condition={"all": [{"f": "cohort.age_months", "op": "ge", "v": 12},
                                           {"f": "cohort.limitation_expired", "op": "eq", "v": False}]},
                        action=RuleAction.KEEP_TAIL, tier="controller_ruling", authority_required=Role.CONTROLLER,
                        origin_ruling_id=ruling.id, origin_example=question.case_refs[0],
                        grounding={"12": "At M12", "False": "until the six-year limitation"},
                        valid_from=at, recorded_at=at, status="proposed",
                        title="Never release the tail: keep (ultimate − M12 rate) × entitlement until limitation")
        return Rule(id=f"R-{ruling.author_role.value.upper().replace('.', '-')}-X", version=1, kind="routing",
                    scope={}, condition={"all": []}, action=RuleAction.ROUTE_TO, action_arg=ruling.author_role.value,
                    tier="claims_lead_ruling" if ruling.author_role == Role.CLAIMS_LEAD else "legal_ruling",
                    authority_required=ruling.author_role, origin_ruling_id=ruling.id, valid_from=at, recorded_at=at,
                    status="proposed", title=ruling.decision[:120])

    def classify_challenge(self, decision: FlightDecision, text: str) -> tuple[str, list[Fact]]:
        t = text.lower()
        if re.search(r"hidden (manufacturing )?defect|operator notice|service bulletin|manufacturer|batch", t):
            cls = "new_legal_pattern"
        elif re.search(r"would have|anyway|storm|weather|everyone|grounded", t):
            cls = "assertion"
        else:
            cls = "new_fact"
        sid = "SRC-CHALLENGE-" + hashlib.sha256(text.encode()).hexdigest()[:12]
        fact = Fact(id=f"F:{sid}:challenge.text", source_id=sid, subject=f"flight:{decision.flight_id}",
                    field="challenge.text", value=text, span=text, extractor="fallback:regex@1", extract_conf=0.5,
                    recorded_at=decision.known_at, acl_tags=[])
        return cls, [fact]

    def challenge_reply(self, decision: FlightDecision, classification: str, cited: list[Evidence]) -> Draft:
        quotes = "; ".join(e.quote for e in cited if e.quote)[:600]
        if classification == "assertion":
            text = f"Decision stands. {decision.reason} Evidence: {quotes}"
        elif classification == "new_legal_pattern":
            text = ("This raises a legal question the engine does not decide (e.g. a hidden manufacturing defect, "
                    "C-549/07 ¶26). It has been routed to Legal; the decision is unchanged until Legal rules.")
        else:
            text = "Thank you. The new information has been recorded and routed for review; the decision is unchanged."
        return self._draft("challenge_reply", decision.flight_id, text)


# ================================================================ FakeBooks (in-memory ledger)
ULTIMATE = {600: Fraction(35, 100), 400: Fraction(27, 100), 250: Fraction(20, 100)}
SEGMENT = {600: "long_haul_gt3500", 400: "medium_1500_3500", 250: "short_le1500"}
ACCRUING = ("owed", "held", "needs_ruling")
LH_POINTS = [(0, Fraction(0)), (1, Fraction(9, 100)), (3, Fraction(17, 100)), (6, Fraction(24, 100)),
             (12, Fraction(29, 100)), (18, Fraction(32, 100)), (72, Fraction(35, 100))]
ACCOUNT_NAMES = {"4090": "EU261 compensation (reduction of passenger revenue)",
                 "2140": "EU261 compensation liability (estimated)", "2141": "EU261 compensation payable",
                 "1000": "Bank"}


def _rhalf(x: Fraction) -> int:
    n = abs(x)
    q = int(n) + (1 if n - int(n) >= Fraction(1, 2) else 0)
    return q if x >= 0 else -q


def _rate_at(age: int, ultimate: Fraction) -> Fraction:
    scale = ultimate / Fraction(35, 100)
    if age <= 0:
        return Fraction(0)
    for (m0, r0), (m1, r1) in zip(LH_POINTS, LH_POINTS[1:]):
        if m0 <= age <= m1:
            return (r0 + (r1 - r0) * Fraction(age - m0, m1 - m0)) * scale
    return ultimate


def _month_end(d: date) -> date:
    nxt = date(d.year + (d.month == 12), d.month % 12 + 1, 1)
    return nxt - timedelta(days=1)


def _age(event: date, period_end: date) -> int:
    m1 = _month_end(event + timedelta(days=28))
    if period_end < m1:
        return 0
    return (period_end.year - m1.year) * 12 + period_end.month - m1.month + 1


class FakeBooks:
    """BooksAPI in memory. Day-1 estimate = Σ accruing entitlement × segment ultimate (35/27/20%)."""

    def __init__(self, clock: Any = None):
        self.clock = clock
        self.jes: dict[str, JournalEntry] = {}
        self.posted_flights: dict[str, str | None] = {}
        self.locked: set[str] = set()
        self.cohort_dates: dict[str, date] = {}
        self.flight_ent: dict[str, dict[int, int]] = {}                       # flight -> band -> accruing entitlement
        self.flight_cohort: dict[str, str] = {}
        self.opening_ent: dict[str, int] = {}
        self.claimed_coupons: set[str] = set()
        self.opening: dict[str, int] = {}

    def _now(self) -> datetime:
        return self.clock.now() if self.clock is not None else datetime(2025, 1, 25, 6, 0, tzinfo=UTC)

    def _je(self, kind: str, event_date: date, memo: str, lines: list[tuple[str, int, int, dict[str, str]]],
            **kw: Any) -> JournalEntry:
        period = event_date.strftime("%Y-%m")
        if period in self.locked:
            raise FakePeriodLocked(f"period {period} is locked")
        je_id = f"JE-{len(self.jes) + 1:06d}"
        je = JournalEntry(id=je_id, event_date=event_date, period=period, memo=memo, kind=kind,
                          lines=[JournalLine(account=a, account_name=ACCOUNT_NAMES.get(a, a), dr_cents=dr, cr_cents=cr,
                                             dims=d) for a, dr, cr, d in lines],
                          status="draft", preparer="agent.engine", **kw)
        self.jes[je_id] = je
        return je

    def post_storm(self, run_id: str, world: World, decisions: list[FlightDecision], ents: list[Entitlement],
                   known_at: datetime) -> list[JournalEntry]:
        m = re.search(r"\d{4}-\d{2}-\d{2}", run_id)
        cohort_date = date.fromisoformat(m.group(0)) if m else known_at.date()
        self.cohort_dates.setdefault(run_id, cohort_date)
        for ob in world.opening_balances:
            if ob.cohort not in self.opening:
                self.opening[ob.cohort] = ob.balance_cents
                self.cohort_dates.setdefault(ob.cohort, date.fromisoformat(ob.cohort.split("@")[1]))
                self.opening_ent[ob.cohort] = ob.entitlement_cents
        out = []
        by_flight: dict[str, list[Entitlement]] = defaultdict(list)
        for e in ents:
            by_flight[e.flight_id].append(e)
        dec = {d.flight_id: d for d in decisions}
        for fid in sorted(by_flight):
            if fid in self.posted_flights:
                if self.posted_flights[fid]:
                    out.append(self.jes[self.posted_flights[fid]])
                continue
            acc: dict[int, int] = defaultdict(int)
            for e in by_flight[fid]:
                if e.status in ACCRUING:
                    acc[e.band_eur] += e.compensation_cents
            lines = []
            self.flight_ent[fid] = dict(acc)
            self.flight_cohort[fid] = run_id
            for band, ent in sorted(acc.items()):
                amt = _rhalf(ent * ULTIMATE[band])
                dims = {"cohort": run_id, "flight": fid, "segment": SEGMENT[band]}
                lines += [("4090", amt, 0, dims), ("2140", 0, amt, dims)]
            if not lines or not sum(x[1] for x in lines):
                self.posted_flights[fid] = None
                continue
            d = dec.get(fid)
            je = self._je("compensation_estimate", cohort_date,
                          f"EU261 compensation liability (estimated) · {fid} · expected ultimate claim rate", lines,
                          source_decision_id=d.commit if d else None, ties_to=["2140"],
                          built_from=len({x.source_id for x in d.evidence}) if d else 0)
            self.posted_flights[fid] = je.id
            out.append(je)
        return out

    def post_claim(self, claim: Claim, ent: Entitlement, known_at: datetime) -> list[JournalEntry]:
        amount = ent.compensation_cents - ent.voucher_offset_cents
        if ent.status != "owed" or amount <= 0 or ent.coupon_id in self.claimed_coupons:
            return []
        self.claimed_coupons.add(ent.coupon_id)
        cohort = self.flight_cohort.get(ent.flight_id, ent.flight_id)
        dims = {"cohort": cohort, "flight": ent.flight_id, "coupon": ent.coupon_id, "claim": claim.id}
        d = known_at.date()
        return [self._je("claim_approved", d, f"EU261 claim {claim.id} approved at face value {_eur(amount)}",
                         [("2140", amount, 0, dims), ("2141", 0, amount, dims)], ties_to=["2140"]),
                self._je("claim_paid", d, f"EU261 payout {_eur(amount)} · drafted, pending Claims Lead approval",
                         [("2141", amount, 0, dims), ("1000", 0, amount, dims)])]

    def entitlement(self, cohort: str, band: int | None = None) -> int:
        if cohort in self.opening_ent:
            return self.opening_ent[cohort] if band in (None, 600) else 0
        return sum(v for f, bands in self.flight_ent.items() if self.flight_cohort.get(f) == cohort
                   for b, v in bands.items() if band in (None, b))

    def _delta(self, before: list[Entitlement], after: list[Entitlement]) -> dict[str, int]:
        def acc(es: Iterable[Entitlement]) -> dict[str, int]:
            out: dict[str, int] = defaultdict(int)
            for e in es:
                if e.status in ACCRUING:
                    out[e.flight_id] += _rhalf(e.compensation_cents * ULTIMATE[e.band_eur])
            return out
        b, a = acc(before), acc(after)
        return {f: a.get(f, 0) - b.get(f, 0) for f in sorted(set(a) | set(b)) if a.get(f, 0) != b.get(f, 0)}

    def preview(self, before: list[Entitlement], after: list[Entitlement]) -> ReplayDiff:
        d = self._delta(before, after)
        return ReplayDiff(rule_ref="preview", known_at=self._now(),
                          flips=[ReplayFlip(entity_id=f, field="eu261_liability_cents", before=None, after=None,
                                            delta_cents=v) for f, v in d.items()],
                          total_delta_cents=sum(d.values()))

    def post_recode(self, before: list[Entitlement], after: list[Entitlement], known_at: datetime) -> list[JournalEntry]:
        out = []
        changed = {e.flight_id for e in after}
        for fid in changed:
            acc: dict[int, int] = defaultdict(int)
            for e in after:
                if e.flight_id == fid and e.status in ACCRUING:
                    acc[e.band_eur] += e.compensation_cents
            if fid in self.flight_ent:
                self.flight_ent[fid] = dict(acc)
        for fid, v in self._delta(before, after).items():
            dims = {"flight": fid, "cohort": self.flight_cohort.get(fid, fid)}
            lines = [("2140", -v, 0, dims), ("4090", 0, -v, dims)] if v < 0 else [("4090", v, 0, dims),
                                                                                  ("2140", 0, v, dims)]
            out.append(self._je("recode", known_at.date(), f"Recode {fid}: change in estimate {_eur(abs(v))}", lines,
                                ias8_class="change_in_estimate", ties_to=["2140"]))
        return out

    def gl(self, account: str = "2140", through: str | None = None, cohort: str | None = None) -> int:
        tot = sum(v for c, v in self.opening.items() if cohort in (None, c)) if account == "2140" else 0
        for je in self.jes.values():
            if through and je.period > through:
                continue
            for line in je.lines:
                if line.account == account and (cohort is None or line.dims.get("cohort") == cohort):
                    tot += line.cr_cents - line.dr_cents
        return tot

    def month_end(self, period: str, known_at: datetime) -> list[JournalEntry]:
        y, m = (int(x) for x in period.split("-"))
        pend = _month_end(date(y, m, 1))
        out = []
        for cohort, ev in sorted(self.cohort_dates.items()):
            if cohort in self.opening:
                continue
            age = _age(ev, pend)
            if age <= 0:
                continue
            target = sum(_rhalf((ULTIMATE[b] - _rate_at(age, ULTIMATE[b])) * self.entitlement(cohort, b))
                         for b in (250, 400, 600))
            change = target - self.gl("2140", period, cohort)
            if change:
                dims = {"cohort": cohort}
                lines = [("4090", change, 0, dims), ("2140", 0, change, dims)] if change > 0 else \
                    [("2140", -change, 0, dims), ("4090", 0, -change, dims)]
                out.append(self._je("change_in_estimate", pend, f"BF true-up {cohort} at M{age}: {_eur(target)}",
                                    lines, ias8_class="change_in_estimate", estimate_ref=f"BF:{cohort}@{period}"))
        return out

    def approve(self, je_id: str, session: Session) -> JournalEntry:
        je = self.jes[je_id]
        if session.role.value.startswith("agent.") or session.principal == je.preparer:
            raise FakeSoDViolation(f"{session.principal} may not approve {je_id} (SoD)")
        need = Role.CLAIMS_LEAD if je.kind in ("claim_approved", "claim_paid") else Role.CONTROLLER
        if session.role != need:
            raise FakeForbidden(f"{je_id} needs the {need.value}")
        if je.period in self.locked:
            raise FakePeriodLocked(f"period {je.period} is locked")
        je = je.model_copy(update={"status": "approved", "approver": session.principal})
        self.jes[je_id] = je
        return je

    def rollforward(self, period: str) -> Rollforward:
        rows = []
        for cohort in sorted(set(self.cohort_dates) | set(self.opening)):
            opening = self.opening.get(cohort, 0) + sum(
                line.cr_cents - line.dr_cents for je in self.jes.values() if je.period < period for line in je.lines
                if line.account == "2140" and line.dims.get("cohort") == cohort)
            cols: dict[str, int] = defaultdict(int)
            for je in self.jes.values():
                if je.period != period:
                    continue
                for line in je.lines:
                    if line.account == "2140" and line.dims.get("cohort") == cohort:
                        net = line.cr_cents - line.dr_cents
                        key = {"compensation_estimate": "new", "claim_approved": "claims", "recode": "recode"}.get(
                            je.kind, "cie")
                        cols[key] += -net if key == "claims" else net
            closing = opening + cols["new"] - cols["claims"] + cols["cie"] + cols["recode"]
            ent = self.entitlement(cohort)
            rows.append(RollforwardRow(cohort=cohort, opening_cents=opening, new_cents=cols["new"],
                                       claims_approved_cents=cols["claims"], change_in_estimate_cents=cols["cie"],
                                       recode_cents=cols["recode"], closing_cents=closing,
                                       unclaimed_entitlement_cents=max(ent - cols["claims"], 0)))
        total = sum(r.closing_cents for r in rows)
        gl = self.gl("2140", period)
        return Rollforward(period=period, rows=rows, closing_total_cents=total, gl_balance_cents=gl,
                           ties_to_gl=total == gl)

    def estimate_card(self, cohort: str, known_at: datetime) -> EstimateCard:
        ev = self.cohort_dates.get(cohort, known_at.date())
        pend = _month_end(known_at.date())
        age = _age(ev, pend)
        ent = self.entitlement(cohort)
        ult = Fraction(35, 100)
        rate = _rate_at(age, ult)
        actual = sum(line.dr_cents for je in self.jes.values() if je.kind == "claim_approved" for line in je.lines
                     if line.account == "2140" and line.dims.get("cohort") == cohort)
        bf = max(_rhalf((ult - rate) * ent), 0)
        el = max(_rhalf(ult * ent) - actual, 0)
        cl = _rhalf(Fraction(actual) * ult / rate) - actual if rate else el
        return EstimateCard(cohort=cohort, segment="long_haul_gt3500", pax=0, entitlement_cents=ent,
                            curve_version="LH-v1", months_developed=age, expected_loss_cents=el, bf_cents=bf,
                            chain_ladder_cents=max(cl, 0), selected="bf",
                            actual_vs_expected=round(actual / float(rate * ent), 3) if rate and ent else None,
                            credibility_z=round(float(rate / ult), 2) if rate else None,
                            sensitivity_5pp_cents=_rhalf(Fraction(5, 100) * ent),
                            constraint_note="IFRS 15.56 constraint (FakeBooks)", ias8_class="change_in_estimate",
                            preparer="agent.engine", approver=None)

    def curve(self, segment: str) -> ClaimCurve:
        doc = json.loads((GOLDEN / "curves.json").read_text(encoding="utf-8"))
        for c in doc["curves"]:
            if c["segment"] == segment:
                return ClaimCurve.model_validate(c)
        raise KeyError(segment)

    def invariants(self) -> list[InvariantResult]:
        unbalanced = [j.id for j in self.jes.values()
                      if sum(x.dr_cents for x in j.lines) != sum(x.cr_cents for x in j.lines)]
        return [InvariantResult(id="INV-BALANCED", description="Every journal entry balances (Σ Dr = Σ Cr)",
                                ok=not unbalanced, detail=f"{len(self.jes)} entries"),
                InvariantResult(id="INV-LOCKED", description="No entry is written to a locked period", ok=True,
                                detail=", ".join(sorted(self.locked)) or "no locked periods")]

    def lock_period(self, period: str, session: Session) -> None:
        if session.role != Role.CONTROLLER:
            raise FakeForbidden("only the controller locks a period")
        self.locked.add(period)

    def cfo_metrics(self, known_at: datetime) -> CfoMetrics:
        drafted = self.gl("2140")
        ent = sum(sum(b.values()) for b in self.flight_ent.values())
        return CfoMetrics(as_of=known_at, cash_basis_cents=0, full_entitlement_cents=ent,
                          drafted_liability_cents=drafted, sensitivity_5pp_cents=_rhalf(Fraction(5, 100) * ent),
                          method_range_cents=(drafted, drafted), held_for_legal_cents=0, liability_bridge=[],
                          recodes_count=sum(1 for j in self.jes.values() if j.kind == "recode"), recodes_cents=0,
                          refunds_within_7d_pct=100.0, vouchers_outstanding_cents=0, care_accrued_cents=0,
                          care_invoiced_cents=0)

    def journal(self, period: str | None = None, status: str | None = None) -> list[JournalEntry]:
        return [j for j in self.jes.values() if (period is None or j.period == period)
                and (status is None or j.status == status)]

    def audit(self, je_id: str) -> dict:
        je = self.jes[je_id]
        return {"je": je.model_dump(mode="json"), "register": [], "decision_commits": [je.source_decision_id]
                if je.source_decision_id else []}


# ================================================================ FakeEngine (golden expected/)
PRIMARY_IDS = {"knock_on_return": "Q-2", "voucher_in_lieu_unsigned": "Q-1", "cohort_release": "Q-3"}


class FakeEngine:
    """EngineAPI from golden `expected/decisions.json` (+ a heuristic for flights it doesn't list)."""

    def __init__(self, world: World | None = None, calibration: dict[str, Any] | None = None):
        self.world = world
        dec = _expected("decisions.json")
        self.expected: dict[str, dict[str, Any]] = {fid: row for rows in dec["storms"].values()
                                                    for fid, row in rows.items()}
        self.calibration = calibration or _cal.load()

    # ---------- helpers
    def _w(self, world: World | None = None) -> World:
        return world or self.world or golden_world()

    @staticmethod
    def _active(rules: Sequence[Rule], action: RuleAction, known_at: datetime) -> list[Rule]:
        return [r for r in rules if r.action == action and r.status == "active" and r.recorded_at <= known_at
                and not r.static_card]

    def _ends(self, w: World, fid: str) -> dict[str, Any]:
        f = next(x for x in w.flights if x.id == fid)
        o_obs, d_obs = station_obs(w, _icao(w, f.origin)), station_obs(w, _icao(w, f.dest))
        dep = position(f.sched_dep, o_obs, storm_windows(o_obs))
        arr = position(f.sched_arr, d_obs, storm_windows(d_obs))
        hub_end = "dep" if f.origin == "DUB" else "arr"
        margin = dep[1] if hub_end == "dep" else arr[1]
        return {"flight": f, "dep": dep[0], "arr": arr[0], "margin": margin, "o_obs": o_obs, "d_obs": d_obs}

    def _heuristic(self, w: World, e: dict[str, Any], known_at: datetime) -> dict[str, Any]:
        f = e["flight"]
        aog = [t for t in w.tech_log if t.aircraft == f.aircraft and t.aog and t.mel_relief is False
               and t.logged_at <= f.sched_dep]
        if "in" in (e["dep"], e["arr"]):
            if aog:
                return {"cause": "concurrent", "extraordinary": "needs_legal", "recoded": False, "recode_label": None,
                        "outcome": "escalated", "routed_to": "legal"}
            return {"cause": "weather", "extraordinary": "extraordinary", "recoded": False, "recode_label": None,
                    "outcome": "auto", "routed_to": None}
        if aog and "unknown" not in (e["dep"], e["arr"]):
            rec = f.ops_cause_code not in (None, "41")
            return {"cause": "technical", "extraordinary": "not_extraordinary", "recoded": rec,
                    "recode_label": f"{f.ops_cause_code} → 41" if rec else None, "outcome": "auto", "routed_to": None}
        if f.outbound_pair_id:
            return {"cause": "knock_on", "extraordinary": "needs_legal", "recoded": False, "recode_label": None,
                    "outcome": "escalated", "routed_to": "legal"}
        return {"cause": "unknown", "extraordinary": "needs_legal", "recoded": False, "recode_label": None,
                "outcome": "escalated", "routed_to": "ops"}

    def _evidence(self, w: World, e: dict[str, Any], cause: str, recoded: bool) -> list[Evidence]:
        f = e["flight"]
        facts = world_to_facts(w, flight_ids=[f.id], include_metar=False)
        src = {s.id: s for s in w.sources}
        ev: list[Evidence] = []

        def add(fact: Fact, role: str, struck: bool = False) -> None:
            s = src.get(fact.source_id)
            ev.append(Evidence(fact_id=fact.id, source_id=fact.source_id, field=fact.field, value=fact.value,
                               quote=fact.span, role=role, trust_tier=s.trust_tier if s else 2, struck=struck))
        tl = [x for x in facts if x.subject == f"aircraft:{f.aircraft}" and x.field in ("aog.mel_relief",
                                                                                         "aog.ata_chapter",
                                                                                         "aog.logged_at")]
        if cause in ("technical", "concurrent"):
            for x in tl:
                add(x, "supports")
            for x in facts:
                if x.subject == f"flight:{f.id}" and x.field == "mcc.part_eta":
                    add(x, "supports")
        hub_t = f.sched_dep if f.origin == "DUB" else f.sched_arr
        hub_obs = e["o_obs"] if f.origin == "DUB" else e["d_obs"]
        if hub_obs:
            o = min(hub_obs, key=lambda o: (abs(o.valid - hub_t), o.valid))
            ev.append(Evidence(fact_id=f"F:METAR-{o.station}-{o.valid.strftime('%Y%m%dT%H%MZ')}:metar.gust_kt",
                               source_id=next((s.id for s in w.sources if s.kind.value == "metar" and o.raw in
                                               (s.text or "")), "SRC-WORLD"),
                               field="metar.gust_kt", value=o.gust, quote=o.raw,
                               role="supports" if cause in ("weather", "technical") else "contradicts", trust_tier=1))
        if cause == "knock_on":
            for x in facts:
                if x.subject == f"flight:{f.id}" and x.field in ("spare.available_within_h",
                                                                 "pax.reroute_earliest_offered"):
                    add(x, "context")
        occ = next((x for x in facts if x.subject == f"flight:{f.id}" and x.field == "flight.ops_cause_code"), None)
        if occ is not None:
            add(occ, "contradicts" if cause != "weather" else "supports", struck=recoded)
        return ev

    def _confidence(self, cause: str, e: dict[str, Any], aog_before: bool, disagree: bool,
                    precedent: float) -> Confidence:
        m = e["margin"]
        feats = {"in_window_dep": 1.0 if e["dep"] == "in" else 0.0, "in_window_arr": 1.0 if e["arr"] == "in" else 0.0,
                 "window_margin_h": round(min(4.0, abs(m) / 60), 2) if m is not None else 0.0,
                 "aog_before_window": 1.0 if aog_before else 0.0,
                 "aog_inside_window": 1.0 if cause == "concurrent" else 0.0,
                 "root_cause_internal": 1.0 if cause == "technical" else 0.0,
                 "sources_disagree": 1.0 if disagree else 0.0, "precedent_count": precedent,
                 "knock_on": 1.0 if cause == "knock_on" else 0.0}
        caps = ["capped:no-precedent"] if cause in ("knock_on", "unknown") and not precedent else []
        return Confidence(score=_cal.score(self.calibration, "cause", feats), kind="cause",
                          label="cause-finding confidence", features=feats, caps=caps,
                          calibration_version=str(self.calibration.get("version", CAL_VERSION_FAKE)))

    # ---------- EngineAPI
    def decide(self, flight_id: str, facts: list[Fact], rules: list[Rule], known_at: datetime,
               calibration_version: str | None = None) -> FlightDecision:
        return self.decide_in(self._w(), flight_id, rules, known_at)

    def decide_in(self, w: World, flight_id: str, rules: Sequence[Rule], known_at: datetime) -> FlightDecision:
        e = self._ends(w, flight_id)
        f = e["flight"]
        row = dict(self.expected.get(flight_id) or self._heuristic(w, e, known_at))
        rules_applied = []
        if row["cause"] == "weather":
            rules_applied.append("R-REG-ART5-3@1")
        if row["cause"] == "knock_on":
            leg = [r for r in self._active(rules, RuleAction.SET_EXTRAORDINARY, known_at) if r.tier == "legal_ruling"]
            if leg:
                row.update(extraordinary="extraordinary", outcome="auto", routed_to=None)
                rules_applied.append(f"{leg[0].id}@{leg[0].version}")
        aog_before = row["cause"] == "technical"
        # the tier-1 tech log settles NS31's code (no disagreement left); only concurrent causes stay contested
        disagree = row["cause"] == "concurrent"
        prec = 10.0 if rules_applied and row["cause"] == "knock_on" else (3.0 if row["cause"] in ("technical",
                                                                                                  "weather") else 0.0)
        conf = self._confidence(row["cause"], e, aog_before, disagree, prec)
        reason = self._reason(row, e)
        d = FlightDecision(
            flight_id=flight_id, cause=row["cause"], extraordinary=row["extraordinary"],
            ops_cause_code=f.ops_cause_code, recoded=row["recoded"], recode_label=row.get("recode_label"),
            in_window_dep=e["dep"], in_window_arr=e["arr"], window_margin_min=e["margin"], confidence=conf,
            reason=reason, evidence=self._evidence(w, e, row["cause"], row["recoded"]), rules_applied=rules_applied,
            legal_basis=LEGAL_BASIS.get(row["cause"], LEGAL_BASIS["unknown"]), outcome=row["outcome"],
            routed_to=Role(row["routed_to"]) if row["routed_to"] else None,
            question_id=None, known_at=known_at)
        return d.model_copy(update={"commit": canon_hash(d)})

    @staticmethod
    def _reason(row: dict[str, Any], e: dict[str, Any]) -> str:
        f = e["flight"]
        c = row["cause"]
        if c == "weather":
            end = "STD" if f.origin == "DUB" else "STA"
            t = f.sched_dep if end == "STD" else f.sched_arr
            return f"Weather: Dublin inside the storm window at {end} {_hhmm(t)}."
        if c == "technical":
            return (f"Not weather: {f.aircraft} AOG with no MEL relief, logged before the storm; out of window at "
                    f"both ends.")
        if c == "knock_on":
            if row["extraordinary"] == "extraordinary":
                return "Knock-on return settled as extraordinary under Legal's ruling (C-74/19)."
            return (f"Knock-on: {f.outbound_pair_id.split('@')[0] if f.outbound_pair_id else 'the outbound'} never "
                    f"left Dublin, so {f.aircraft} never reached {f.origin}; calm at both ends. Legal question.")
        if c == "concurrent":
            return "Concurrent causes: an AOG inside the storm window. Legal question."
        return "Not enough evidence to decide the cause (no METAR near the schedule). Ops question."

    def entitlements(self, decision: FlightDecision, world: World, rules: list[Rule]) -> list[Entitlement]:
        f = next(x for x in world.flights if x.id == decision.flight_id)
        if f.status != "cancelled":
            return []
        far = f.dest if f.origin == "DUB" else f.origin
        dist = distance_km(world, f.origin, f.dest)
        o, de = _airport(world, f.origin), _airport(world, f.dest)
        intra = bool(o and de and o.eu and de.eu)
        band = 250 if dist <= 1500 else (400 if intra or dist <= 3500 else 600)
        margin = (1500 - dist) if band == 250 else (dist - 1500 if band == 400 and intra else
                                                    (min(dist - 1500, 3500 - dist) if band == 400 else dist - 3500))
        limit = {250: 120, 400: 180, 600: 240}[band]
        known_at = decision.known_at
        reduce = self._active(rules, RuleAction.APPLY_7_2_REDUCTION, known_at)
        deny = self._active(rules, RuleAction.DENY_OFFSET, known_at)
        el = {x.coupon_id: x for x in world.elections}
        crm: dict[str, list] = defaultdict(list)
        for ev in world.crm:
            if ev.at <= known_at:
                crm[ev.coupon_id].append(ev)
        out = []
        for c in world.coupons:
            if c.flight_id != f.id:
                continue
            x = el.get(c.id)
            evs = crm.get(c.id, [])
            refund_done = any(v.kind in ("refund_initiated", "bsp_refund") for v in evs)
            refund_due = 0 if refund_done or not x or x.kind != "refund" else c.fare_cents + c.taxes_cents
            applied: list[str] = list(decision.rules_applied)
            red = "none"
            comp = band * 100
            if c.fare_type == "staff_id90":
                status, comp, art = "staff_ticket", 0, "Art. 3(3)"
            elif decision.extraordinary == Extraordinary.YES:
                status, comp, art = "no_compensation", 0, "Art. 5(3)"
            elif decision.extraordinary == Extraordinary.NEEDS_LEGAL:
                status, art = "held", "Art. 5(3), 7(1)"
            else:
                status, art = "owed", "Art. 7(1)"
                if (reduce and x and x.kind in ("reroute_partner", "reaccommodated_own")
                        and x.arrival_delay_min is not None and x.arrival_delay_min <= limit):
                    comp //= 2
                    red = "art7_2_50pct"
                    applied.append(f"{reduce[0].id}@{reduce[0].version}")
                lieu = [v for v in evs if v.kind == "voucher_in_lieu_of_compensation"]
                if lieu and not lieu[-1].signed_acceptance_sha256:
                    hit = [r for r in deny if r.scope.get("flight.departs_eu") in (None, True, "case:true")
                           and (r.scope.get("flight.departs_eu") is None or bool(o and o.eu))]
                    if hit:
                        applied.append(f"{hit[0].id}@{hit[0].version}")
                    else:
                        status = "needs_ruling"
            reason = {"no_compensation": "Extraordinary circumstances. No compensation; refunds and care still due.",
                      "held": "Held for Legal: compensation owed unless the cancellation is extraordinary.",
                      "needs_ruling": "Voucher in lieu of compensation without signed acceptance (Art. 7(3)): "
                                      "offset needs the Claims Lead.",
                      "owed": f"Compensation owed: {_eur(comp)} ({dist:,.0f} km).",
                      "staff_ticket": "Staff ticket: the Regulation does not apply (Art. 3(3))."}[status]
            out.append(Entitlement(coupon_id=c.id, flight_id=f.id, distance_km=dist, band_eur=band,
                                   band_margin_km=round(margin, 1), compensation_cents=comp, reduction=red,
                                   refund_due_cents=refund_due, refund_already_initiated=refund_done,
                                   care_due=status != "staff_ticket", voucher_offset_cents=0, status=status,
                                   article=art, reason=reason, rules_applied=list(dict.fromkeys(applied))))
        _ = far
        return out

    def mine_rules(self, world: World) -> list[RuleProposal]:
        rr = [h for h in world.history_cases if h.kind == "reroute_reduction"]
        if len(rr) < 8:
            return []
        applied = sum(1 for h in rr if h.decision == "apply_7_2_reduction")
        if applied / len(rr) < 0.95:
            return []
        at = max(h.at for h in rr)
        rule = Rule(id="R-MINED-REDUCE", version=1, kind="mined_policy", scope={},
                    condition={"all": [{"f": "pax.election", "op": "in", "v": ["reroute_partner",
                                                                                "reaccommodated_own"]}]},
                    action=RuleAction.APPLY_7_2_REDUCTION, tier="mined", authority_required=Role.CLAIMS_LEAD,
                    origin_example=f"history_cases ({len(rr)} reroute-reduction decisions)",
                    support=f"{applied} of {len(rr)}", valid_from=at, recorded_at=at, status="shadow",
                    title="Take the 50% reroute cut (Art. 7(2)) when the reroute arrives within the band's limit")
        return [RuleProposal(rule=rule, checks={"compiles": True, "reproduces_case": True, "no_hard_control": True,
                                                "grounded": True, "author_has_authority": True, "no_conflict": True},
                             would_flip=ReplayDiff(rule_ref="R-MINED-REDUCE@1", known_at=at, flips=[],
                                                   total_delta_cents=0))]

    # ---------- storm run
    def storm_flights(self, w: World, station: str, local_day: date) -> list[str]:
        storm = f"{station}@{local_day.isoformat()}"
        meta = (w.meta.get("storms") or {}).get(storm)
        if meta:
            return list(meta["flight_ids"])
        iata = next((a.iata for a in w.airports if a.icao == station), station)
        return [f.id for f in w.flights if iata in (f.origin, f.dest) and f.date == local_day]

    def run_storm(self, world: World, station: str, local_day: date, rules: list[Rule],
                  known_at: datetime) -> StormRun:
        w = world
        storm = f"{station}@{local_day.isoformat()}"
        ids = self.storm_flights(w, station, local_day)
        obs = list(w.metar.get(storm) or [o for o in station_obs(w, station)
                                          if o.valid.date() in (local_day, local_day - timedelta(days=1))])
        windows = storm_windows(obs)
        flights = sorted((f for f in w.flights if f.id in set(ids)), key=lambda f: (f.status != "cancelled",
                                                                                    f.sched_dep, f.id))
        decisions: dict[str, FlightDecision] = {}
        ents: dict[str, list[Entitlement]] = {}
        for f in flights:
            if f.status == "cancelled":
                d = self.decide_in(w, f.id, rules, known_at)
                decisions[f.id] = d
                ents[f.id] = self.entitlements(d, w, rules)
        questions = self._questions(w, storm, decisions, ents, known_at)
        qmap = {ref: q.id for q in questions for ref in q.case_refs}
        for fid, d in list(decisions.items()):
            if fid in qmap:
                decisions[fid] = d.model_copy(update={"question_id": qmap[fid]})
        all_ents = [e for es in ents.values() for e in es]
        owed = sum(e.compensation_cents for e in all_ents if e.status in ("owed", "needs_ruling"))
        liability = sum(_rhalf(sum(e.compensation_cents for e in es if e.status in ACCRUING and e.band_eur == b)
                               * ULTIMATE[b]) for es in ents.values() for b in (250, 400, 600))
        cancelled = [f for f in flights if f.status == "cancelled"]
        counters = {
            "passengers": sum(f.pax for f in cancelled), "cancelled": len(cancelled),
            "operated": len(flights) - len(cancelled),
            "drafted": sum(1 for fid, es in ents.items() for e in es if e.status in ("owed", "needs_ruling")
                           and e.compensation_cents and decisions[fid].outcome == "auto"),
            "held": sum(f.pax for f in cancelled if decisions[f.id].extraordinary == Extraordinary.NEEDS_LEGAL),
            "questions": len(questions), "people": len({q.routed_to for q in questions}), "repeat_questions": 0,
            "rules_cited": sum(len(d.rules_applied) for d in decisions.values()) + sum(
                1 for e in all_ents for r in e.rules_applied if r not in decisions[e.flight_id].rules_applied),
            "recoded": sum(1 for d in decisions.values() if d.recoded),
            "weather": sum(1 for d in decisions.values() if d.cause.value == "weather"),
        }
        peak = max((o.gust or o.sknt or 0 for o in obs), default=0)
        airports = sorted({c for f in flights for c in (f.origin, f.dest)}, key=lambda c: (c != "DUB", c))
        feed = self._feed(storm, decisions, ents, questions, known_at, windows, len(obs))
        mined = self.mine_rules(w)
        learned = [LearnedItem(text="35% expected ultimate claim rate for owed long-haul passengers (history to "
                                    "M18 + tail judgment)", support="curve LH-v1")]
        if mined:
            learned.append(LearnedItem(text="Takes the 50% reroute cut (Art. 7(2)) when a reroute arrives within "
                                            "the band's limit", support=mined[0].rule.support,
                                       rule_ref="R-MINED-REDUCE@1"))
        learned.append(LearnedItem(text="Asks Legal about cause patterns, the Claims Lead about vouchers, the "
                                        "Controller about releases"))
        return StormRun(id=storm, station=station, date=local_day, windows=windows, metar=obs,
                        flights=[FlightRow(flight=f, decision=decisions.get(f.id)) for f in flights],
                        counters=counters, entitlement_cents=owed, liability_drafted_cents=liability,
                        learned=learned, questions=questions, feed=feed,
                        real_context=w.real_context.get(storm, {}),
                        message=None if windows else f"max gust {peak} kt · no storm window",
                        airports=[a for a in (_airport(w, c) for c in airports) if a is not None])

    def _questions(self, w: World, storm: str, decisions: dict[str, FlightDecision],
                   ents: dict[str, list[Entitlement]], known_at: datetime) -> list[Question]:
        primary = storm == min((w.meta.get("storms") or {storm: {}}), default=storm)
        qid = (lambda p: PRIMARY_IDS[p] if primary and p in PRIMARY_IDS else f"Q-{storm}:{p}")
        out: list[Question] = []
        remind = known_at + timedelta(hours=3)
        legal = [d for d in decisions.values() if d.routed_to == Role.LEGAL]
        if legal:
            refs = sorted(d.flight_id for d in legal)
            held = sum(_rhalf(sum(e.compensation_cents for e in ents[f]) * ULTIMATE[ents[f][0].band_eur])
                       for f in refs if ents.get(f))
            pattern = "knock_on_return" if all(d.cause.value == "knock_on" for d in legal) else "concurrent_causes"
            conf = min((d.confidence for d in legal), key=lambda c: c.score or 0)
            out.append(Question(
                id=qid(pattern), case_refs=refs, pattern=pattern, routed_to=Role.LEGAL, asked_at=known_at,
                title="Is the return sector of a storm-cancelled rotation extraordinary when both ends were calm?"
                if pattern == "knock_on_return" else "Concurrent causes: is this cancellation extraordinary?",
                found=f"{', '.join(r.split('@')[0] for r in refs)} were cancelled because their outbound legs never "
                      "left Dublin; each return was calm at both ends.",
                why_flagged="No precedent. C-74/19 needs a direct causal link and reasonable measures.",
                recommends="Extraordinary only if no aircraft and crew could operate the return within 3 h of STD and "
                           "passengers were offered the earliest reroute on any carrier (C-74/19).",
                recommended_option="Extraordinary if no aircraft within 3 h of STD and the earliest reroute was "
                                   "offered",
                options=["Extraordinary if no aircraft within 3 h of STD and the earliest reroute was offered",
                         "Not extraordinary: compensation owed on all", "Decide flight by flight"],
                evidence=[e for d in legal for e in d.evidence if e.field in ("spare.available_within_h",
                                                                              "metar.gust_kt")],
                confidence=conf, reason_tag="no-precedent" if pattern == "knock_on_return" else "concurrent-causes",
                holds=refs, holds_cents=held, status="open", remind_at=remind))
        lieu = sorted(e.coupon_id for es in ents.values() for e in es if e.status == "needs_ruling")
        if lieu:
            feats = {"in_lieu": 1.0, "signed": 0.0, "sources_disagree": 1.0, "precedent_count": 0.0}
            out.append(Question(
                id=qid("voucher_in_lieu_unsigned"), case_refs=lieu, pattern="voucher_in_lieu_unsigned",
                routed_to=Role.CLAIMS_LEAD, asked_at=known_at,
                title="Does a service-desk voucher 'in lieu of compensation' offset the compensation without a "
                      "signed acceptance?",
                found=f"{len(lieu)} passenger(s) were handed a voucher 'in lieu of compensation'; CRM records them as "
                      "accepted, but there is no signed acceptance on file.",
                why_flagged="Sources disagree, and Art. 7(3) needs signed agreement for vouchers. No precedent.",
                recommends="No signed acceptance, no offset: pay the compensation in cash; the voucher stays as "
                           "goodwill.",
                recommended_option="Pay €600 cash; the voucher stays as goodwill" if any(
                    e.band_eur == 600 for es in ents.values() for e in es if e.coupon_id in lieu)
                else "Pay the compensation in cash; the voucher stays as goodwill",
                options=["Pay €600 cash; the voucher stays as goodwill", "Offset the voucher: pay the difference",
                         "Ask the passenger to sign the acceptance first"],
                evidence=[], confidence=Confidence(score=_cal.score(self.calibration, "voucher", feats), kind="voucher",
                                                   label="voucher-offset confidence", features=feats,
                                                   caps=["capped:sources-disagree"],
                                                   calibration_version=str(self.calibration.get("version"))),
                reason_tag="sources-disagree", holds=lieu,
                holds_cents=sum(e.compensation_cents for es in ents.values() for e in es if e.coupon_id in lieu),
                status="open", remind_at=remind))
        if primary:
            for ob in w.opening_balances:
                feats = {"cohort_age_months": 12.0, "months_since_last_claim": 3.0, "precedent_count": 0.0}
                out.append(Question(
                    id=PRIMARY_IDS["cohort_release"], case_refs=[ob.cohort], pattern="cohort_release",
                    routed_to=Role.CONTROLLER, asked_at=known_at,
                    title=f"Reduce the {ob.cohort} cohort to nil at M12?",
                    found=f"Cohort {ob.cohort}: {_eur(ob.entitlement_cents)} full Art. 7 entitlement, "
                          f"{round(ob.claimed_cents / ob.entitlement_cents * 100)}% claimed by M12, "
                          f"{_eur(ob.balance_cents)} EU261 compensation liability remaining. No new claims in 3 months.",
                    why_flagged="Release proposal: a change in estimate (IAS 8.36) needs the Controller.",
                    recommends=f"Reduce the remaining {_eur(ob.balance_cents)} to nil as a change in estimate.",
                    recommended_option="Reduce to nil now",
                    options=["Reduce to nil now", "Keep the expected tail until the six-year limitation",
                             "Review again at M18"],
                    evidence=[], confidence=Confidence(score=_cal.score(self.calibration, "release", feats),
                                                       kind="release", label="release confidence", features=feats,
                                                       calibration_version=str(self.calibration.get("version"))),
                    reason_tag="release-proposal", holds=[ob.cohort], holds_cents=ob.balance_cents, status="open",
                    remind_at=remind))
        ops = [d for d in decisions.values() if d.routed_to == Role.OPS]
        if ops:
            out.append(Question(
                id=qid("data_gap"), case_refs=sorted(d.flight_id for d in ops), pattern="data_gap",
                routed_to=Role.OPS, asked_at=known_at, title="Missing weather data: what happened to these flights?",
                found="No METAR within 60 minutes of the schedule at one end.", why_flagged="Data gap.",
                recommends="Confirm the cause from the ops log.", recommended_option="Confirm the cause",
                options=["Confirm the cause", "Weather", "Not weather"], evidence=[],
                confidence=min((d.confidence for d in ops), key=lambda c: c.score or 0), reason_tag="out-of-scope",
                holds=sorted(d.flight_id for d in ops), status="open", remind_at=remind))
        return out

    @staticmethod
    def _feed(storm: str, decisions: dict[str, FlightDecision], ents: dict[str, list[Entitlement]],
              questions: list[Question], known_at: datetime, windows: list[StormWindow], n_obs: int) -> list[TraceEvent]:
        out: list[TraceEvent] = []

        def ev(kind: str, actor: str, summary: str, chip: str, ref: str | None = None, amount: int | None = None):
            out.append(TraceEvent(seq=len(out) + 1, at=known_at + timedelta(seconds=2 * len(out)), kind=kind,
                                  actor=actor, summary=summary, ref=ref, chip=chip, amount_cents=amount))
        main = max(windows, key=lambda w: w.end - w.start) if windows else None
        ev("info", "agent.engine", f"Read {n_obs} METAR obs" + (f" · storm window {_hhmm(main.start)}–{_hhmm(main.end)}"
                                                                f" · peak gust {main.peak_gust_kt} kt" if main else
                                                                " · no storm window"), "INFO", storm)
        weather = [d for d in decisions.values() if d.cause.value == "weather"]
        if weather:
            ev("decision", "agent.engine", f"{len(weather)} flights confirmed weather · no compensation; refunds and "
                                           "care still due", "APPLIED", storm)
        for d in decisions.values():
            if d.recoded:
                owed = [e for e in ents[d.flight_id] if e.status in ("owed", "needs_ruling")]
                ev("decision", "agent.engine", f"{d.flight_id.split('@')[0]} recoded {d.recode_label} · {len(owed)} "
                                               "payouts drafted", "APPLIED", d.flight_id)
        for q in questions:
            ev("question", "agent.engine", f"Asked {q.routed_to.value.replace('_', ' ').title()}: {q.pattern} · "
                                           f"confidence {round((q.confidence.score or 0) * 100)}% · {q.reason_tag}",
               "ASKED", q.id, q.holds_cents or None)
        return out


__all__ = ["FakeWorld", "FakeReader", "FakeDrafter", "FakeBooks", "FakeEngine", "WorldError", "FakeSoDViolation",
           "FakeForbidden", "FakePeriodLocked", "impl", "golden_world", "storm_windows", "position", "station_obs",
           "distance_km", "canon_hash", "INJECTION_RE"]
