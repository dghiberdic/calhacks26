// Hand-written mirror of contracts/models.py (CONTRACTS.md §1) until `pnpm gen:api` can read
// contracts/openapi.json. Field names and literals are copied exactly. Fields with a Pydantic default
// are optional here, as openapi-typescript will generate them. Money is integer euro cents; times are
// UTC ISO-8601 strings with `Z`; dates are `YYYY-MM-DD`.

export type Cents = number;
export type ISODateTime = string;
export type ISODate = string;

export type Role =
  | "claims_lead"
  | "legal"
  | "controller"
  | "ops"
  | "cfo"
  | "judge"
  | "agent.reader"
  | "agent.drafter"
  | "agent.engine"
  | "agent.crm_bot";

export type Session = { principal: string; role: Role; name: string; issued_at: ISODateTime };

// ---------- raw world ----------
export type SourceKind =
  | "metar"
  | "schedule"
  | "occ_log"
  | "mcc_log"
  | "tech_log"
  | "spares"
  | "manifest"
  | "pss"
  | "crm"
  | "bsp"
  | "claim"
  | "email"
  | "regulation"
  | "ruling"
  | "manufacturer"
  | "challenge"
  /** Additive (D0b): GL extracts, care accrual sheets, vendor invoices. */
  | "finance";

export type Source = {
  id: string;
  kind: SourceKind;
  title: string;
  text?: string | null;
  sha256: string;
  received_at: ISODateTime;
  /** 1 tech log/METAR/MCC · 2 schedule/manifest/PSS/BSP · 3 OCC batch code/CRM · 4 passenger/agency/challenge */
  trust_tier: number;
  acl_tags?: string[];
  uri?: string | null;
};

export type Fact = {
  id: string;
  source_id: string;
  subject: string;
  field: string;
  value: unknown;
  span?: string | null;
  extractor: string;
  extract_conf?: number | null;
  valid_at?: ISODateTime | null;
  recorded_at: ISODateTime;
  acl_tags?: string[];
};

export type MetarObs = {
  station: string;
  valid: ISODateTime;
  sknt?: number | null;
  gust?: number | null;
  drct?: number | null;
  vsby_sm?: number | null;
  wxcodes?: string | null;
  raw: string;
};

export type StormWindow = {
  station: string;
  start: ISODateTime;
  end: ISODateTime;
  peak_gust_kt: number;
  definition?: string;
  obs_count?: number;
};

export type Airport = { icao: string; iata: string; name: string; lat: number; lon: number; country: string; eu: boolean; tz: string };

export type FlightStatus = "operated" | "cancelled" | "delayed";

export type Flight = {
  id: string;
  number: string;
  date: ISODate;
  origin: string;
  dest: string;
  sched_dep: ISODateTime;
  sched_arr: ISODateTime;
  aircraft: string;
  status: FlightStatus;
  actual_dep?: ISODateTime | null;
  actual_arr?: ISODateTime | null;
  pax: number;
  ops_cause_code?: string | null;
  inbound_flight_id?: string | null;
  outbound_pair_id?: string | null;
  notified_at?: ISODateTime | null;
  operating_carrier_eu?: boolean;
};

export type TechLogEntry = {
  id: string;
  aircraft: string;
  logged_at: ISODateTime;
  station: string;
  ata: string;
  text: string;
  mel_relief?: boolean | null;
  aog: boolean;
  rts_est?: ISODateTime | null;
};

export type OpsLogEntry = {
  id: string;
  at: ISODateTime;
  kind: "occ" | "mcc" | "spares";
  flight_ids?: string[];
  code?: string | null;
  text: string;
  author: string;
};

// ---------- engine ----------
export type Cause = "weather" | "technical" | "knock_on" | "crew" | "atc" | "concurrent" | "unknown";
export type Extraordinary = "extraordinary" | "not_extraordinary" | "needs_legal";
export type InWindow = "in" | "out" | "unknown";

export type Evidence = {
  fact_id: string;
  source_id: string;
  field: string;
  value: unknown;
  quote?: string | null;
  role: "supports" | "contradicts" | "context";
  trust_tier: number;
  struck?: boolean;
};

