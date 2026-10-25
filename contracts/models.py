"""StormCheck contracts v2 — generated verbatim from CONTRACTS.md §1. Additive-only changes; log in contracts/CHANGELOG.md."""
from __future__ import annotations
import re as _re
from datetime import datetime, date, timezone as _tz
from enum import Enum
from typing import Annotated, Any, Literal
from pydantic import AfterValidator, BaseModel, ConfigDict, Strict, WithJsonSchema
from pydantic import Field as _Field     # additive (blackout v1): World.events is left out of dumps while empty


def _utc(v: datetime) -> datetime:
    """Every model time is tz-aware and stored in UTC (the same instant always hashes the same)."""
    if v.tzinfo is None or v.utcoffset() is None:
        raise ValueError("naive datetime: StormCheck times are tz-aware UTC (ISO-8601 with Z)")
    return v.astimezone(_tz.utc)


_ID_RE = _re.compile(r"^[A-Za-z0-9@.:_-]+$")


def _id(v: str) -> str:
    if not _ID_RE.match(v):
        raise ValueError(f"id {v[:60]!r} may use only [A-Za-z0-9@.:_-]")
    return v


# additive tightening (D0b-6): stricter validation, same JSON schema types
Cents = Annotated[int, Strict()]                     # integer euro cents; no bool, float or numeric string
UTCDateTime = Annotated[datetime, AfterValidator(_utc)]
ID = Annotated[str, AfterValidator(_id)]

class Role(str, Enum):
    CLAIMS_LEAD = "claims_lead"; LEGAL = "legal"; CONTROLLER = "controller"
    OPS = "ops"; CFO = "cfo"; JUDGE = "judge"
    READER = "agent.reader"; DRAFTER = "agent.drafter"; ENGINE = "agent.engine"; CRM_BOT = "agent.crm_bot"

class Session(BaseModel):
    principal: str; role: Role; name: str; issued_at: UTCDateTime

# ---------- raw world ----------
class SourceKind(str, Enum):
    METAR = "metar"; SCHEDULE = "schedule"; OCC_LOG = "occ_log"; MCC_LOG = "mcc_log"; TECH_LOG = "tech_log"
    SPARES = "spares"; MANIFEST = "manifest"; PSS = "pss"; CRM = "crm"; BSP = "bsp"; CLAIM = "claim"
    EMAIL = "email"; REGULATION = "regulation"; RULING = "ruling"; MANUFACTURER = "manufacturer"; CHALLENGE = "challenge"
    FINANCE = "finance"                     # additive (D0b): GL extracts, care accrual sheets, vendor invoices
    EXTERNAL_EVENT = "external_event"       # additive (blackout v1): grid/airport/ANSP notice (tier 1); tier 4 if a passenger says it

class Source(BaseModel):
    id: ID; kind: SourceKind; title: str
    text: str | None = None                 # raw text; Fact.span quotes from here
    sha256: str; received_at: UTCDateTime
    trust_tier: int                         # 1 tech log/METAR/MCC · 2 schedule/manifest/PSS/BSP · 3 OCC batch code/CRM · 4 passenger/agency/challenge
    acl_tags: list[str] = []                # "pii" | "ops" | "finance" | "legal" | "maintenance"
    uri: str | None = None

class Fact(BaseModel):
    id: ID; source_id: ID
    subject: str                            # "flight:NS31@2025-01-24" | "aircraft:EI-NSB" | "coupon:NS31@2025-01-24:14C" | "storm:EIDW@2025-01-24"
    field: str                              # MUST be registered in contracts/fields.py
    value: Any
    span: str | None = None                 # verbatim substring of Source.text; contracts/parse.py re-parses value from it
    extractor: str                          # "parser:iem@1" | "normalize@1" | "llm:<response.model>@reader-v1" | "fallback:regex@1"
    extract_conf: float | None = None
    valid_at: UTCDateTime | None = None; recorded_at: UTCDateTime
    acl_tags: list[str] = []

class MetarObs(BaseModel):
    station: str; valid: UTCDateTime
    sknt: int | None = None; gust: int | None = None; drct: int | None = None
    vsby_sm: float | None = None; wxcodes: str | None = None; raw: str

class StormWindow(BaseModel):
    station: str; start: UTCDateTime; end: UTCDateTime; peak_gust_kt: int
    definition: str = "gust>=35kt or sknt>=30kt or vsby<0.5sm or wx in {SN,FZ,TS,GR}; gaps<2h merged"
    obs_count: int = 0
    kind: str = "weather"                   # additive (blackout v1): "weather" | "grid_outage"
    label: str | None = None                # additive (blackout v1): "Grid outage (Iberian blackout)"


