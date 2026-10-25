// Pitch insights for the mock world: what a storm costs done by hand (GET /runs/{id}/effort) and what was
// learned and reused storm by storm (GET /learning). The assumptions are the spec's (server/insights.py holds
// the real ones); the mock applies them to each run's own counts, so every run, desk days included, has one.
import type { EffortEstimate, EffortLine, ErrorCaught, LearningStep, StormRun } from "@/api/types";
import { longDate } from "@/lib/format";
import { stormName } from "@/lib/storms";
import { EOWYN_ID, HERMINIA_ID } from "./flights";

const RATE = { ops: 45, claims: 31, counsel: 100, accountant: 61 } as const;
const CLAIM_RATE = 0.18;
const MONTH_ENDS = 18;
/** Refund and voucher elections per passenger on a cancelled flight (the rest rebook). */
const REFUND_RATE = 0.05;

const SRC = {
  claims: "Steer (2020) for the European Commission: cancellation claim rate; a rail delay-repay case study measured 30 min a claim by hand, 5 min automated",
  rates: "Irish salary surveys (Chartered Accountants Ireland / Barden 2026; recruiter guides for claims handlers) × 1.3 on-cost ÷ 1,700 h",
};

const n = (x: number) => x.toLocaleString("en-IE");
const plural = (k: number, one: string, many: string) => `${n(k)} ${k === 1 ? one : many}`;

/** Errors the golden Éowyn run caught (the engine's own figures). Other runs list their recodes. */
const ERRORS: Record<string, ErrorCaught[]> = {
  [EOWYN_ID]: [
    { label: "NS31 recoded 71 → 41", amount_cents: 9_900_000, detail: "Coded weather, but the plane was broken: compensation is owed, not €0." },
    { label: "32 refunds the CRM bot had already made, not repeated", amount_cents: 1_632_000, detail: "Refunding them again would have paid twice." },
  ],
};

export function effortOf(run: StormRun): EffortEstimate {
  const c = run.counters ?? {};
  const cancelled = c.cancelled ?? run.flights.filter((r) => r.flight.status === "cancelled").length;
  const passengers = c.passengers ?? run.flights.filter((r) => r.flight.status === "cancelled").reduce((s, r) => s + r.flight.pax, 0);
  const expectedClaims = Math.round(passengers * CLAIM_RATE);
  const questions = run.questions.length;
  const refunds = Math.round(passengers * REFUND_RATE);
  const cohorts = cancelled > 0 ? 1 : 0;
  const escalated = run.flights.filter((r) => r.decision?.outcome === "escalated").length;

  const lines: EffortLine[] = [
    { task: "Find what really caused each cancellation", role: "ops analyst", basis: `${plural(cancelled, "flight", "flights")} × 1.5 h; with StormCheck a person reads only the ${plural(escalated, "escalated one", "escalated ones")}, 10 min each`, manual_hours: cancelled * 1.5, with_stormcheck_hours: (escalated * 10) / 60, rate_eur_per_hour: RATE.ops, source: null },
    { task: "Decide each claim", role: "claims handler", basis: `${n(expectedClaims)} expected claims (18% of ${n(passengers)} passengers) × 20 min; 2 min to review a drafted decision`, manual_hours: (expectedClaims * 20) / 60, with_stormcheck_hours: (expectedClaims * 2) / 60, rate_eur_per_hour: RATE.claims, source: SRC.claims },
    { task: "Research the legal and policy questions", role: "in-house counsel", basis: `${plural(questions, "question", "questions")} × 4 h (research and a memo); 15 min to answer one card`, manual_hours: questions * 4, with_stormcheck_hours: questions * 0.25, rate_eur_per_hour: RATE.counsel, source: null },
    { task: "Reconcile refunds and vouchers", role: "claims handler", basis: `${plural(refunds, "refund or voucher choice", "refund and voucher choices")} × 3 min`, manual_hours: refunds * 0.05, with_stormcheck_hours: 0, rate_eur_per_hour: RATE.claims, source: null },
    { task: "Book and re-estimate the liability", role: "revenue accountant", basis: `${plural(cohorts, "cohort", "cohorts")}: 16 h first estimate, ${MONTH_ENDS} month-ends × 2 h, 16 h audit evidence; 1 h, ${MONTH_ENDS} × 30 min and 1 h with StormCheck`, manual_hours: cohorts * (16 + 2 * MONTH_ENDS + 16), with_stormcheck_hours: cohorts * (1 + 0.5 * MONTH_ENDS + 1), rate_eur_per_hour: RATE.accountant, source: SRC.rates },
  ];

  const sum = (f: (l: EffortLine) => number) => lines.reduce((s, l) => s + f(l), 0);
  const manual = sum((l) => l.manual_hours);
  const withSc = sum((l) => l.with_stormcheck_hours);
  const manualCost = Math.round(sum((l) => l.manual_hours * l.rate_eur_per_hour * 100));
  const withCost = Math.round(sum((l) => l.with_stormcheck_hours * l.rate_eur_per_hour * 100));
  const recodes = run.flights
    .filter((r) => r.decision?.recoded)
    .map((r): ErrorCaught => ({ label: `${r.flight.number} recoded ${r.decision?.recode_label ?? ""}`.trim(), amount_cents: null, detail: "The weather code hid a cause the airline controls." }));

  return {
    run_id: run.id,
    name: [run.name ?? stormName(run.id) ?? run.station, longDate(run.date)].join(" · "),
    inputs: { cancelled_flights: cancelled, passengers, expected_claims: expectedClaims, questions, refunds, cohorts, month_ends: MONTH_ENDS },
    lines,
    manual_hours: manual,
    with_stormcheck_hours: withSc,
    hours_saved: manual - withSc,
    manual_cost_cents: manualCost,
    with_stormcheck_cost_cents: withCost,
    cost_saved_cents: manualCost - withCost,
    errors_caught: ERRORS[run.id] ?? recodes,
    assumptions_note: "Estimate from the assumptions below; not measured at a real airline.",
  };
}

