// Rules come only from mined history, rulings, rejections and regulation versions (plan §2 rule 3).
// Conditions use only the CONTRACTS §4 feature allowlist; `case:` scope values are what Widen removes,
// one rung at a time. Hard controls are code; their cards carry the sentence in `origin_example`.
import type { Role, Rule, RuleAction } from "@/api/types";

export const ONBOARDING = "2025-01-20T09:00:00Z";

type RuleInit = Omit<Rule, "version" | "grounding" | "support" | "supersedes" | "times_cited" | "static_card" | "origin_ruling_id" | "action_arg" | "scope" | "condition"> &
  Partial<Pick<Rule, "version" | "grounding" | "support" | "supersedes" | "static_card" | "origin_ruling_id" | "action_arg" | "scope" | "condition">>;

function rule(r: RuleInit): Rule {
  return {
    version: 1,
    scope: {},
    condition: {},
    action_arg: null,
    origin_ruling_id: null,
    grounding: {},
    support: null,
    supersedes: null,
    times_cited: 0,
    static_card: false,
    ...r,
  };
}

const hc = (id: string, sentence: string, routeTo: Role, condition: Record<string, unknown> = {}): Rule =>
  rule({ id, kind: "routing", condition, action: "route_to", action_arg: routeTo, tier: "hard_control", authority_required: routeTo, origin_example: sentence, valid_from: null, recorded_at: ONBOARDING, status: "active" });

export function baselineRules(): Rule[] {
  return [
    rule({
      id: "R-MIN-1",
      kind: "mined_policy",
      scope: { "flight.band_eur": 600 },
      condition: { all: [{ f: "pax.election", op: "eq", v: "reroute_partner" }, { f: "flight.distance_km", op: "gt", v: 3500 }, { f: "pax.arrival_delay_min", op: "le", v: 240 }] },
      action: "apply_7_2_reduction",
      tier: "mined",
      authority_required: "legal",
      origin_example: "41 of 42 past long-haul partner reroutes landing within 4 h took the 50% cut; the exception (NS41, 2 Mar 2024) landed 4 h 12 min late",
      support: "41 of 42",
      valid_from: "2023-07-01T00:00:00Z",
      recorded_at: ONBOARDING,
      status: "active",
    }),
    rule({
      id: "REG-ART5-3-WEATHER",
      kind: "cause",
      condition: { any: [{ f: "flight.in_window_dep", op: "eq", v: "in" }, { f: "flight.in_window_arr", op: "eq", v: "in" }] },
      action: "set_extraordinary",
      tier: "regulation",
      authority_required: "legal",
      origin_example: "EU261 Art. 5(3): extraordinary circumstances which could not have been avoided even if all reasonable measures had been taken · weather inside the storm window at either end",
      grounding: { in: "extraordinary circumstances which could not have been avoided even if all reasonable measures had been taken" },
      valid_from: "2005-02-17T00:00:00Z",
      recorded_at: ONBOARDING,
      status: "active",
    }),
    rule({
      id: "REG-C549-TECHNICAL",
      kind: "cause",
      condition: { all: [{ f: "aog.before_window", op: "eq", v: true }, { f: "aog.root_cause_internal", op: "eq", v: true }, { f: "aog.mel_relief", op: "eq", v: false }] },
      action: "set_not_extraordinary",
      tier: "regulation",
      authority_required: "legal",
      origin_example: "CJEU C-549/07 Wallentin-Hermann and C-257/14 van der Lans: a technical problem arising in the normal operation of the aircraft is not an extraordinary circumstance",
      valid_from: null,
      recorded_at: ONBOARDING,
      status: "active",
    }),
    rule({
      id: "REG-2026-2202",
      kind: "regime",
      action: "route_to",
      action_arg: "legal",
      tier: "regulation",
      authority_required: "legal",
      origin_example: "Reg (EU) 2026/2202 · in force 22 Oct 2026 · applies from 23 Oct 2027 · 9-month claim window",
      valid_from: "2027-10-23T00:00:00Z",
      recorded_at: "2026-10-22T00:00:00Z",
      status: "shadow",
      static_card: true,
    }),
    hc("HC-SOD-1", "Preparer ≠ approver: nobody approves an entry or a payout they prepared", "controller"),
    hc("HC-PAYOUT-1", "Payouts need the Claims Lead's approval; StormCheck never releases a payment run", "claims_lead"),
    hc("HC-LOCK-1", "Locked periods are never written; adjustments land in the first open period", "controller"),
    hc("HC-MAT-1", "Auto-draft only if the per-flight liability is under €50k and confidence is at least 0.90", "claims_lead"),
    hc("HC-AUTH-1", "A rule's author must hold the authority for what the rule automates", "controller"),
    hc("HC-EXT-1", "External parties (emails, claims, agencies) never satisfy an internal approval", "claims_lead"),
    hc("HC-FLOOR-1", "Statutory floor: only Legal may lower EU261 compensation", "legal"),
    hc("HC-OFFSET-1", "No voucher offset without a signed acceptance (Art. 7(3))", "claims_lead", { all: [{ f: "voucher.in_lieu", op: "eq", v: true }, { f: "voucher.signed", op: "eq", v: false }] }),
    hc("HC-UNKNOWN-1", "No METAR within ±60 min of either end: in-window is unknown, routed to Ops below 0.6", "ops", { any: [{ f: "flight.in_window_dep", op: "eq", v: "unknown" }, { f: "flight.in_window_arr", op: "eq", v: "unknown" }] }),
    hc("HC-CONC-1", "An AOG inside the storm window is a concurrent cause: Legal decides", "legal", { f: "aog.inside_window", op: "eq", v: true }),
  ];
}