class EventAirportWindow(BaseModel):        # additive (blackout v1): an external event's outage window at one airport
    icao: str                               # "LPPT"
    start: UTCDateTime                      # 2025-04-28T10:33:00Z
    end: UTCDateTime                        # when normal operations resumed at that airport
    note: str | None = None                 # "approximate: ..." whenever the end is an estimate, never a published fact


class ExternalEvent(BaseModel):             # additive (blackout v1): a non-weather extraordinary event (grid outage, ...)
    id: ID                                  # "EVT-IBERIA-BLACKOUT@2025-04-28"
    kind: str                               # "grid_outage"
    title: str                              # "Iberian Peninsula blackout"
    airports: list[EventAirportWindow]
    source_ids: list[ID]                    # Source(kind=EXTERNAL_EVENT, trust_tier=1) with the verbatim notice text


def _no_events(v: list[Any]) -> bool:
    return not v

class Airport(BaseModel):
    icao: str; iata: str; name: str; lat: float; lon: float; country: str
    eu: bool                                # EU261 territory (EU27 + EEA + CH)
    tz: str                                 # IANA, e.g. "Europe/Dublin"

class Flight(BaseModel):
    id: ID; number: str; date: date        # date = local departure date
    origin: str; dest: str                  # IATA
    sched_dep: UTCDateTime; sched_arr: UTCDateTime
    aircraft: str
    status: Literal["operated", "cancelled", "delayed"]
    actual_dep: UTCDateTime | None = None; actual_arr: UTCDateTime | None = None
    pax: int                                # manifest wins over ops
    ops_cause_code: str | None = None       # IATA delay code as typed by OCC: "71","72","41","93","...". Never trusted alone.
    inbound_flight_id: ID | None = None    # previous rotation of the same tail
    outbound_pair_id: ID | None = None     # for a return sector, the outbound that positions the aircraft
    notified_at: UTCDateTime | None = None     # when pax were told (Art. 5(1)(c))
    operating_carrier_eu: bool = True

class TechLogEntry(BaseModel):
    id: ID; aircraft: str; logged_at: UTCDateTime; station: str
    ata: str                                # "2913"
    text: str                               # raw AMOS-style line, e.g. "23JAN 21:40Z EI-NSB DUB N/S. HYD FLUID ENG 2 LWR COWL. ..."
    mel_relief: bool | None = None          # False = no-go
    aog: bool; rts_est: UTCDateTime | None = None

class OpsLogEntry(BaseModel):
    id: ID; at: UTCDateTime; kind: Literal["occ", "mcc", "spares"]
    flight_ids: list[ID] = []; code: str | None = None; text: str; author: str

class Coupon(BaseModel):
    id: ID; pnr: str; pax_ref: str         # pseudonymous; real name only in PII sources
    flight_id: ID; fare_cents: Cents; taxes_cents: Cents
    channel: Literal["direct", "ota", "agency_gds"] = "direct"
    fare_type: Literal["revenue", "staff_id90"] = "revenue"
    lead_booker: bool = False

class Election(BaseModel):
    coupon_id: str
    kind: Literal["refund", "voucher", "reaccommodated_own", "reroute_partner", "none"]
    new_arrival: UTCDateTime | None = None; arrival_delay_min: int | None = None
    recorded_by: Literal["crm-bot", "service-desk", "web", "call-centre", "occ"]

class CrmEvent(BaseModel):
    id: ID; coupon_id: ID; at: UTCDateTime
    kind: Literal["refund_initiated", "bsp_refund", "chargeback", "voucher_issued",
                  "voucher_in_lieu_of_compensation", "care_issued", "rights_email_sent"]
    amount_cents: Cents = 0
    signed_acceptance_sha256: str | None = None   # Art. 7(3)
    actor: str; text: str

class Claim(BaseModel):
    id: ID; coupon_id: ID; received_at: UTCDateTime
    channel: Literal["direct", "agency"]; agency: str | None = None
    authority: Literal["poa", "assignment", "none"] | None = None
    pnr_scope: Literal["coupon", "pnr"] = "coupon"   # lead booker claiming for the whole PNR
    amount_claimed_cents: Cents
    currency_regime: Literal["EU261", "UK261"] = "EU261"
    text: str                               # raw, PII, may contain injection attempts

class CareCost(BaseModel):
    id: ID; flight_id: ID; kind: Literal["hotel", "meal", "transport"]
    amount_cents: Cents; vendor: str; at: UTCDateTime; invoiced: bool = False

class HistoryCase(BaseModel):              # past human decision WITH its case features (for the miner)
    ruling_id: ID; case_ref: ID; kind: str
    features: dict[str, Any]; decision: str; at: UTCDateTime

