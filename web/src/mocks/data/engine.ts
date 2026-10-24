// What David's engine would derive from the world, as pure functions of (storm, flight, active rules).
// Decisions, entitlements, money and counters are recomputed on every read, so a confirmed ruling or a
// revert changes every screen consistently. Golden numbers (CONTRACTS §5) fall out of this arithmetic:
//   NS31 entitlement 158 × €600 + 14 × €300 = 9,900,000c · day-1 liability 35% = 3,465,000c
//   knock-on accruals (IFRS 15.56, segment rates) 178×€400×27% + 184×€400×27% + 168×€250×20%
//     = 1,922,400 + 1,987,200 + 840,000 = 4,749,600c · storm day 1 = 8,214,600c
//   StormRun.entitlement_cents = full Art. 7 entitlement of the owed + held flights (weather flights are 0):
//     NS31 9,900,000 + NS113 178×€400 7,120,000 + NS115 184×€400 7,360,000 + NS117 168×€250 4,200,000 = 28,580,000c
// Cause logic in the engine's priority order (THREAD_DAVID D2): an AOG inside the window → concurrent,
// Legal; in window at either end → weather; a return of a storm-cancelled outbound, calm at both ends →
// knock-on, Legal (unless R-LEG-1 is active); an AOG before the window, out at both ends → technical.
import type { Confidence, Entitlement, Evidence, FlightDecision, InWindow } from "@/api/types";
import { bandFor } from "./airports";
import { electionsFor, fareFor, seatRefs, type FlightSpec } from "./flights";
import * as T from "./texts";
import { ev, hubOf, metarEv, scheduleEv, type StormDef, type VoucherCase } from "./world";
import { position } from "./util";

/** A tech-log line injected through POST /inject that grounds an aircraft inside the window. */
export type InjectedAog = { logged_at: string; source_id: string; span: string; question_id: string };

/** The active rules that change decisions or entitlements (derived from the rule store by state.ts). */
export type RuleCtx = {
  /** R-LEG-1 (any version) active: how storm-cancelled return sectors settle. */
  knockOn: { ref: string; action: "set_extraordinary" | "set_not_extraordinary" } | null;
  /** R-CL-1 active: unsigned in-lieu vouchers settle without offset; `allDepartures` once it reaches non-EU departures. */
  voucher: { ref: string; action: "deny_offset" | "allow_offset"; allDepartures: boolean } | null;
  /** R-MIN-1 active: the Art. 7(2)(c) 50% cut on long-haul partner reroutes landing within 4 h. */
  reduction: { ref: string; support: string } | null;
  /** Per-flight decision metadata (known_at, commit), kept by state.ts. */
  meta: (flightId: string) => { known_at: string; commit: string | null };
  /** Injected tier-1 facts that change a decision (an AOG inside the window). */
  injected: (flightId: string) => InjectedAog | undefined;
  /** Memo of decisions for this exact rule/fact state (state.ts keys it by a fingerprint). */
  memo?: Map<string, FlightDecision | null>;
};

export const RATE_PCT = { long_haul_gt3500: 35, medium_1500_3500: 27, short_le1500: 20 } as const;
export const CAL = "cal-v1";
export const HERO_FLIGHT = "NS31@2025-01-24";
/** NS31's 14 partner reroutes arrived +3 h 40 min: inside Art. 7(2)(c)'s 4 h, so the mined policy cuts 50%. */
export const NS31_REROUTE_SEATS = seatRefs(172).slice(118, 132);

const isHero = (spec: FlightSpec) => spec.flight.id === HERO_FLIGHT;

// ---------- positions against the storm window (both ends, at the storm's station) ----------
export function positions(storm: StormDef, spec: FlightSpec) {
  const f = spec.flight;
  const hub = hubOf(storm);
  const at = (iata: string, t: string) => (iata === hub ? position(storm.metar, storm.windows, t) : { pos: "out" as InWindow, margin_min: null });
  return { dep: at(f.origin, f.sched_dep), arr: at(f.dest, f.sched_arr), hub };
}