// ---------- grounding: every literal maps to words the ruler wrote ----------
/** For each literal, the first candidate phrase found in the ruling text (case-insensitive), else the canonical one. */
export function ground(text: string, candidates: Record<string, string[]>): { grounding: Record<string, string>; found: number } {
  const lower = text.toLowerCase();
  const grounding: Record<string, string> = {};
  let found = 0;
  for (const [literal, phrases] of Object.entries(candidates)) {
    const hit = phrases.find((p) => lower.includes(p.toLowerCase()));
    if (hit) {
      found += 1;
      const at = lower.indexOf(hit.toLowerCase());
      grounding[literal] = text.slice(at, at + hit.length);
    } else grounding[literal] = phrases[0];
  }
  return { grounding, found };
}

export type Proposed = { rule: Rule; checks: Record<string, boolean>; widen_next: Record<string, unknown> | null };

const CHECKS_OK = { compiles: true, reproduces_case: true, no_hard_control: true, grounded: true, author_has_authority: true, no_conflict: true };

/** Q1 → R-CL-1@1. `offset` = the ruler chose to let the voucher offset (a hard control blocks it). */
export function proposeQ1(text: string, rulingId: string, at: string, offset: boolean): Proposed {
  const { grounding } = ground(text, {
    in_lieu: ["the voucher stays as goodwill", "voucher in lieu", "in lieu", "service-desk voucher", "voucher"],
    signed: ["No signed acceptance", "signed acceptance", "didn't sign", "signature", "signed"],
    departs_eu: ["every flight leaving the EU", "leaving the EU", "departs the EU", "EU departure"],
  });
  const action: RuleAction = offset ? "allow_offset" : "deny_offset";
  const r = rule({
    id: "R-CL-1",
    kind: "voucher",
    scope: { "voucher.in_lieu": true, "voucher.signed": false, "flight.departs_eu": true, "voucher.amount_cents": "case:30000", "pax.fare_type": "case:revenue" },
    condition: { all: [{ f: "voucher.in_lieu", op: "eq", v: true }, { f: "voucher.signed", op: "eq", v: false }, { f: "flight.departs_eu", op: "eq", v: true }] },
    action,
    tier: "claims_lead_ruling",
    authority_required: "claims_lead",
    origin_ruling_id: rulingId,
    origin_example: "NS31@2025-01-24:14C",
    grounding,
    valid_from: null,
    recorded_at: at,
    status: "shadow",
  });
  return {
    rule: r,
    checks: { ...CHECKS_OK, no_hard_control: !offset },
    widen_next: { drop: "voucher.amount_cents", question: "Any voucher amount, not just €300?", scope_after: Object.fromEntries(Object.entries(r.scope).filter(([k]) => k !== "voucher.amount_cents")) },
  };
}