export type ConfidenceKind = "cause" | "voucher" | "release" | "claim_validity";

export type Confidence = {
  /** null = "uncalibrated" (no model for this decision kind) */
  score: number | null;
  kind: ConfidenceKind;
  label: string;
  features: Record<string, number>;
  caps?: string[];
  calibration_version: string;
  /** Additive (#12): coefficient × input per feature, in log-odds; score = logistic(intercept + Σ contributions). */
  contributions?: Record<string, number>;
  intercept?: number | null;
};

export type FlightDecision = {
  flight_id: string;
  cause: Cause;
  extraordinary: Extraordinary;
  ops_cause_code: string | null;
  recoded: boolean;
  recode_label?: string | null;
  in_window_dep: InWindow;
  in_window_arr: InWindow;
  window_margin_min?: number | null;
  confidence: Confidence;
  reason: string;
  evidence: Evidence[];
  rules_applied: string[];
  legal_basis: string[];
  outcome: "auto" | "escalated" | "human";
  routed_to?: Role | null;
  question_id?: string | null;
  known_at: ISODateTime;
  commit?: string | null;
};

export type EntitlementStatus = "owed" | "no_compensation" | "held" | "needs_ruling" | "exempt_notice" | "out_of_scope" | "staff_ticket";

export type Entitlement = {
  coupon_id: string;
  flight_id: string;
  distance_km: number;
  band_eur: 250 | 400 | 600;
  band_margin_km: number;
  regime?: "EU261_2004";
  compensation_cents: Cents;
  reduction?: "none" | "art7_2_50pct";
  refund_due_cents?: Cents;
  refund_already_initiated?: boolean;
  care_due?: boolean;
  voucher_offset_cents?: Cents;
  status: EntitlementStatus;
  article: string;
  reason: string;
  rules_applied?: string[];
};

export type ReasonTag = "no-precedent" | "sources-disagree" | "out-of-scope" | "release-proposal" | "concurrent-causes" | "new-legal-pattern";

export type Question = {
  id: string;
  case_refs: string[];
  pattern: string;
  routed_to: Role;
  asked_at: ISODateTime;
  title: string;
  found: string;
  why_flagged: string;
  recommends: string;
  recommended_option: string;
  options: string[];
  evidence: Evidence[];
  confidence: Confidence;
  reason_tag: ReasonTag;
  holds?: string[];
  holds_cents?: Cents;
  status?: "open" | "answered" | "reminded";
  remind_at?: ISODateTime | null;
  /** Additive (contracts/requests/justin.md #4): cases the same pattern settled since it was asked. */
  others_settled?: number;
  /** Additive (#11): the pending proposal a release question is about, when there is one. */
  proposal_rule_id?: string | null;
};

export type Ruling = {
  id: string;
  question_id?: string | null;
  author_role: Role;
  author: string;
  kind: "answer" | "rejection" | "override" | "challenge_response";
  decision: string;
  explanation: string;
  at: ISODateTime;
};

export type RuleAction =
  | "set_extraordinary"
  | "set_not_extraordinary"
  | "allow_offset"
  | "deny_offset"
  | "deny_release"
  | "keep_tail"
  | "apply_7_2_reduction"
  | "route_to";

export type RuleTier = "hard_control" | "regulation" | "legal_ruling" | "controller_ruling" | "claims_lead_ruling" | "mined";
export type RuleStatus = "proposed" | "shadow" | "active" | "suspect" | "retired";

/** Rule DSL (CONTRACTS §4): {"all":[...]} / {"any":[...]} / {"not":clause}; clause = {f, op, v}. */
export type DslClause = { f: string; op: "eq" | "ne" | "lt" | "le" | "gt" | "ge" | "in" | "nin" | "exists"; v?: unknown };
export type DslNode = DslClause | { all: DslNode[] } | { any: DslNode[] } | { not: DslNode };

