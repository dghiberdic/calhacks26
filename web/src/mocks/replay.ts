// Replay: re-derive every decision under a different rule set and diff it against now (THREAD_DAVID D8).
// Pure over the stored world, never calls an LLM; € deltas are the change in the drafted EU261
// compensation liability (entitlement × segment rate), which is what Books would post.
import type { ReplayDiff, ReplayFlip, Rule } from "@/api/types";
import { decide, HERO_FLIGHT, isOwed, liabilityCents, NS31_REROUTE_SEATS, voucherCases, voucherSettled } from "./data/engine";
import { activeRule, ctxOf, type MockState } from "./state";

type FlightSnap = { extraordinary: string; outcome: string; liability: number; storm: string };
export type Snap = {
  flights: Map<string, FlightSnap>;
  vouchers: Map<string, { settled: boolean; storm: string }>;
  reroutes: Map<string, number>;
  isha: "derecognise €3,600 (proposed)" | "keep the €3,600 tail to limitation";
};

export function snapshot(s: MockState): Snap {
  const ctx = ctxOf(s);
  const flights = new Map<string, FlightSnap>();
  const vouchers = new Map<string, { settled: boolean; storm: string }>();
  const reroutes = new Map<string, number>();
  for (const storm of s.storms) {
    for (const spec of storm.flights) {
      const d = decide(storm, spec, ctx);
      if (!d) continue;
      flights.set(spec.flight.id, { extraordinary: d.extraordinary, outcome: d.outcome, liability: liabilityCents(spec, d, ctx), storm: storm.id });
      if (spec.flight.id === HERO_FLIGHT && isOwed(d)) for (const seat of NS31_REROUTE_SEATS) reroutes.set(`${HERO_FLIGHT}:${seat}`, ctx.reduction ? 30_000 : 60_000);
    }
    for (const c of voucherCases(storm)) vouchers.set(c.coupon_id, { settled: voucherSettled(c, ctx), storm: storm.id });
  }
  return { flights, vouchers, reroutes, isha: activeRule(s, "R-CTL-1") ? "keep the €3,600 tail to limitation" : "derecognise €3,600 (proposed)" };
}

/** The world as it would be with `rules` in place of the current rule store. */
export function simulate(s: MockState, rules: Rule[]): Snap {
  return snapshot({ ...s, rules, cache: { key: "", memo: new Map() } });
}

/** Rules with `rule` active (and whatever it supersedes retired). */
export function withActive(s: MockState, rule: Rule): Rule[] {
  const ref = `${rule.id}@${rule.version}`;
  return [
    ...s.rules.filter((r) => `${r.id}@${r.version}` !== ref).map((r) => (rule.supersedes && `${r.id}@${r.version}` === rule.supersedes ? { ...r, status: "retired" as const } : r)),
    { ...rule, status: "active" as const },
  ];
}

export function diffSnaps(before: Snap, after: Snap, rule_ref: string, known_at: string, locked: string[], exclude: string[] = []): ReplayDiff {
  const flips: ReplayFlip[] = [];
  for (const [id, a] of after.flights) {
    const b = before.flights.get(id);
    if (!b || exclude.includes(id)) continue;
    if (b.extraordinary !== a.extraordinary) flips.push({ entity_id: id, field: "extraordinary", before: b.extraordinary, after: a.extraordinary, delta_cents: a.liability - b.liability });
    else if (b.outcome !== a.outcome) flips.push({ entity_id: id, field: "outcome", before: b.outcome, after: a.outcome, delta_cents: a.liability - b.liability });
  }
  for (const [id, a] of after.vouchers) {
    const b = before.vouchers.get(id);
    if (!b || exclude.includes(id) || b.settled === a.settled) continue;
    flips.push({ entity_id: id, field: "status", before: b.settled ? "owed" : "needs_ruling", after: a.settled ? "owed" : "needs_ruling", delta_cents: 0 });
  }
  for (const [id, a] of after.reroutes) {
    const b = before.reroutes.get(id);
    if (b === undefined || b === a) continue;
    flips.push({ entity_id: id, field: "compensation_cents", before: b, after: a, delta_cents: Math.round(((a - b) * 35) / 100) });
  }
  if (before.isha !== after.isha) flips.push({ entity_id: "EIDW@2024-01-21", field: "release", before: before.isha, after: after.isha, delta_cents: 0 });
  return { rule_ref, known_at, flips, total_delta_cents: flips.reduce((t, f) => t + (f.delta_cents ?? 0), 0), locked_periods_untouched: [...locked], adjustment_je_ids: [] };
}