class OpeningBalance(BaseModel):            # e.g. the Isha 2024 cohort for Q3
    cohort: str; account: str; entitlement_cents: Cents; claimed_cents: Cents
    balance_cents: Cents; curve_segment: str; as_of: UTCDateTime

class World(BaseModel):
    meta: dict[str, Any]
    airports: list[Airport]; flights: list[Flight]
    tech_log: list[TechLogEntry]; ops_log: list[OpsLogEntry]
    coupons: list[Coupon]; elections: list[Election]
    crm: list[CrmEvent]; claims: list[Claim]; care: list[CareCost] = []
    metar: dict[str, list[MetarObs]]        # key "EIDW@2025-01-24"
    sources: list[Source]
    history_cases: list[HistoryCase] = []
    opening_balances: list[OpeningBalance] = []
    real_context: dict[str, Any] = {}       # {"EIDW@2025-01-24": {"eurocontrol_departures":179,"reported_cancellations_dep":119,"red_warning":"06:00-11:00"}}
    # additive (blackout v1): external events (e.g. a grid outage). Left out of dumps while empty, so every existing
    # world (golden, the full world, the answer key's world_hash) serialises and hashes exactly as before.
    events: list[ExternalEvent] = _Field(default_factory=list, exclude_if=_no_events)

# ---------- engine ----------
class Cause(str, Enum):
    WEATHER = "weather"; TECHNICAL = "technical"; KNOCK_ON = "knock_on"
    CREW = "crew"; ATC = "atc"; CONCURRENT = "concurrent"; UNKNOWN = "unknown"
    EXTERNAL_EVENT = "external_event"       # additive (blackout v1): inside an external event's outage window

class Extraordinary(str, Enum):
    YES = "extraordinary"; NO = "not_extraordinary"; NEEDS_LEGAL = "needs_legal"

class Evidence(BaseModel):
    fact_id: ID; source_id: ID; field: str; value: Any
    quote: str | None = None
    role: Literal["supports", "contradicts", "context"]
    trust_tier: int; struck: bool = False

class Confidence(BaseModel):
    score: float | None                     # None = "uncalibrated" (no model for this decision kind)
    kind: Literal["cause", "voucher", "release", "claim_validity"]
    label: str                              # "cause-finding confidence"
    features: dict[str, float]              # keys from contracts/calibration_schema.json
    caps: list[str] = []                    # shown as separate chips, e.g. "capped:sources-disagree"
    calibration_version: str
    # additive (Justin #12): `features` holds the RAW model inputs, already encoded per calibration_schema.json
    # x-encoding (flags 0/1, margin in hours, precedent count). `contributions` = coef × input per feature, in
    # log-odds; score = logistic(intercept + Σ contributions). Empty / None when the kind is uncalibrated.
    contributions: dict[str, float] = {}
    intercept: float | None = None

class FlightDecision(BaseModel):
    flight_id: ID
    cause: Cause; extraordinary: Extraordinary
    ops_cause_code: str | None; recoded: bool; recode_label: str | None = None   # "71 → 41"
    in_window_dep: Literal["in", "out", "unknown"]; in_window_arr: Literal["in", "out", "unknown"]
    window_margin_min: int | None = None
    confidence: Confidence
    reason: str                             # ONE line
    evidence: list[Evidence]
    rules_applied: list[str]
    legal_basis: list[str]                  # ["EU261 Art.5(3)", "CJEU C-549/07", "CJEU C-257/14"]
    outcome: Literal["auto", "escalated", "human"]
    routed_to: Role | None = None; question_id: ID | None = None
    known_at: UTCDateTime; commit: str | None = None

class Entitlement(BaseModel):
    coupon_id: ID; flight_id: ID
    distance_km: float; band_eur: Literal[250, 400, 600]; band_margin_km: float
    regime: Literal["EU261_2004"] = "EU261_2004"
    compensation_cents: Cents
    reduction: Literal["none", "art7_2_50pct"] = "none"
    refund_due_cents: Cents = 0; refund_already_initiated: bool = False
    care_due: bool = True
    voucher_offset_cents: Cents = 0
    status: Literal["owed", "no_compensation", "held", "needs_ruling", "exempt_notice", "out_of_scope", "staff_ticket"]
    article: str; reason: str; rules_applied: list[str] = []

class WidenOffer(BaseModel):               # additive (asked-again-v1): one rung wider (POST /rules/{rule_id}/widen)
    rule_id: ID
    question: str                           # "Also cover flights arriving into the EU (e.g. BOS→DUB)?"


class AskedAgain(BaseModel):                # additive (asked-again-v1): why a ruled pattern is asked again
    rule_ref: str                           # "R-CL-1@1"
    rule_title: str
    reason: str                             # plain words: the rule's scope, and how this case falls outside it
    widen: WidenOffer | None = None