const RULE = {
  mined: { rule_ref: "R-MIN-1@1", title: "Long-haul partner reroutes landing within 4 h take the 50% cut", learned_from: "18 months of history (41 of 42)" },
  voucher: { rule_ref: "R-CL-1@1", title: "No signed acceptance, no offset", learned_from: "Claims Lead ruling on Storm Éowyn (Q-1)" },
  knockOn: { rule_ref: "R-LEG-1@1", title: "A knock-on return is extraordinary only if nothing could fly it within 3 h", learned_from: "Legal ruling on Storm Éowyn (Q-2)" },
};

/** Storm by storm, in the order the clock reached them (the scripted flow's expected story). */
export const LEARNING: LearningStep[] = [
  {
    run_id: EOWYN_ID,
    name: "Storm Éowyn · 24 Jan 2025",
    known_at: "2025-01-25T06:00:00Z",
    questions_asked: 3,
    cases_settled_by_reused_rules: 12,
    reused: [{ ...RULE.mined, cases: 12 }],
    new_rules: ["R-CL-1@1", "R-LEG-1@1", "R-CTL-1@1"],
    note: "Asked 3 questions, each to the person who owns the answer; each answer became a rule. The reroute rule from history settled 12 cases on its own.",
  },
  {
    run_id: HERMINIA_ID,
    name: "Storm Herminia · 26 Jan 2025",
    known_at: "2025-01-27T06:00:00Z",
    questions_asked: 1,
    cases_settled_by_reused_rules: 31,
    reused: [{ ...RULE.voucher, cases: 31 }],
    new_rules: [],
    note: "Reused the Claims Lead's voucher rule: 31 cases settled without asking. 1 asked again (BOS→DUB is outside the rule's scope).",
  },
  {
    run_id: "EIDW@2025-04-28",
    name: "Iberian blackout · 28 Apr 2025",
    known_at: "2025-04-29T06:00:00Z",
    questions_asked: 1,
    cases_settled_by_reused_rules: 9,
    reused: [
      { ...RULE.mined, cases: 6 },
      { ...RULE.knockOn, cases: 3 },
    ],
    new_rules: ["R-LEG-2@1"],
    note: "A new kind of event, a national power cut: 1 question to Legal, now a rule. The reroute rule and the knock-on ruling still applied: 9 cases settled without asking.",
  },
];