export type Rule = {
  id: string;
  version: number;
  kind: "cause" | "entitlement" | "voucher" | "release" | "routing" | "regime" | "mined_policy";
  scope: Record<string, unknown>;
  condition: Record<string, unknown>;
  action: RuleAction;
  action_arg?: string | null;
  tier: RuleTier;
  authority_required: Role;
  origin_ruling_id?: string | null;
  origin_example?: string | null;
  grounding?: Record<string, string>;
  support?: string | null;
  valid_from: ISODateTime | null;
  recorded_at: ISODateTime;
  status: RuleStatus;
  supersedes?: string | null;
  times_cited?: number;
  static_card?: boolean;
  /** Additive (D0a): plain-language card title (the ruling sentence, a regulation's name, a hard control). */
  title?: string | null;
  /** Additive (#13): the ruler's own words; the static 2026/2202 card carries its text here. */
  origin_quote?: string | null;
  /** Additive (#6): cases each storm settled by citing this rule, e.g. {"EIDW@2025-01-24": 23}. */
  cases_settled_by_storm?: Record<string, number>;
};

export type ReplayFlip = { entity_id: string; field: string; before: unknown; after: unknown; delta_cents?: Cents };

export type ReplayDiff = {
  rule_ref: string;
  known_at: ISODateTime;
  flips: ReplayFlip[];
  total_delta_cents: Cents;
  locked_periods_untouched?: string[];
  adjustment_je_ids?: string[];
};

export type RuleProposal = {
  rule: Rule;
  /** compiles, reproduces_case, no_hard_control, grounded, author_has_authority, no_conflict */
  checks: Record<string, boolean>;
  would_flip: ReplayDiff;
  widen_next?: Record<string, unknown> | null;
};

export type Draft = {
  id: string;
  kind: "explanation" | "rights_notice" | "je_memo" | "challenge_reply" | "rule_draft";
  text: string;
  numbers_verified: boolean;
  llm_commit?: string | null;
  template_fallback?: boolean;
};

export type CommitKind =
  | "fact"
  | "decision"
  | "entitlement"
  | "question"
  | "ruling"
  | "rule_event"
  | "journal_event"
  | "period_lock"
  | "revert"
  | "access_denied"
  | "llm_call"
  | "clock";

export type Commit = {
  hash: string;
  parent: string | null;
  kind: CommitKind;
  at: ISODateTime;
  actor: string;
  payload_hash: string;
  payload_ref: string;
  inputs?: string[];
  message: string;
  /** Additive (#15): when the commit was written, beside the event time. */
  recorded_at?: ISODateTime | null;
};

export type BlameStep = { commit: Commit; label: string; quote?: string | null };
export type Blame = { target: string; steps: BlameStep[] };

// ---------- books ----------
export type JournalLine = { account: string; account_name: string; dr_cents?: Cents; cr_cents?: Cents; dims?: Record<string, string> };

export type JournalKind =
  | "sale"
  | "refund"
  | "voucher"
  | "reroute_fim"
  | "compensation_estimate"
  | "claim_approved"
  | "claim_paid"
  | "change_in_estimate"
  | "derecognition"
  | "care_accrual"
  | "care_invoice"
  | "recode"
  | "out_of_period_adjustment"
  | "voucher_in_lieu"
  | "voucher_void";

export type JournalEntry = {
  id: string;
  event_date: ISODate;
  period: string;
  memo: string;
  lines: JournalLine[];
  kind: JournalKind;
  ias8_class?: "none" | "change_in_estimate" | "prior_period_error";
  reverses?: string | null;
  estimate_ref?: string | null;
  source_decision_id?: string | null;
  status: "draft" | "approved" | "posted";
  preparer: string;
  approver?: string | null;
  built_from?: number;
  ties_to?: string[];
};

export type RollforwardRow = {
  cohort: string;
  opening_cents: Cents;
  new_cents: Cents;
  claims_approved_cents: Cents;
  settled_in_kind_cents?: Cents;
  change_in_estimate_cents: Cents;
  recode_cents?: Cents;
  out_of_period_cents?: Cents;
  derecognised_cents?: Cents;
  closing_cents: Cents;
  unclaimed_entitlement_cents: Cents;
};