def _is_none(v: Any) -> bool:
    return v is None


class Question(BaseModel):
    id: ID; case_refs: list[ID]           # one question may cover a whole pattern (e.g. 3 knock-on flights)
    pattern: str                            # "knock_on_return" | "voucher_in_lieu_unsigned" | "cohort_release" | "new_legal_pattern" | ...
    routed_to: Role; asked_at: UTCDateTime
    title: str; found: str; why_flagged: str; recommends: str
    recommended_option: str; options: list[str]
    evidence: list[Evidence]; confidence: Confidence
    reason_tag: Literal["no-precedent", "sources-disagree", "out-of-scope", "release-proposal", "concurrent-causes", "new-legal-pattern"]
    holds: list[ID] = []; holds_cents: Cents = 0
    status: Literal["open", "answered", "reminded"] = "open"     # view over events
    remind_at: UTCDateTime | None = None
    # additive (Justin #4): other cases in the same storm run settled automatically while this question waits
    # ("Waiting on Claims Lead 3h · reminder sent · N others settled")
    others_settled: int = 0
    # additive (Justin #11): the rule or proposal a "Reject" on this question targets (POST /rules/{id}/reject);
    # None → answer the question with its reject option instead
    proposal_rule_id: ID | None = None
    # additive (asked-again-v1): read-time view only, never committed. Set when the case falls outside the SCOPE of
    # an active rule for the same pattern ("asks instead of stretching your ruling"); left out of dumps while None,
    # so every committed question payload and hash is byte-identical.
    asked_again: AskedAgain | None = _Field(default=None, exclude_if=_is_none)

class Ruling(BaseModel):
    id: ID; question_id: ID | None = None
    author_role: Role; author: str
    kind: Literal["answer", "rejection", "override", "challenge_response"]
    decision: str; explanation: str; at: UTCDateTime

class RuleAction(str, Enum):
    SET_EXTRAORDINARY = "set_extraordinary"; SET_NOT_EXTRAORDINARY = "set_not_extraordinary"
    ALLOW_OFFSET = "allow_offset"; DENY_OFFSET = "deny_offset"
    DENY_RELEASE = "deny_release"; KEEP_TAIL = "keep_tail"
    APPLY_7_2_REDUCTION = "apply_7_2_reduction"; ROUTE_TO = "route_to"

class Rule(BaseModel):
    id: ID; version: int
    kind: Literal["cause", "entitlement", "voucher", "release", "routing", "regime", "mined_policy"]
    scope: dict[str, Any]                   # values grounded or tagged "case:<value>"
    condition: dict[str, Any]               # DSL (CONTRACTS §4)
    action: RuleAction; action_arg: str | None = None   # e.g. ROUTE_TO -> "legal"; never a cents literal
    tier: Literal["hard_control", "regulation", "legal_ruling", "controller_ruling", "claims_lead_ruling", "mined"]
    authority_required: Role
    origin_ruling_id: str | None = None; origin_example: str | None = None
    grounding: dict[str, str] = {}          # literal value (condition AND scope) -> phrase in the ruling
    support: str | None = None              # mined: "41 of 42"
    valid_from: UTCDateTime | None             # None = legal interpretation (applies to past flights)
    recorded_at: UTCDateTime
    status: Literal["proposed", "shadow", "active", "suspect", "retired"]   # view over events
    supersedes: str | None = None
    times_cited: int = 0                    # view over events
    static_card: bool = False               # e.g. Reg 2026/2202 (display only, no logic)
    title: str | None = None                # additive (D0a): plain-language card title, e.g. the ruling sentence or regulation name
    origin_quote: str | None = None         # additive (Justin #13): the ruler's own words (or the regulation's text)
    cases_settled_by_storm: dict[str, int] = {}   # additive (Justin #6): storm id → cases settled citing this rule

class ReplayFlip(BaseModel):
    entity_id: str; field: str; before: Any; after: Any; delta_cents: Cents = 0

class ReplayDiff(BaseModel):
    rule_ref: str; known_at: UTCDateTime
    flips: list[ReplayFlip]; total_delta_cents: Cents
    locked_periods_untouched: list[str] = []; adjustment_je_ids: list[str] = []

class RuleProposal(BaseModel):
    rule: Rule
    checks: dict[str, bool]                 # compiles, reproduces_case, no_hard_control, grounded, author_has_authority, no_conflict
    would_flip: ReplayDiff
    widen_next: dict[str, Any] | None = None