function causeConfidence(score: number, f: Partial<Record<string, number>>, caps: string[] = []): Confidence {
  const features: Record<string, number> = {
    in_window_dep: 0, in_window_arr: 0, window_margin_h: 0, aog_before_window: 0, aog_inside_window: 0, root_cause_internal: 0, sources_disagree: 0, precedent_count: 0, knock_on: 0,
  };
  for (const [k, v] of Object.entries(f)) if (v !== undefined) features[k] = v;
  return { score, kind: "cause", label: "cause-finding confidence", features, caps, calibration_version: CAL };
}

const round2 = (n: number) => Math.round(n * 100) / 100;
/** Weather confidence grows with how deep inside the window the decisive end sits (0.90 → 0.97). */
const weatherScore = (marginMin: number | null) => round2(Math.min(0.97, 0.9 + (Math.min(marginMin ?? 0, 360) / 60) * 0.0117));
const WEATHER_CODES = ["71", "72", "73", "75", "76", "77"];

/** The engine's verdict for one cancelled flight (null for flights that operated). Pure; memoised per rule state. */
export function decide(storm: StormDef, spec: FlightSpec, ctx: RuleCtx): FlightDecision | null {
  const key = spec.flight.id;
  if (ctx.memo?.has(key)) return ctx.memo.get(key) ?? null;
  const d = decideRaw(storm, spec, ctx);
  ctx.memo?.set(key, d);
  return d;
}