export type Rollforward = {
  period: string;
  account?: "2140";
  rows: RollforwardRow[];
  closing_total_cents: Cents;
  gl_balance_cents: Cents;
  ties_to_gl: boolean;
  /** Additive (#16): the period is locked. */
  locked?: boolean;
};

export type CurveSegment = "long_haul_gt3500" | "medium_1500_3500" | "short_le1500";

export type ClaimCurve = {
  segment: CurveSegment;
  basis?: "eur";
  /** (months since event; M1 = first month-end >=28 days after), cumulative valid-claim rate */
  points: [number, number][];
  n_by_point: number[];
  observed_through_month: number;
  ultimate: number;
  tail_factor: number;
  tail_note?: string;
  version: string;
};

export type EstimateCard = {
  cohort: string;
  segment: string;
  pax: number;
  entitlement_cents: Cents;
  curve_version: string;
  months_developed: number;
  expected_loss_cents: Cents;
  bf_cents: Cents;
  chain_ladder_cents: Cents;
  selected: "bf" | "expected_loss" | "chain_ladder";
  actual_vs_expected: number | null;
  credibility_z: number | null;
  sensitivity_5pp_cents: Cents;
  constraint_note: string;
  ias8_class: string;
  preparer: string;
  approver: string | null;
};

export type InvariantResult = { id: string; description: string; ok: boolean; detail?: string };

export type CfoMetrics = {
  as_of: ISODateTime;
  cash_basis_cents: Cents;
  full_entitlement_cents: Cents;
  drafted_liability_cents: Cents;
  sensitivity_5pp_cents: Cents;
  method_range_cents: [Cents, Cents];
  held_for_legal_cents: Cents;
  liability_bridge: RollforwardRow[];
  recodes_count: number;
  recodes_cents: Cents;
  refunds_within_7d_pct: number;
  vouchers_outstanding_cents: Cents;
  care_accrued_cents: Cents;
  care_invoiced_cents: Cents;
  /** Additive (#19): the cohort these figures describe, e.g. "EIDW@2025-01-24". */
  cohort?: string | null;
};

// ---------- API views ----------
export type TraceKind =
  | "fact"
  | "decision"
  | "entitlement"
  | "question"
  | "ruling"
  | "rule"
  | "journal"
  | "replay"
  | "access_denied"
  | "reminder"
  | "llm_call"
  | "info";

export type TraceChip = "APPLIED" | "DRAFTED" | "HELD" | "DENIED" | "ASKED" | "RULED" | "LEARNED" | "CITED" | "LOCKED" | "INFO";

export type TraceEvent = {
  seq: number;
  at: ISODateTime;
  kind: TraceKind;
  actor: string;
  /** past tense, e.g. "NS31 recoded 71 → 41 · 172 payouts drafted" */
  summary: string;
  ref?: string | null;
  chip: TraceChip;
  amount_cents?: Cents | null;
};

export type FlightRow = { flight: Flight; decision: FlightDecision | null };
export type LearnedItem = { text: string; support?: string | null; rule_ref?: string | null };

export type StormRun = {
  id: string;
  station: string;
  date: ISODate;
  windows: StormWindow[];
  metar: MetarObs[];
  flights: FlightRow[];
  /** passengers, cancelled, operated, drafted, held, questions, people, repeat_questions, rules_cited */
  counters: Record<string, number>;
  entitlement_cents: Cents;
  liability_drafted_cents: Cents;
  learned: LearnedItem[];
  questions: Question[];
  feed: TraceEvent[];
  real_context?: Record<string, unknown>;
  message?: string | null;
  /** Additive (D0a): every airport the flights reference (map coordinates, tz, eu). */
  airports?: Airport[];
  /** Additive (#3): "Storm Éowyn", from real_context.storm_name. */
  name?: string | null;
};

export type StormSummary = { id: string; station: string; date: ISODate; cancelled: number; questions: number; liability_drafted_cents: Cents };

/** One timeline mark on the Flight File strip (tech log → MCC → OCC → METAR marks → CRM). Loosely typed by the contract. */
/** Kinds of Flight File timeline mark (CONTRACTS TimelineKind; Justin request #9). */
export type TimelineKind =
  | "tech_log" | "mcc" | "occ" | "spares" | "metar" | "window_start" | "window_end" | "metar_window_start" | "metar_window_end"
  | "crm" | "operated" | "schedule" | "pss" | "claim" | "care" | "warning" | "email" | "injection" | "challenge" | "ruling" | "info";