class Draft(BaseModel):                     # any LLM prose (letters, memos, explanations)
    id: str; kind: Literal["explanation", "rights_notice", "je_memo", "challenge_reply", "rule_draft"]
    text: str; numbers_verified: bool       # every number in text appears in the evidence; else template used
    llm_commit: str | None = None; template_fallback: bool = False

class Commit(BaseModel):
    hash: str; parent: str | None
    kind: Literal["fact", "decision", "entitlement", "question", "ruling", "rule_event", "journal_event",
                  "period_lock", "revert", "access_denied", "llm_call", "clock"]
    at: UTCDateTime; actor: str
    payload_hash: str; payload_ref: str
    inputs: list[str] = []                  # fact/rule hashes + "engine@<git-sha>" + "cal@<version>"
    message: str
    recorded_at: UTCDateTime | None = None  # additive (Justin #15): when the commit was written (`at` = event time)

class BlameStep(BaseModel):
    commit: Commit; label: str; quote: str | None = None

class Blame(BaseModel):
    target: str; steps: list[BlameStep]

# ---------- books ----------
class JournalLine(BaseModel):
    account: str; account_name: str
    dr_cents: Cents = 0; cr_cents: Cents = 0
    dims: dict[str, str] = {}               # storm, flight, segment, cohort

class JournalEntry(BaseModel):
    id: ID; event_date: date; period: str  # period follows event_date (cut-off), not commit date
    memo: str; lines: list[JournalLine]
    kind: Literal["sale", "refund", "voucher", "reroute_fim", "compensation_estimate", "claim_approved", "claim_paid",
                  "change_in_estimate", "derecognition", "care_accrual", "care_invoice", "recode",
                  "out_of_period_adjustment", "voucher_in_lieu", "voucher_void"]
    ias8_class: Literal["none", "change_in_estimate", "prior_period_error"] = "none"
    reverses: str | None = None; estimate_ref: str | None = None
    source_decision_id: str | None = None
    status: Literal["draft", "approved", "posted"]          # view over events; StormCheck never posts beyond "approved" (parked)
    preparer: str; approver: str | None = None
    built_from: int = 0; ties_to: list[str] = []
    approver_role: Role | None = None       # additive (server): who must approve it (claims_lead: payouts, controller: JEs)
    period_locked: bool = False             # additive (server): its period is locked (nothing more is written to it)

class RollforwardRow(BaseModel):
    cohort: str
    opening_cents: Cents; new_cents: Cents; claims_approved_cents: Cents; settled_in_kind_cents: Cents = 0
    change_in_estimate_cents: Cents; recode_cents: Cents = 0; out_of_period_cents: Cents = 0
    derecognised_cents: Cents = 0; closing_cents: Cents
    unclaimed_entitlement_cents: Cents
    je_ids: list[str] = []                  # additive (Justin #18): journal entries behind this row (may be empty)

class Rollforward(BaseModel):
    period: str; account: Literal["2140"] = "2140"
    rows: list[RollforwardRow]; closing_total_cents: Cents
    gl_balance_cents: Cents; ties_to_gl: bool
    locked: bool = False                    # additive (Justin #16): the period is locked

class ClaimCurve(BaseModel):
    segment: Literal["long_haul_gt3500", "medium_1500_3500", "short_le1500"]
    basis: Literal["eur"] = "eur"
    points: list[tuple[int, float]]         # (months since event; M1 = first month-end >=28 days after), cumulative valid-claim rate
    n_by_point: list[int]
    observed_through_month: int             # e.g. 18
    ultimate: float; tail_factor: float
    tail_note: str = "months 18–72 beyond history: documented judgment (Steer 2020 benchmark 18% for cancellations)"
    version: str

class EstimateCard(BaseModel):
    cohort: str; segment: str; pax: int; entitlement_cents: Cents
    curve_version: str; months_developed: int
    expected_loss_cents: Cents; bf_cents: Cents; chain_ladder_cents: Cents; selected: Literal["bf", "expected_loss", "chain_ladder"]
    actual_vs_expected: float | None; credibility_z: float | None
    sensitivity_5pp_cents: Cents
    constraint_note: str; ias8_class: str; preparer: str; approver: str | None

class InvariantResult(BaseModel):
    id: str; description: str; ok: bool; detail: str = ""

class CfoMetrics(BaseModel):
    as_of: UTCDateTime
    cash_basis_cents: Cents; full_entitlement_cents: Cents; drafted_liability_cents: Cents; sensitivity_5pp_cents: Cents
    method_range_cents: tuple[Cents, Cents]
    held_for_legal_cents: Cents
    liability_bridge: list[RollforwardRow]
    recodes_count: int; recodes_cents: Cents
    refunds_within_7d_pct: float
    vouchers_outstanding_cents: Cents
    care_accrued_cents: Cents; care_invoiced_cents: Cents
    cohort: str | None = None               # additive (Justin #19): the cohort the bridge describes (None = all)
    refund_vouchers_outstanding_cents: Cents = 0        # additive (server): GL 2131, of vouchers_outstanding_cents
    compensation_vouchers_outstanding_cents: Cents = 0  # additive (server): GL 2132, of vouchers_outstanding_cents