function decideRaw(storm: StormDef, spec: FlightSpec, ctx: RuleCtx): FlightDecision | null {
  const f = spec.flight;
  if (f.status === "operated") return null;
  const { dep, arr, hub } = positions(storm, spec);
  const meta = ctx.meta(f.id);
  const base = { flight_id: f.id, ops_cause_code: f.ops_cause_code ?? null, in_window_dep: dep.pos, in_window_arr: arr.pos, known_at: meta.known_at, commit: meta.commit };
  const occCode = (code: string | null | undefined) => (code === "72" ? storm.occ.span72 : storm.occ.span71);
  const atHubEnd = f.origin === hub ? { t: f.sched_dep, end: dep, field: "flight.in_window_dep" } : { t: f.sched_arr, end: arr, field: "flight.in_window_arr" };
  const weatherAtEitherEnd = dep.pos === "in" || arr.pos === "in";

  // An AOG logged inside the window (injected tech-log line): concurrent causes, Legal decides.
  const aog = ctx.injected(f.id);
  if (aog && weatherAtEitherEnd) {
    return {
      ...base,
      cause: "concurrent",
      extraordinary: "needs_legal",
      recoded: false,
      recode_label: null,
      window_margin_min: atHubEnd.end.margin_min,
      confidence: causeConfidence(0.55, { in_window_dep: dep.pos === "in" ? 1 : 0, in_window_arr: arr.pos === "in" ? 1 : 0, aog_inside_window: 1, root_cause_internal: 1, sources_disagree: 1 }, ["capped:concurrent-causes"]),
      reason: "AOG inside the storm window: concurrent causes",
      evidence: [
        ev(aog.source_id, "aog.logged_at", aog.logged_at, aog.span, "contradicts", false, `aircraft:${f.aircraft}`),
        metarEv(storm, atHubEnd.t, atHubEnd.field, atHubEnd.end.pos),
        scheduleEv(spec),
        ev(storm.occ.source, "flight.ops_cause_code", f.ops_cause_code, occCode(f.ops_cause_code), "context", false, `flight:${f.id}`),
      ],
      rules_applied: ["HC-CONC-1@1"],
      legal_basis: ["EU261 Art.5(3)", "CJEU C-549/07", "CJEU C-74/19"],
      outcome: "escalated",
      routed_to: "legal",
      question_id: aog.question_id,
    };
  }

  if (spec.group === "outbound_weather" || spec.group === "return_weather" || spec.group === "overnight_inbound") {
    const atArr = spec.group !== "outbound_weather";
    const end = atArr ? arr : dep;
    const t = atArr ? f.sched_arr : f.sched_dep;
    const field = atArr ? "flight.in_window_arr" : "flight.in_window_dep";
    const evidence: Evidence[] = [metarEv(storm, t, field, "in"), scheduleEv(spec), ev(storm.occ.source, "flight.ops_cause_code", f.ops_cause_code, occCode(f.ops_cause_code), "supports", false, `flight:${f.id}`)];
    const reason = spec.group === "outbound_weather" ? `inside the storm window at ${hub}` : f.ops_cause_code === "72" ? `destination weather: STA inside the ${hub} window` : `STA inside the storm window at ${hub}`;
    return {
      ...base,
      cause: "weather",
      extraordinary: "extraordinary",
      recoded: false,
      recode_label: null,
      window_margin_min: end.margin_min,
      confidence: causeConfidence(weatherScore(end.margin_min), { in_window_dep: dep.pos === "in" ? 1 : 0, in_window_arr: arr.pos === "in" ? 1 : 0, window_margin_h: round2((end.margin_min ?? 0) / 60), precedent_count: 108 }),
      reason,
      evidence,
      rules_applied: ["REG-ART5-3-WEATHER@1"],
      legal_basis: ["EU261 Art.5(3)", "EU261 recital 14", "CJEU C-12/11"],
      outcome: "auto",
      routed_to: null,
      question_id: null,
    };
  }

  if (spec.group === "knock_on") {
    const n = f.number;
    const k = storm.knockOn[n];
    const outbound = f.outbound_pair_id?.split("@")[0] ?? "";
    const evidence: Evidence[] = [atHubEnd.end.pos === "out" ? metarEv(storm, atHubEnd.t, atHubEnd.field, "out") : scheduleEv(spec)];
    if (k) {
      evidence.push(
        ev(`spares:${storm.id}`, "spare.available_within_h", k.hours, k.spares, "supports", false, `flight:${f.id}`),
        ev(`pss:${storm.id}`, "pax.reroute_earliest_offered", true, k.pss, "supports", false, `flight:${f.id}`),
      );
    }
    evidence.push(
      ev(storm.occ.source, "rotation.prev_cancelled", true, `${outbound}/${n.slice(2)}`, "supports", false, `flight:${f.id}`),
      scheduleEv(spec),
      ev(storm.occ.source, "flight.ops_cause_code", f.ops_cause_code, occCode(f.ops_cause_code), "context", false, `flight:${f.id}`),
    );
    const legal = ["EU261 Art.5(3)", "CJEU C-74/19", "CJEU C-549/07"];
    const features = { in_window_dep: 0, in_window_arr: 0, window_margin_h: round2((atHubEnd.end.margin_min ?? 0) / 60), sources_disagree: 1, knock_on: 1 };
    if (ctx.knockOn) {
      const extraordinary = ctx.knockOn.action === "set_extraordinary";
      return {
        ...base,
        cause: "knock_on",
        extraordinary: extraordinary ? "extraordinary" : "not_extraordinary",
        recoded: false,
        recode_label: null,
        window_margin_min: atHubEnd.end.margin_min,
        confidence: causeConfidence(0.93, { ...features, sources_disagree: 0, precedent_count: 1 }),
        reason: extraordinary ? `storm-cancelled rotation · no spare within 3 h · earliest reroute offered · ${ctx.knockOn.ref}` : `knock-on return, not extraordinary · ${ctx.knockOn.ref}`,
        evidence,
        rules_applied: [ctx.knockOn.ref],
        legal_basis: legal,
        outcome: "auto",
        routed_to: null,
        question_id: "Q-2",
      };
    }
    return {
      ...base,
      cause: "knock_on",
      extraordinary: "needs_legal",
      recoded: false,
      recode_label: null,
      window_margin_min: atHubEnd.end.margin_min,
      confidence: causeConfidence(0.47, features, ["capped:no-precedent"]),
      reason: "knock-on return, calm at both ends",
      evidence,
      rules_applied: [],
      legal_basis: legal,
      outcome: "escalated",
      routed_to: "legal",
      question_id: "Q-2",
    };
  }

  // technical: AOG logged before the window, out of window at both ends
  const log = storm.techLogs[f.id];
  const recoded = WEATHER_CODES.includes(f.ops_cause_code ?? "");
  const evidence: Evidence[] = [];
  if (log) {
    const subject = `aircraft:${f.aircraft}`;
    evidence.push(
      ev(log.source, "aog.logged_at", log.logged_at, log.text, "supports", false, subject),
      ev(log.source, "aog.mel_relief", false, "NO MEL RELIEF", "supports", false, subject),
      ev(log.source, "aog.ata", log.ata, log.span, "supports", false, subject),
    );
  }
  if (isHero(spec)) {
    evidence.push(
      ev("mcc_log:EI-NSB@2025-01-23", "aog.rts_est", "2025-01-25T20:00:00Z", T.MCC_NS31, "supports", false, "aircraft:EI-NSB"),
      metarEv(storm, "2025-01-24T16:00:00Z", "metar.max_gust_kt_from_16z", 25),
      metarEv(storm, f.sched_dep, "flight.in_window_dep", "out"),
      metarEv(storm, "2025-01-23T21:40:00Z", "metar.sknt_at_aog", 14, "context"),
      scheduleEv(spec),
      ev(`spares:${storm.id}`, "spare.long_range_at_dub", false, T.SPARES_EOWYN, "context", false, `flight:${f.id}`),
      ev(storm.occ.source, "flight.ops_cause_code", "71", storm.occ.span71, "contradicts", true, `flight:${f.id}`),
    );
  } else {
    evidence.push(metarEv(storm, atHubEnd.t, atHubEnd.field, "out"), scheduleEv(spec));
    if (log?.occ) evidence.push(ev(log.occ.source, "flight.ops_cause_code", f.ops_cause_code, log.occ.quote, recoded ? "contradicts" : "supports", recoded, `flight:${f.id}`));
    else evidence.push(ev(storm.occ.source, "flight.ops_cause_code", f.ops_cause_code, occCode(f.ops_cause_code), recoded ? "contradicts" : "supports", recoded, `flight:${f.id}`));
  }
  const margin = atHubEnd.end.margin_min;
  const score = isHero(spec) ? 0.91 : recoded ? 0.92 : 0.95;
  return {
    ...base,
    cause: "technical",
    extraordinary: "not_extraordinary",
    recoded,
    recode_label: recoded ? `${f.ops_cause_code} → 41` : null,
    window_margin_min: margin,
    confidence: causeConfidence(score, { window_margin_h: round2((margin ?? 0) / 60), aog_before_window: 1, root_cause_internal: 1, sources_disagree: recoded ? 1 : 0, precedent_count: 23 }),
    reason: log?.reason ?? "fault logged before storm",
    evidence,
    rules_applied: ["REG-C549-TECHNICAL@1"],
    legal_basis: ["EU261 Art.5(3)", "CJEU C-549/07", "CJEU C-257/14"],
    outcome: "auto",
    routed_to: null,
    question_id: null,
  };
}