/** One mark on the Flight File timeline (TimelineItem; extra keys allowed). */
export type TimelineMark = {
  at?: ISODateTime;
  kind?: TimelineKind | (string & {});
  label?: string | null;
  text?: string | null;
  source_id?: string | null;
  trust_tier?: number | null;
  [key: string]: unknown;
};

export type FlightFile = {
  flight: Flight;
  decision: FlightDecision;
  entitlements_summary: Record<string, unknown>;
  sample_entitlements: Entitlement[];
  journal_preview: JournalEntry[];
  timeline: TimelineMark[];
  handoff?: { refunds_already_initiated?: number; not_repeated?: boolean; rights_notices_drafted?: number; drafter_pii_seen?: number; [key: string]: unknown } | null;
  explanation?: Draft | null;
};

export type ChallengeRequest = { text: string };
export type ChallengeResponse = {
  classification: "assertion" | "new_fact" | "new_legal_pattern";
  decision_stands: boolean;
  reply: Draft;
  cited: Evidence[];
  question?: Question | null;
};

export type AnswerRequest = { decision: string; explanation: string };
export type AnswerResponse = { ruling: Ruling; proposal: RuleProposal | null };

export type InjectKind = "tech_log" | "claim" | "crm" | "email" | "occ_log" | "manufacturer";
export type InjectRequest = { kind: InjectKind; text: string; flight_id?: string | null };
export type InjectResponse = {
  source: Source;
  facts: Fact[];
  dropped_unverifiable: number;
  events: TraceEvent[];
  affected: string[];
  fallback_used?: boolean;
  message?: string | null;
};

export type Injection = { id: string; title: string; request: InjectRequest; expected: string };
export type DeskRequest = { icao: string; date: ISODate };

export type AccessDecision = { at: ISODateTime; principal: string; action: string; resource: string; allowed: boolean; reason: string };
export type AccessCell = "read" | "write" | "approve" | "none" | "redacted";
export type AccessMatrix = { principals: string[]; resources: string[]; cells: Record<string, Record<string, AccessCell>> };
export type ControlMapping = { control: string; framework_ref: string; implemented_by: string; evidence_endpoint: string };

export type CalibrationBin = { lo: number; hi: number; n: number; accuracy: number; wilson_lo: number; wilson_hi: number };

export type EvalReport = {
  split: Record<string, string>;
  n_storms: number;
  n_passengers: number;
  straight_through_pct: number;
  miscodes_caught: number;
  miscodes_total: number;
  miscodes_eur_cents: Cents;
  false_holds: number;
  repeat_questions: number;
  out_of_scope_auto: number;
  liability_vs_actual: Record<string, number>;
  calibration: Record<string, CalibrationBin[]>;
  coverage_at_90: Record<string, number>;
  /** {"model","runs":3,"liability_eur":[a,b,c],"cause_accuracy":[..],"hash_identical":false} */
  baseline: Record<string, unknown>;
  /** {"runs":3,"liability_eur":[34650,34650,34650],"hash_identical":true} */
  stormcheck_runs: Record<string, unknown>;
  injections: Record<string, number>;
  real_vs_simulated: Record<string, string[]>;
  label?: string;
};

export type Health = { ok: boolean; mode: string; impl: unknown };
export type SessionResponse = { token: string; session: Session };
export type ConfirmResponse = { rule: Rule; replay: ReplayDiff };
export type MonthEndResponse = { entries: JournalEntry[]; rollforward: Rollforward; estimate: EstimateCard };

/** Error envelope (CONTRACTS §3). */
export type ApiErrorCode =
  | "sod_violation"
  | "forbidden"
  | "not_found"
  | "validation"
  | "upstream"
  | "no_metar"
  | "future_date"
  | "unknown_airport";
export type ApiErrorBody = { error: { code: ApiErrorCode | string; message: string } };