# ---------- API views ----------
class TraceEvent(BaseModel):
    seq: int; at: UTCDateTime
    kind: Literal["fact", "decision", "entitlement", "question", "ruling", "rule", "journal", "replay",
                  "access_denied", "reminder", "llm_call", "info"]
    actor: str; summary: str                # past tense, "NS31 recoded 71 → 41 · 172 payouts drafted"
    ref: str | None = None
    chip: Literal["APPLIED", "DRAFTED", "HELD", "DENIED", "ASKED", "RULED", "LEARNED", "CITED", "LOCKED", "INFO"]
    amount_cents: Cents | None = None

class FlightRow(BaseModel):
    flight: Flight; decision: FlightDecision | None

class LearnedItem(BaseModel):
    text: str; support: str | None = None; rule_ref: str | None = None

class StormRun(BaseModel):
    id: ID; station: str; date: date
    windows: list[StormWindow]; metar: list[MetarObs]
    flights: list[FlightRow]                # cancelled + operated
    counters: dict[str, int]                # passengers, cancelled, operated, drafted, held, questions, people, repeat_questions, rules_cited
    entitlement_cents: Cents; liability_drafted_cents: Cents
    learned: list[LearnedItem]              # the "Learns" strip
    questions: list[Question]; feed: list[TraceEvent]
    real_context: dict[str, Any] = {}
    message: str | None = None              # e.g. "max gust 18 kt · no storm window"
    airports: list[Airport] = []            # additive (D0a): every airport referenced by flights (map coordinates, tz, eu)
    name: str | None = None                 # additive (Justin #3): "Storm Éowyn" (from real_context.storm_name)
    event_id: str | None = None             # additive (blackout v1): the ExternalEvent this run covers, if any

TimelineKind = Literal["tech_log", "mcc", "occ", "spares", "metar", "window_start", "window_end",
                       "metar_window_start", "metar_window_end", "crm", "operated", "schedule", "pss", "claim",
                       "care", "warning", "email", "injection", "challenge", "ruling", "info"]


class TimelineItem(BaseModel):              # additive (Justin #9): one mark on the Flight File timeline
    model_config = ConfigDict(extra="allow")
    at: UTCDateTime; kind: TimelineKind
    label: str | None = None                # short UI label, e.g. "Tech log EI-NSB · AOG"
    text: str | None = None                 # verbatim source text (METAR raw, log line) or a count summary
    source_id: str | None = None            # the document it quotes
    trust_tier: int | None = None


class EntitlementsSummary(BaseModel):       # additive (Justin #5/#10): every key a Flight File summary may carry
    model_config = ConfigDict(extra="allow")
    coupons: int | None = None
    distance_km: float | None = None; band_eur: int | None = None; band_margin_km: float | None = None
    band_label: str | None = None           # "4,804 km · 1,304 km over the €600 threshold"
    band_note: str | None = None            # same as band_label (D0a name)
    compensation_cents: Cents | None = None         # Σ compensation_cents over the flight's coupons
    owed: int | None = None; needs_ruling: int | None = None; held: int | None = None   # status counts
    full_entitlement_cents: Cents | None = None     # full Art. 7 entitlement if every passenger claims (owed + needs_ruling + held)
    full_entitlement_label: str | None = None       # "€99,000 full Art. 7 entitlement if every passenger claims"
    drafted_liability_cents: Cents | None = None    # Σ accruing entitlement × the segment's expected ultimate claim rate
    liability_drafted_cents: Cents | None = None    # same (D0a name)
    claim_rate: float | None = None                 # expected ultimate claim rate used, e.g. 0.35
    expected_ultimate_claim_rate: float | None = None   # same (D0a name)
    claim_rate_label: str | None = None             # "35% expected ultimate claim rate (history to M18 + tail judgment)"
    status_counts: dict[str, int] | None = None     # {"owed": 171, "needs_ruling": 1}
    statuses: list[dict[str, Any]] | None = None    # [{"status","count","label"}]
    status_line: str | None = None                  # one sentence, plan §9 wording
    elections: dict[str, int] | None = None         # {"refund": 32, "voucher": 14, ...}
    compensation_breakdown: list[dict[str, Any]] | None = None  # [{"band_eur","reduction","count","each_cents","total_cents"}]
    formula: str | None = None                      # "158 × €600 + 14 × €300 (Art. 7(2)(c))"
    reduction_7_2: dict[str, Any] | None = None     # {"count","saved_cents","rules"}
    reduced: int | None = None
    refunds_already_initiated: int | None = None; refund_due_cents: Cents | None = None
    voucher_offset_cents: Cents | None = None
    claims_received: int | None = None; care_due: bool | None = None
    accrued_cents: Cents | None = None; accrual_basis: str | None = None   # held flights: the IFRS 15.56 accrual
    compensation_if_owed_cents: Cents | None = None; question_id: str | None = None
    headline: str | None = None