// ---------- money ----------
export const isOwed = (d: FlightDecision | null) => !!d && d.extraordinary === "not_extraordinary";
export const isHeld = (d: FlightDecision | null) => !!d && (d.extraordinary === "needs_legal" || d.outcome === "escalated");
export const ratePct = (spec: FlightSpec) => RATE_PCT[bandFor(spec.flight.origin, spec.flight.dest).segment];

/** Full Art. 7 entitlement if every passenger claims (0 for extraordinary flights). */
export function fullEntitlementCents(spec: FlightSpec, d: FlightDecision | null, ctx: RuleCtx): number {
  if (!isOwed(d) && !isHeld(d)) return 0;
  const per = bandFor(spec.flight.origin, spec.flight.dest).band_eur * 100;
  const cut = isHero(spec) && ctx.reduction ? NS31_REROUTE_SEATS.length : 0;
  return (spec.flight.pax - cut) * per + cut * (per / 2);
}

/** Day-1 EU261 compensation liability: entitlement × the segment's expected ultimate claim rate (held items too, IFRS 15.56). */
export const liabilityCents = (spec: FlightSpec, d: FlightDecision | null, ctx: RuleCtx) => Math.round((fullEntitlementCents(spec, d, ctx) * ratePct(spec)) / 100);

// ---------- voucher-in-lieu cases (Q1 pattern) ----------
export type { VoucherCase };