/** Q2 → R-LEG-1@1 (the plan's scripted ruling; `extraordinary=false` if Legal says the returns are owed). */
export function proposeQ2(text: string, rulingId: string, at: string, mode: "conditional" | "always" | "owed"): Proposed {
  const candidates: Record<string, string[]> = {
    is_return_sector: ["A return sector", "return sector", "returns"],
    prev_cancelled: ["storm-cancelled rotation", "cancelled rotation", "rotation"],
    weather: ["storm-cancelled", "storm"],
  };
  const all: Record<string, unknown>[] = [
    { f: "flight.is_return_sector", op: "eq", v: true },
    { f: "rotation.prev_cancelled", op: "eq", v: true },
    { f: "rotation.prev_cause", op: "eq", v: "weather" },
  ];
  if (mode === "conditional") {
    candidates.available_within_h = ["within 3 h of STD", "within 3 h", "3 h"];
    candidates.reroute_earliest_offered = ["offered the earliest reroute on any carrier", "earliest reroute", "reroute"];
    all.push({ f: "spare.available_within_h", op: "gt", v: 3 }, { f: "pax.reroute_earliest_offered", op: "eq", v: true });
  }
  const { grounding } = ground(text, candidates);
  const r = rule({
    id: "R-LEG-1",
    kind: "cause",
    scope: { "flight.route_region": "case:EU" },
    condition: { all },
    action: mode === "owed" ? "set_not_extraordinary" : "set_extraordinary",
    tier: "legal_ruling",
    authority_required: "legal",
    origin_ruling_id: rulingId,
    origin_example: "NS117@2025-01-24",
    grounding,
    valid_from: null,
    recorded_at: at,
    status: "shadow",
  });
  return { rule: r, checks: { ...CHECKS_OK }, widen_next: { drop: "flight.route_region", question: "Also for returns to the UK and North America?", scope_after: {} } };
}

/** Q3 rejection → R-CTL-1@1: keep the tail until the six-year limitation; asks once more about all storm cohorts. */
export function proposeQ3(text: string, rulingId: string, at: string): Proposed {
  const { grounding } = ground(text, {
    keep_tail: ["Never release the tail", "never release", "keep"],
    age_months: ["At M12", "M12"],
    limitation_expired: ["until the six-year limitation", "six-year limitation", "limitation"],
  });
  const r = rule({
    id: "R-CTL-1",
    kind: "release",
    scope: { cohort: "case:EIDW@2024-01-21" },
    condition: { all: [{ f: "cohort.age_months", op: "ge", v: 12 }, { f: "cohort.limitation_expired", op: "eq", v: false }] },
    action: "keep_tail",
    tier: "controller_ruling",
    authority_required: "controller",
    origin_ruling_id: rulingId,
    origin_example: "EIDW@2024-01-21",
    grounding,
    valid_from: at,
    recorded_at: at,
    status: "shadow",
  });
  return { rule: r, checks: { ...CHECKS_OK }, widen_next: { drop: "cohort", question: "All storm cohorts?", scope_after: {} } };
}

/** One rung wider: drop the first `case:` scope key. Null when every scope key is grounded. */
export function widenOnce(r: Rule, at: string): { rule: Rule; dropped: string } | null {
  const key = Object.keys(r.scope).find((k) => typeof r.scope[k] === "string" && (r.scope[k] as string).startsWith("case:"));
  if (!key) return null;
  const scope = { ...r.scope };
  delete scope[key];
  return { rule: { ...r, version: r.version + 1, scope, recorded_at: at, status: "shadow", supersedes: `${r.id}@${r.version}`, times_cited: 0 }, dropped: key };
}

export const ruleRef = (r: Pick<Rule, "id" | "version">) => `${r.id}@${r.version}`;

const TIER_ORDER: Record<Rule["tier"], number> = { hard_control: 0, regulation: 1, legal_ruling: 2, controller_ruling: 3, claims_lead_ruling: 4, mined: 5 };
export const byPrecedence = (a: Rule, b: Rule) => TIER_ORDER[a.tier] - TIER_ORDER[b.tier] || a.id.localeCompare(b.id) || a.version - b.version;