def _check_summary(v: dict[str, Any]) -> dict[str, Any]:
    EntitlementsSummary.model_validate(v)   # documented keys must have their types; the dict itself is kept
    return v


def _check_timeline(v: list[dict[str, Any]]) -> list[dict[str, Any]]:
    for item in v:
        TimelineItem.model_validate(item)
    return v


# Runtime stays a plain dict / list of dicts (readers index them); validation and the published JSON Schema are typed.
SummaryDict = Annotated[dict[str, Any], AfterValidator(_check_summary),
                        WithJsonSchema(EntitlementsSummary.model_json_schema(mode="serialization"))]
TimelineList = Annotated[list[dict[str, Any]], AfterValidator(_check_timeline),
                         WithJsonSchema({"type": "array", "items": TimelineItem.model_json_schema(mode="serialization")})]


class FlightFile(BaseModel):
    flight: Flight; decision: FlightDecision
    entitlements_summary: SummaryDict; sample_entitlements: list[Entitlement]   # keys: EntitlementsSummary
    journal_preview: list[JournalEntry]
    timeline: TimelineList                  # ordered marks; items: TimelineItem (typed, Justin #9)
    handoff: dict[str, Any] | None = None   # {"refunds_already_initiated":32,"not_repeated":true,"rights_notices_drafted":32,"drafter_pii_seen":0}
    explanation: Draft | None = None

class ChallengeRequest(BaseModel):
    text: str

class ChallengeResponse(BaseModel):
    classification: Literal["assertion", "new_fact", "new_legal_pattern"]
    decision_stands: bool; reply: Draft
    cited: list[Evidence]; question: Question | None = None

class AnswerRequest(BaseModel):
    decision: str; explanation: str

class AnswerResponse(BaseModel):
    ruling: Ruling; proposal: RuleProposal | None

class InjectRequest(BaseModel):
    kind: Literal["tech_log", "claim", "crm", "email", "occ_log", "manufacturer"]
    text: str; flight_id: str | None = None

class InjectResponse(BaseModel):
    source: Source; facts: list[Fact]; dropped_unverifiable: int
    events: list[TraceEvent]; affected: list[str]
    fallback_used: bool = False; message: str | None = None

class Injection(BaseModel):                 # rehearsed judge scenarios (GET /api/injections)
    id: ID; title: str; request: InjectRequest; expected: str

class DeskRequest(BaseModel):
    icao: str; date: date                   # local date at that airport

class AccessDecision(BaseModel):
    at: UTCDateTime; principal: str; action: str; resource: str; allowed: bool; reason: str

class AccessMatrix(BaseModel):
    principals: list[str]; resources: list[str]
    cells: dict[str, dict[str, Literal["read", "write", "approve", "none", "redacted"]]]

class ControlMapping(BaseModel):
    control: str; framework_ref: str        # "CC6.1" (SOC 2 mapping; not a certification claim)
    implemented_by: str; evidence_endpoint: str

class EvalReport(BaseModel):
    split: dict[str, str]; n_storms: int; n_passengers: int
    straight_through_pct: float
    miscodes_caught: int; miscodes_total: int; miscodes_eur_cents: Cents
    false_holds: int; repeat_questions: int; out_of_scope_auto: int
    liability_vs_actual: dict[str, float]
    calibration: dict[str, list[dict[str, float]]]   # per Confidence.kind: bins {lo,hi,n,accuracy,wilson_lo,wilson_hi}
    coverage_at_90: dict[str, float]
    baseline: dict[str, Any]                # {"model","runs":3,"liability_eur":[a,b,c],"cause_accuracy":[..],"hash_identical":false}
    stormcheck_runs: dict[str, Any]         # {"runs":3,"liability_eur":[34650,34650,34650],"hash_identical":true}
    injections: dict[str, int]
    real_vs_simulated: dict[str, list[str]]
    label: str = "calibrated on synthetic labels; validates the pipeline, not the world"


World.model_rebuild()


# ---------- API envelopes (additive, D0a: CONTRACTS §3 shapes that had no model) ----------
class TraceAnchor(BaseModel):               # additive (server): the published head of the commit chain
    head: str | None; count: int            # `make verify --expect-head <head>:<count>` checks it later
    text: str                               # "head 1a2b3c4d5e6f · 412 commits"