export function voucherCases(storm: StormDef): VoucherCase[] {
  if (storm.vouchers) return storm.vouchers;
  if (storm.kind === "eowyn") return [{ coupon_id: `${HERO_FLIGHT}:14C`, flight_id: HERO_FLIGHT, departs_eu: true, amount_cents: 30_000, source_id: "crm:NS31@2025-01-24:14C" }];
  if (storm.kind === "herminia") {
    const ns112 = seatRefs(178).slice(20, 51).map((s) => ({ coupon_id: `NS112@2025-01-26:${s}`, flight_id: "NS112@2025-01-26", departs_eu: true, amount_cents: 30_000, source_id: "crm:NS112@2025-01-26:desk" }));
    return [...ns112, { coupon_id: "NS30@2025-01-25:12A", flight_id: "NS30@2025-01-25", departs_eu: false, amount_cents: 30_000, source_id: "crm:NS30@2025-01-25:desk" }];
  }
  return [];
}

export const voucherSettled = (c: VoucherCase, ctx: RuleCtx) => !!ctx.voucher && (c.departs_eu || ctx.voucher.allDepartures);

// ---------- entitlements ----------
export function entitlementFor(storm: StormDef, spec: FlightSpec, d: FlightDecision | null, ctx: RuleCtx, seat: string, election: "refund" | "voucher" | "reaccommodated_own" | "reroute_partner"): Entitlement {
  const f = spec.flight;
  const band = bandFor(f.origin, f.dest);
  const fare = fareFor(f.origin, f.dest);
  const coupon_id = `${f.id}:${seat}`;
  const refundAlready = isHero(spec) && election === "refund";
  const refund_due_cents = election === "refund" && !refundAlready ? fare.fare_cents + fare.taxes_cents : 0;
  const common = { coupon_id, flight_id: f.id, distance_km: band.distance_km, band_eur: band.band_eur, band_margin_km: band.band_margin_km, regime: "EU261_2004" as const, refund_due_cents, refund_already_initiated: refundAlready, care_due: true, voucher_offset_cents: 0 };
  if (!isOwed(d) && !isHeld(d)) {
    return { ...common, compensation_cents: 0, reduction: "none", status: "no_compensation", article: "Art. 5(3)", reason: "no compensation; refunds and care still due", rules_applied: d?.rules_applied ?? [] };
  }
  if (isHeld(d)) {
    const why = d?.cause === "concurrent" ? "concurrent causes (AOG inside the window)" : "knock-on return, C-74/19 pattern";
    return { ...common, compensation_cents: band.band_eur * 100, reduction: "none", status: "held", article: band.article, reason: `held for Legal (${d?.question_id ?? "Q-2"}): ${why}`, rules_applied: [] };
  }
  const vc = voucherCases(storm).find((c) => c.coupon_id === coupon_id);
  if (vc) {
    const settled = voucherSettled(vc, ctx);
    return {
      ...common,
      compensation_cents: band.band_eur * 100,
      reduction: "none",
      status: settled ? "owed" : "needs_ruling",
      article: band.article,
      reason: settled
        ? `no signed acceptance, no offset: compensation in cash; the €${vc.amount_cents / 100} service-desk voucher stays as goodwill · ${ctx.voucher?.ref}`
        : `unsigned service-desk voucher in lieu (€${vc.amount_cents / 100}): an offset needs signed acceptance (Art. 7(3)) · asked the Claims Lead`,
      rules_applied: settled && ctx.voucher ? [ctx.voucher.ref] : [],
    };
  }
  const cut = isHero(spec) && election === "reroute_partner" && !!ctx.reduction;
  const reason = cut
    ? `partner reroute via LHR arrived +3 h 40 min: Art. 7(2)(c) 50% cut (${ctx.reduction?.ref}, ${ctx.reduction?.support})`
    : refundAlready
      ? "technical fault, not extraordinary · refund already initiated by the CRM bot (not repeated)"
      : election === "voucher"
        ? `elected a refund voucher (ticket value €${(fare.fare_cents + fare.taxes_cents) / 100}); compensation still owed`
        : d?.cause === "knock_on"
          ? `knock-on return, not extraordinary: compensation owed (${d.rules_applied.join(", ")})`
          : "technical fault, not extraordinary: compensation owed";
  return {
    ...common,
    compensation_cents: cut ? (band.band_eur * 100) / 2 : band.band_eur * 100,
    reduction: cut ? "art7_2_50pct" : "none",
    status: "owed",
    article: cut ? "Art. 7(2)(c)" : band.article,
    reason,
    rules_applied: cut && ctx.reduction ? [ctx.reduction.ref, ...(d?.rules_applied ?? [])] : [...(d?.rules_applied ?? [])],
  };
}

/** A few representative coupons per flight; NS31's include 14C (the unsigned voucher) and a CRM-bot refund. */
export function sampleEntitlements(storm: StormDef, spec: FlightSpec, d: FlightDecision | null, ctx: RuleCtx): Entitlement[] {
  if (!d) return [];
  if (isHero(spec)) {
    return [
      entitlementFor(storm, spec, d, ctx, "14C", "reaccommodated_own"),
      entitlementFor(storm, spec, d, ctx, "3A", "refund"),
      entitlementFor(storm, spec, d, ctx, "22F", "reroute_partner"),
      entitlementFor(storm, spec, d, ctx, "9D", "voucher"),
      entitlementFor(storm, spec, d, ctx, "27B", "reaccommodated_own"),
    ];
  }
  const seats = seatRefs(spec.flight.pax);
  const samples = [entitlementFor(storm, spec, d, ctx, seats[6], "refund"), entitlementFor(storm, spec, d, ctx, seats[17], "reaccommodated_own"), entitlementFor(storm, spec, d, ctx, seats[40], "voucher")];
  const vc = voucherCases(storm).find((c) => c.flight_id === spec.flight.id);
  if (vc) samples.unshift(entitlementFor(storm, spec, d, ctx, vc.coupon_id.split(":").pop() ?? "", "reaccommodated_own"));
  return samples;
}