class Health(BaseModel):                    # GET /health
    ok: bool; mode: str                     # mode: STORMCHECK_MODE (live|cache|offline) or "stub"
    impl: dict[str, str] = {}               # {"engine","world","reader","drafter","books"} -> "fake" | "real" | "stub"
    anchor: TraceAnchor | None = None       # additive (server); also the X-Trace-Head / X-Trace-Commits headers
    trace_write_failures: int = 0           # additive (server): trace writes that failed since boot/reset (ok=false)

class StormSummary(BaseModel):              # GET /storms item
    id: ID; station: str; date: date
    cancelled: int; questions: int; liability_drafted_cents: Cents

class SessionRequest(BaseModel):            # POST /session
    role: Role; name: str

class SessionResponse(BaseModel):
    token: str; session: Session

class ConfirmResponse(BaseModel):           # POST /proposals/{rule_id}/confirm
    rule: Rule; replay: ReplayDiff

class RejectRequest(BaseModel):             # POST /rules/{rule_id}/reject
    explanation: str

class PeriodRequest(BaseModel):             # POST /books/month-end, POST /books/lock
    period: str                             # "2025-02"

class MonthEndResponse(BaseModel):
    entries: list[JournalEntry]; rollforward: Rollforward; estimate: EstimateCard

class LockResponse(BaseModel):
    locked: str                             # the period now locked, e.g. "2025-01"

class ClockRequest(BaseModel):              # POST /clock (forward-only)
    known_at: UTCDateTime

class ClockMark(BaseModel):                 # additive (server, Justin #2): a named moment the demo moves through
    at: UTCDateTime; label: str             # "Iberian blackout · 28 Apr 2025"
    note: str | None = None
    # additive (asked-again-v1): the storm run this mark runs ("EIDW@2025-01-26"); left out of dumps while None
    run_id: ID | None = _Field(default=None, exclude_if=_is_none)

class ClockResponse(BaseModel):
    known_at: UTCDateTime
    marks: list[ClockMark] = []             # additive (Justin #2): GET /clock serves them; earlier ones have passed

class OkResponse(BaseModel):                # POST /reset
    ok: bool

# ---------- pitch insights (additive, insights-v1): computed on read from a run's real data, never stored ----------
class EffortLine(BaseModel):                # one task of a storm run, by hand vs with StormCheck
    task: str                               # "Find what really caused each cancellation"
    role: str                               # "ops analyst" | "claims handler" | "in-house counsel" | "revenue accountant"
    basis: str                              # plain words: "27 flights × 1.5 h"
    manual_hours: float
    with_stormcheck_hours: float
    rate_eur_per_hour: int                  # loaded cost
    source: str | None = None               # citation for the assumption, if any

class EffortEstimate(BaseModel):            # GET /runs/{run_id}/effort
    run_id: str
    name: str                               # "Storm Éowyn · 24 Jan 2025"
    inputs: dict[str, int]                  # cancelled_flights, passengers, expected_claims, questions, refunds, cohorts, month_ends
    lines: list[EffortLine]
    manual_hours: float; with_stormcheck_hours: float; hours_saved: float          # totals rounded to the nearest 5 h
    manual_cost_cents: Cents; with_stormcheck_cost_cents: Cents; cost_saved_cents: Cents   # rounded to the nearest €100
    errors_caught: list[dict[str, Any]]     # [{label, amount_cents (int | None), detail}] from the run, never invented
    assumptions_note: str                   # "Estimate from the assumptions below; not measured at a real airline."

class RuleReuse(BaseModel):
    rule_ref: str                           # "R-CL-1@1"
    title: str                              # "No signed acceptance, no offset"
    learned_from: str                       # "Claims Lead ruling on Storm Éowyn (Q-1)" | "18 months of history (41 of 42)"
    cases: int                              # cases this rule settled on this run, with no question asked

class LearningStep(BaseModel):              # GET /learning item: one storm or event run the clock has reached
    run_id: str; name: str; known_at: UTCDateTime
    questions_asked: int                    # new questions this run raised
    cases_settled_by_reused_rules: int
    reused: list[RuleReuse]
    new_rules: list[str]                    # rule refs first confirmed on this run
    note: str                               # one plain sentence or two

class ErrorBody(BaseModel):
    code: Literal["sod_violation", "forbidden", "not_found", "validation", "upstream",
                  "no_metar", "future_date", "unknown_airport"]
    message: str                            # plain sentence, safe to show in the UI

class ErrorEnvelope(BaseModel):             # every 4xx body: {"error": {"code", "message"}}
    error: ErrorBody