/** FlightFile.entitlements_summary (keys per contracts/requests/justin.md #5, plus display helpers). */
export function entitlementsSummary(storm: StormDef, spec: FlightSpec, d: FlightDecision | null, ctx: RuleCtx): Record<string, unknown> {
  const f = spec.flight;
  const band = bandFor(f.origin, f.dest);
  const elections = electionsFor(f);
  const full = fullEntitlementCents(spec, d, ctx);
  const liability = liabilityCents(spec, d, ctx);
  const owed = isOwed(d);
  const held = isHeld(d);
  const vcs = voucherCases(storm).filter((c) => c.flight_id === f.id);
  const needsRuling = vcs.filter((c) => !voucherSettled(c, ctx)).length;
  const fare = fareFor(f.origin, f.dest);
  const cut = isHero(spec) && ctx.reduction ? NS31_REROUTE_SEATS.length : 0;
  const statuses: Record<string, number> = owed ? { owed: f.pax - needsRuling, ...(needsRuling ? { needs_ruling: needsRuling } : {}) } : held ? { held: f.pax } : { no_compensation: f.pax };
  const summary: Record<string, unknown> = {
    coupons: f.pax,
    elections,
    distance_km: band.distance_km,
    band_eur: band.band_eur,
    band_margin_km: band.band_margin_km,
    band_label: band.label,
    segment: band.segment,
    statuses,
    full_entitlement_cents: full,
    full_entitlement_label: "full Art. 7 entitlement if every passenger claims",
    drafted_liability_cents: liability,
    claim_rate: owed || held ? ratePct(spec) / 100 : null,
    claim_rate_label: owed || held ? `${ratePct(spec)}% expected ultimate claim rate (history to M18 + tail judgment)` : null,
    refund_cents: elections.refund * (fare.fare_cents + fare.taxes_cents),
    care_due: true,
  };
  if (owed) {
    summary.payouts_drafted = f.pax;
    summary.status_line = `${f.pax} payouts drafted, pending Claims Lead approval`;
    summary.compensation_breakdown = cut ? [{ count: f.pax - cut, band_eur: band.band_eur }, { count: cut, band_eur: band.band_eur / 2 }] : [{ count: f.pax, band_eur: band.band_eur }];
    if (cut) summary.reduction_7_2 = { coupons: cut, rule_ref: ctx.reduction?.ref, support: ctx.reduction?.support, label: "Art. 7(2)(c) 50% cut on partner reroutes landing within 4 h" };
    summary.voucher_cases = vcs.length;
    summary.needs_ruling = needsRuling;
  } else if (held) {
    summary.status_line = `held for Legal · accrued at the ${ratePct(spec)}% segment rate (IFRS 15.56)`;
    summary.question_id = d?.question_id ?? null;
  } else {
    summary.status_line = "no compensation; refunds and care still due";
  }
  if (isHero(spec)) {
    summary.refunds_already_initiated = 32;
    summary.claims_received = 6;
    summary.claims_unassessed = 6;
    summary.atl_cents = 7_740_000;
    summary.taxes_payable_cents = 1_032_000;
  }
  return summary;
}

// ---------- counters ----------
export type StormMoney = { entitlement_cents: number; liability_drafted_cents: number; held_for_legal_cents: number };

export function stormMoney(storm: StormDef, ctx: RuleCtx): StormMoney {
  let entitlement = 0;
  let liability = 0;
  let held = 0;
  for (const spec of storm.flights) {
    const d = decide(storm, spec, ctx);
    entitlement += fullEntitlementCents(spec, d, ctx);
    liability += liabilityCents(spec, d, ctx);
    if (isHeld(d)) held += liabilityCents(spec, d, ctx);
  }
  return { entitlement_cents: entitlement, liability_drafted_cents: liability, held_for_legal_cents: held };
}

export function rulesCited(storm: StormDef, ctx: RuleCtx): number {
  let n = 0;
  for (const spec of storm.flights) {
    const d = decide(storm, spec, ctx);
    if (isHero(spec) && ctx.reduction && isOwed(d)) n += NS31_REROUTE_SEATS.length;
    if (spec.group === "knock_on" && ctx.knockOn) n += 1;
  }
  n += voucherCases(storm).filter((c) => voucherSettled(c, ctx)).length;
  return n;
}

export function baseCounters(storm: StormDef, ctx: RuleCtx): Record<string, number> {
  let passengers = 0, cancelled = 0, operated = 0, drafted = 0, held = 0, recoded = 0;
  for (const spec of storm.flights) {
    const f = spec.flight;
    if (f.status === "operated") {
      operated += 1;
      continue;
    }
    cancelled += 1;
    passengers += f.pax;
    const d = decide(storm, spec, ctx);
    if (isOwed(d)) drafted += f.pax;
    if (isHeld(d)) held += f.pax;
    if (d?.recoded) recoded += 1;
  }
  const needs_ruling = voucherCases(storm).filter((c) => !voucherSettled(c, ctx)).length;
  return { passengers, cancelled, operated, drafted, held, needs_ruling, recoded, settled: passengers - held - needs_ruling, rules_cited: rulesCited(storm, ctx), repeat_questions: 0 };
}
