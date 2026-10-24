// The mock world's mutable state (an in-memory stand-in for the event-sourced SQLite store) and the read
// views every route serves. Status fields are recomputed from the rule store and the journal on every
// read, so a confirmed ruling, a revert or an approval shows up consistently on every screen.
import type {
  AccessDecision,
  Commit,
  CommitKind,
  Draft,
  FlightDecision,
  FlightFile,
  JournalEntry,
  LearnedItem,
  Question,
  ReplayDiff,
  Role,
  Rule,
  RuleProposal,
  Ruling,
  StormRun,
  StormSummary,
  TimelineMark,
  TraceEvent,
} from "@/api/types";
import { bandFor, findAirport } from "./data/airports";
import { baselineJournal, COHORT_ISHA, COHORT_LH, COHORT_MED, COHORT_SHORT } from "./data/books";
import { baseCounters, CAL, decide, entitlementsSummary, fullEntitlementCents, HERO_FLIGHT, isHeld, isOwed, liabilityCents, sampleEntitlements, stormMoney, voucherCases, voucherSettled, type InjectedAog, type RuleCtx } from "./data/engine";
import { EOWYN_ID, HERMINIA_ID, type FlightSpec } from "./data/flights";
import { baselineQuestions, type MockQuestion } from "./data/questions";
import { baselineRules, byPrecedence, ruleRef } from "./data/rules";
import * as T from "./data/texts";
import { addMin, canonical, clone, eur, hashOf, hhmmZ, isoZ, nearestObs, sha256 } from "./data/util";
import { EOWYN, HERMINIA, hubOf, mainWindow, scheduleLine, SOURCES, windowLabel, type StormDef } from "./data/world";

export const ENGINE_SHA = "engine@4c1d9e2";
export const BASELINE_CLOCK = "2025-01-25T09:00:00Z";

export type MockState = {
  knownAt: string;
  /** Events written since the clock last moved: each new event is stamped knownAt + n seconds. */
  tick: number;
  storms: StormDef[];
  rules: Rule[];
  proposals: Map<string, RuleProposal>;
  questions: MockQuestion[];
  rulings: Ruling[];
  trace: TraceEvent[];
  eventStorm: Map<number, string>;
  commits: Commit[];
  journal: JournalEntry[];
  locked: string[];
  lockedWrites: number;
  accessLog: AccessDecision[];
  meta: Map<string, { known_at: string; commit: string | null }>;
  /** Tier-1 facts injected through POST /inject that change a decision (an AOG inside the window). */
  injected: Map<string, InjectedAog>;
  /** Replay diffs of confirmed proposals, so a repeated confirm answers the same thing. */
  confirmed: Map<string, ReplayDiff>;
  ids: { je: number; q: number; ruling: number; inject: number; draft: number };
  /** Bumped whenever a decision's metadata (known_at, commit) changes; part of the memo key. */
  metaVersion: number;
  cache: { key: string; memo: Map<string, FlightDecision | null> };
  extRefusals: number;
  monthEnd: Set<string>;
};

const listeners = new Set<(e: TraceEvent) => void>();
export const onEvent = (fn: (e: TraceEvent) => void) => {
  listeners.add(fn);
  return () => void listeners.delete(fn);
};

// Built on first use (module constants below must be initialised first).
let state: MockState | null = null;
export const S = (): MockState => (state ??= createBaseline());
export function resetState() {
  state = createBaseline();
}

// ---------- rules → engine context ----------
export const activeRule = (s: MockState, id: string) => s.rules.filter((r) => r.id === id && r.status === "active").sort((a, b) => b.version - a.version)[0];

export function ctxOf(s: MockState): RuleCtx {
  const leg = activeRule(s, "R-LEG-1");
  const cl = activeRule(s, "R-CL-1");
  const min = activeRule(s, "R-MIN-1");
  const knockOn = leg && (leg.action === "set_extraordinary" || leg.action === "set_not_extraordinary") ? { ref: ruleRef(leg), action: leg.action } : null;
  const voucher = cl && (cl.action === "deny_offset" || cl.action === "allow_offset") ? { ref: ruleRef(cl), action: cl.action, allDepartures: !("flight.departs_eu" in cl.scope) } : null;
  const reduction = min ? { ref: ruleRef(min), support: min.support ?? "" } : null;
  // Decisions are pure in (rules, metadata, injected facts, storms): memoise them per that fingerprint.
  const key = JSON.stringify([knockOn, voucher, reduction, s.metaVersion, [...s.injected.keys()], s.storms.length]);
  if (s.cache.key !== key) s.cache = { key, memo: new Map() };
  return {
    knockOn,
    voucher,
    reduction,
    meta: (id) => s.meta.get(id) ?? { known_at: defaultKnownAt(s, id), commit: null },
    injected: (id) => s.injected.get(id),
    memo: s.cache.memo,
  };
}

function defaultKnownAt(s: MockState, flightId: string) {
  const storm = stormOfFlight(s, flightId);
  return storm?.kind === "herminia" ? "2025-01-27T06:00:00Z" : storm?.kind === "desk" ? (storm.real_context.run_at as string) ?? s.knownAt : "2025-01-25T06:00:00Z";
}

export const stormById = (s: MockState, id: string) => s.storms.find((x) => x.id === id);
export function stormOfFlight(s: MockState, flightId: string): StormDef | undefined {
  return s.storms.find((x) => x.flights.some((f) => f.flight.id === flightId));
}
export function specOf(s: MockState, flightId: string): { storm: StormDef; spec: FlightSpec } | undefined {
  for (const storm of s.storms) {
    const spec = storm.flights.find((f) => f.flight.id === flightId);
    if (spec) return { storm, spec };
  }
  return undefined;
}

// ---------- events and commits ----------
const COMMIT_KIND: Record<TraceEvent["kind"], CommitKind> = {
  fact: "fact", decision: "decision", entitlement: "entitlement", question: "question", ruling: "ruling", rule: "rule_event", journal: "journal_event",
  replay: "revert", access_denied: "access_denied", reminder: "question", llm_call: "llm_call", info: "fact",
};

export function addCommit(s: MockState, kind: CommitKind, actor: string, at: string, payload: unknown, payload_ref: string, message: string, inputs: string[] = []): Commit {
  const parent = s.commits.length ? s.commits[s.commits.length - 1].hash : null;
  const payload_hash = hashOf(payload);
  const fullInputs = kind === "decision" || kind === "entitlement" || kind === "revert" ? [...inputs, ENGINE_SHA, `cal@${CAL}`] : inputs;
  const hash = sha256(canonical({ kind, parent, payload_hash, inputs: fullInputs, at, actor }));
  const c: Commit = { hash, parent, kind, at, actor, payload_hash, payload_ref, inputs: fullInputs, message };
  s.commits.push(c);
  return c;
}

/** The next event time: the clock plus one second per event written since it last moved. */
export function nextAt(s: MockState) {
  s.tick += 1;
  return isoZ(Date.parse(s.knownAt) + s.tick * 1000);
}

type EventInit = Omit<TraceEvent, "seq" | "at"> & { at?: string };

export function emit(s: MockState, init: EventInit, stormId: string | null, opts: { commitKind?: CommitKind; payload?: unknown; inputs?: string[]; silent?: boolean } = {}): TraceEvent {
  const seq = (s.trace[s.trace.length - 1]?.seq ?? 0) + 1;
  const at = init.at ?? nextAt(s);
  const event: TraceEvent = { seq, at, kind: init.kind, actor: init.actor, summary: init.summary, ref: init.ref ?? null, chip: init.chip, amount_cents: init.amount_cents ?? null };
  s.trace.push(event);
  if (stormId) s.eventStorm.set(seq, stormId);
  addCommit(s, opts.commitKind ?? COMMIT_KIND[event.kind], event.actor, at, opts.payload ?? event, event.ref ?? `event:${seq}`, event.summary, opts.inputs ?? []);
  if (!opts.silent) for (const fn of listeners) fn(event);
  return event;
}

/** Record (or re-record) a flight's decision as a commit and remember it for FlightDecision.commit. */
export function commitDecision(s: MockState, storm: StormDef, spec: FlightSpec, at: string, actor = "agent.engine") {
  s.meta.set(spec.flight.id, { known_at: at, commit: null });
  s.metaVersion += 1;
  const d = decide(storm, spec, ctxOf(s));
  if (!d) return;
  const inputs = d.evidence.map((e) => `fact:${sha256(e.fact_id).slice(0, 16)}`);
  const c = addCommit(s, "decision", actor, at, { ...d, commit: null }, `decision:${spec.flight.id}`, `${spec.flight.number} ${d.cause} · ${d.extraordinary.replace(/_/g, " ")}${d.recoded ? ` · recoded ${d.recode_label}` : ""}`, inputs);
  s.meta.set(spec.flight.id, { known_at: at, commit: c.hash });
  s.metaVersion += 1;
}

// ---------- read views ----------
export const LEARNED: LearnedItem[] = [
  { text: "Read 18 months of claims · 35% of owed long-haul passengers claim · takes the 50% reroute cut", support: "41 of 42", rule_ref: "R-MIN-1@1" },
  { text: "35% expected ultimate claim rate long haul · 27% medium · 20% short (history to M18 + tail judgment)", support: "1,214 long-haul claims to M18", rule_ref: "LH-v1" },
  { text: "OCC batch-codes whole storm days as weather: 12 of 108 coded storm-day cancellations were really technical", support: "12 of 108", rule_ref: "REG-C549-TECHNICAL@1" },
  { text: "Who rules what: vouchers → Claims Lead · legal patterns → Legal · releases → Controller", support: "42 past escalations", rule_ref: null },
];

/** Every role but the Claims Lead sees passenger PII masked (Ops never sees it; Legal gets case facts without PII). */
export const seesPii = (role: Role) => role === "claims_lead" || role === "agent.reader";

export function mask<T>(value: T, role: Role): T {
  if (seesPii(role)) return value;
  let json = JSON.stringify(value);
  for (const p of T.PII_STRINGS) json = json.split(p).join("[redacted]");
  return JSON.parse(json) as T;
}

/** Strip mock-internal fields so payloads stay contract-shaped (plus the additive `others_settled`). */
export function publicQuestion(s: MockState, q: MockQuestion, role: Role): Question & { others_settled: number } {
  const { storm_id, ...rest } = q;
  const storm = stormById(s, storm_id);
  const others = storm ? baseCounters(storm, ctxOf(s)).settled : 0;
  return mask({ ...rest, others_settled: q.others_settled ?? others }, role);
}

export function stormQuestions(s: MockState, stormId: string) {
  return s.questions.filter((q) => q.storm_id === stormId);
}

export function counters(s: MockState, storm: StormDef): Record<string, number> {
  const c = baseCounters(storm, ctxOf(s));
  const qs = stormQuestions(s, storm.id);
  return {
    ...c,
    questions: qs.length,
    open_questions: qs.filter((q) => q.status !== "answered").length,
    people: new Set(qs.map((q) => q.routed_to)).size,
    repeat_questions: 0,
  };
}

export function stormRun(s: MockState, storm: StormDef, role: Role): StormRun {
  const ctx = ctxOf(s);
  const money = stormMoney(storm, ctx);
  return {
    id: storm.id,
    station: storm.station,
    date: storm.date,
    windows: clone(storm.windows),
    metar: clone(storm.metar),
    flights: storm.flights.map((spec) => ({ flight: clone(spec.flight), decision: decide(storm, spec, ctx) })),
    counters: counters(s, storm),
    entitlement_cents: money.entitlement_cents,
    liability_drafted_cents: money.liability_drafted_cents,
    learned: clone(LEARNED),
    questions: stormQuestions(s, storm.id).map((q) => publicQuestion(s, q, role)),
    feed: s.trace.filter((e) => s.eventStorm.get(e.seq) === storm.id).map((e) => ({ ...e })),
    real_context: clone(storm.real_context),
    message: storm.message,
  };
}

export function stormSummaries(s: MockState): StormSummary[] {
  return s.storms.map((storm) => ({
    id: storm.id,
    station: storm.station,
    date: storm.date,
    cancelled: storm.flights.filter((f) => f.flight.status === "cancelled").length,
    questions: stormQuestions(s, storm.id).length,
    liability_drafted_cents: stormMoney(storm, ctxOf(s)).liability_drafted_cents,
  }));
}

/** Rules with `times_cited` as a view over the current decisions (frozen when a version retires). */
export function rulesView(s: MockState): Rule[] {
  return [...s.rules].sort(byPrecedence).map((r) => ({ ...clone(r), times_cited: r.status === "active" ? citations(s, r) : (r.times_cited ?? 0) }));
}

export function citations(s: MockState, r: Rule): number {
  const ctx = ctxOf(s);
  let n = 0;
  const ref = ruleRef(r);
  for (const storm of s.storms) {
    for (const spec of storm.flights) {
      const d = decide(storm, spec, ctx);
      if (!d) continue;
      if (d.rules_applied.includes(ref)) n += 1;
      if (r.id === "R-MIN-1" && spec.flight.id === HERO_FLIGHT && isOwed(d)) n += 14;
    }
    if (r.id === "R-CL-1") n += voucherCases(storm).filter((c) => voucherSettled(c, ctx)).length;
  }
  if (r.id === "R-CTL-1") n += 1;
  if (r.id === "HC-SOD-1") n += s.accessLog.filter((a) => !a.allowed && /SoD/.test(a.reason)).length;
  if (r.id === "HC-OFFSET-1") n += s.storms.reduce((t, storm) => t + voucherCases(storm).length, 0);
  if (r.id === "HC-EXT-1") n += s.extRefusals;
  if (r.id === "HC-LOCK-1") n += s.locked.length;
  if (r.id === "HC-PAYOUT-1" || r.id === "HC-MAT-1") n += s.storms.reduce((t, storm) => t + storm.flights.filter((spec) => isOwed(decide(storm, spec, ctx))).length, 0);
  return n;
}

// ---------- Flight File ----------
function mark(at: string, kind: string, label: string, text: string, source_id?: string): TimelineMark {
  return source_id ? { at, kind, label, text, source_id } : { at, kind, label, text };
}

function timeline(s: MockState, storm: StormDef, spec: FlightSpec, d: FlightDecision | null): TimelineMark[] {
  const f = spec.flight;
  const w = mainWindow(storm);
  const metarAt = (t: string, label: string) => {
    const o = nearestObs(storm.metar, t);
    return mark(o.valid, "metar", label, o.raw, `metar:${storm.id}`);
  };
  const marks: TimelineMark[] = [];
  if (f.id === HERO_FLIGHT) {
    marks.push(
      mark("2025-01-23T21:40:00Z", "tech_log", "AOG · no MEL relief", T.TECHLOG_NS31, "tech_log:EI-NSB@2025-01-23"),
      mark("2025-01-23T22:15:00Z", "mcc", "No EDP in DUB stores · pool unit ETA 25 Jan 14:00Z", T.MCC_NS31, "mcc_log:EI-NSB@2025-01-23"),
      mark("2025-01-23T23:30:00Z", "window", "minor window 23:30–00:30Z", nearestObs(storm.metar, "2025-01-23T23:30:00Z").raw, `metar:${storm.id}`),
      mark(w?.start ?? "2025-01-24T02:30:00Z", "window", `storm window opens ${hhmmZ(w?.start ?? "2025-01-24T02:30:00Z")}`, nearestObs(storm.metar, w?.start ?? "2025-01-24T02:30:00Z").raw, `metar:${storm.id}`),
      mark("2025-01-24T05:12:00Z", "occ", "OCC cancel list · all 27 coded 71/72", T.OCC_EOWYN, `occ_log:${storm.id}`),
      mark("2025-01-24T05:40:00Z", "spares", "No long-range tail at DUB", T.SPARES_EOWYN, `spares:${storm.id}`),
      mark("2025-01-24T06:02:00Z", "crm", "CRM bot · first of 32 refunds initiated", T.CRM_BOT_FIRST, "crm:NS31@2025-01-24:bot"),
      metarAt("2025-01-24T07:00:00Z", "peak gust 56 kt"),
      mark("2025-01-24T09:40:00Z", "crm", "CRM bot · 32nd refund · 'weather, no compensation' emails", T.CRM_BOT_LAST, "crm:NS31@2025-01-24:bot"),
      metarAt("2025-01-24T12:00:00Z", "gust 56 kt again"),
      mark("2025-01-24T14:52:00Z", "crm", "T2 service desk · €300 voucher in lieu to 14C (unsigned)", T.CRM_14C, "crm:NS31@2025-01-24:14C"),
      mark(w?.end ?? "2025-01-24T15:00:00Z", "window", `storm window closes ${hhmmZ(w?.end ?? "2025-01-24T15:00:00Z")}`, nearestObs(storm.metar, w?.end ?? "2025-01-24T15:00:00Z").raw, `metar:${storm.id}`),
      mark("2025-01-24T15:30:00Z", "operated", "11 Northstar departures operate 15:30–17:30Z", "NS120 NS122 NS124 NS126 NS128 NS130 NS132 NS134 NS136 NS138 NS140", `schedule:${storm.id}`),
      metarAt("2025-01-24T16:00:00Z", "16:00Z · 11 kt · gusts ≤25 kt from here"),
      mark(f.sched_dep, "schedule", `NS31 STD ${hhmmZ(f.sched_dep)} · ${d?.window_margin_min ?? 90} min after the window`, scheduleLine(spec), `schedule:${f.id}`),
    );
    return marks;
  }
  const hub = hubOf(storm);
  const occAt = String(storm.real_context.occ_at ?? (storm.kind === "herminia" ? "2025-01-26T09:55:00Z" : "2025-01-24T05:12:00Z"));
  if (w) marks.push(mark(w.start, "window", `storm window opens ${hhmmZ(w.start)}`, nearestObs(storm.metar, w.start).raw, `metar:${storm.id}`));
  const log = storm.techLogs[f.id];
  if (f.status === "cancelled") {
    if (log?.occ) marks.push(mark(log.occ.at ?? occAt, "occ", `OCC · coded ${f.ops_cause_code ?? "—"}`, log.occ.quote, log.occ.source));
    else marks.push(mark(occAt, "occ", `OCC cancel list · coded ${f.ops_cause_code ?? "—"}`, storm.occ.text, storm.occ.source));
  }
  if (log) marks.push(mark(log.logged_at, "tech_log", "AOG · no MEL relief", log.text, log.source));
  const aog = s.injected.get(f.id);
  if (aog) marks.push(mark(aog.logged_at, "tech_log", "AOG inside the window (injected) · concurrent causes", aog.span, aog.source_id));
  const k = storm.knockOn[f.number];
  if (spec.group === "knock_on") {
    if (k) marks.push(mark(occAt, "spares", "no spare within 3 h", k.spares, `spares:${storm.id}`));
    marks.push(mark(f.sched_dep, "schedule", `STD ${hhmmZ(f.sched_dep)} at ${f.origin} · calm`, scheduleLine(spec), `schedule:${f.id}`));
    if (f.dest === hub) marks.push(metarAt(f.sched_arr, `STA ${hhmmZ(f.sched_arr)} at ${hub} · calm`));
    else if (f.origin === hub) marks.push(metarAt(f.sched_dep, `STD ${hhmmZ(f.sched_dep)} at ${hub} · calm`));
    if (k) marks.push(mark(f.sched_dep, "pss", "earliest reroute offered", k.pss, `pss:${storm.id}`));
  } else if (f.status === "operated") {
    marks.push(mark(f.sched_dep, "schedule", `STD ${hhmmZ(f.sched_dep)}`, scheduleLine(spec), `schedule:${f.id}`));
    if (f.actual_dep) marks.push(mark(f.actual_dep, "operated", `operated · off blocks ${hhmmZ(f.actual_dep)}`, `${f.number} ${f.origin}-${f.dest} ATD ${hhmmZ(f.actual_dep)} ATA ${f.actual_arr ? hhmmZ(f.actual_arr) : "—"}`, `schedule:${f.id}`));
    if (f.origin === hub) marks.push(metarAt(f.actual_dep ?? f.sched_dep, "METAR at departure"));
    else if (f.dest === hub) marks.push(metarAt(f.actual_arr ?? f.sched_arr, "METAR at arrival"));
  } else {
    const atArr = f.dest === hub && f.origin !== hub;
    const t = atArr ? f.sched_arr : f.sched_dep;
    marks.push(mark(f.sched_dep, "schedule", `STD ${hhmmZ(f.sched_dep)}${atArr ? ` · STA ${hhmmZ(f.sched_arr)}` : ""}`, scheduleLine(spec), `schedule:${f.id}`));
    if (atArr || f.origin === hub) marks.push(metarAt(t, `METAR at ${atArr ? "STA" : "STD"} ${hhmmZ(t)}`));
  }
  if (w) marks.push(mark(w.end, "window", `storm window closes ${hhmmZ(w.end)}`, nearestObs(storm.metar, w.end).raw, `metar:${storm.id}`));
  return marks.sort((a, b) => Date.parse(String(a.at)) - Date.parse(String(b.at)));
}

function explanation(storm: StormDef, spec: FlightSpec, d: FlightDecision, s: MockState): Draft {
  const f = spec.flight;
  const ctx = ctxOf(s);
  const w = mainWindow(storm);
  const win = windowLabel(w);
  const band = bandFor(f.origin, f.dest);
  const hubName = findAirport(storm.station)?.name ?? storm.station;
  let text: string;
  if (f.status === "operated") {
    text = `${f.number} operated (off blocks ${f.actual_dep ? hhmmZ(f.actual_dep) : hhmmZ(f.sched_dep)}), so there is no cancellation to settle and nothing is owed under Art. 5.`;
  } else if (f.id === HERO_FLIGHT) {
    text = `Not weather. Broken plane. ${f.aircraft} was grounded at Dublin from 23 Jan 21:40Z with a leaking engine-driven hydraulic pump and no MEL relief (tech log), before any storm window. No pump was in Dublin stores; the pool unit's ETA, quoted at 22:15Z, was 25 Jan 14:00Z. NS31 was due out at 16:30Z, ${d.window_margin_min} min after the Dublin storm window closed (${win}); from 16:00Z the METAR shows gusts ≤25 kt, and 11 Northstar departures operated between 15:30 and 17:30Z. A technical fault is not an extraordinary circumstance (EU261 Art. 5(3); CJEU C-549/07, C-257/14), so the OCC's code 71 is recoded to 41 and all 172 passengers are owed compensation: ${eur(fullEntitlementCents(spec, d, ctx))} full Art. 7 entitlement if every passenger claims; ${eur(liabilityCents(spec, d, ctx))} drafted at the 35% expected ultimate claim rate, pending approval.`;
  } else if (d.cause === "weather") {
    const atArr = spec.group !== "outbound_weather";
    const t = atArr ? f.sched_arr : f.sched_dep;
    const o = nearestObs(storm.metar, t);
    text = `${f.number} was due to ${atArr ? "land in" : "leave"} ${hubName} at ${hhmmZ(t)}, inside the storm window (${win}; ${o.raw.split(" ").slice(1, 3).join(" ")}). The storm is an extraordinary circumstance (EU261 Art. 5(3)), so there is no compensation; refunds and care are still due. Distance ${band.label}.`;
  } else if (d.cause === "knock_on") {
    const outbound = f.outbound_pair_id?.split("@")[0] ?? "the outbound";
    text = isHeld(d)
      ? `${f.number} never had an aircraft: ${outbound} was cancelled by the storm, so ${f.aircraft} never reached ${f.origin}. At ${f.number}'s STD (${hhmmZ(f.sched_dep)}) ${f.origin} was calm, and at its ${f.dest === hubOf(storm) ? `STA (${hhmmZ(f.sched_arr)}) ${hubName}` : `STD ${hubName}`} was outside the window. Whether a storm-cancelled rotation makes the return extraordinary is a legal question (CJEU C-74/19), so it is with Legal: one question covers every return of this pattern.`
      : `${f.number} is settled by ${d.rules_applied[0]}: a storm-cancelled rotation, no aircraft and crew within 3 h of STD, and the earliest reroute offered on any carrier. ${d.extraordinary === "extraordinary" ? "No compensation; refunds and care still due." : "Compensation is owed."}`;
  } else {
    const log = storm.techLogs[f.id];
    text = d.cause === "concurrent"
      ? `${f.number} has two candidate causes: the storm window (${win}) and an AOG logged inside it. Concurrent causes are a legal question, so Legal decides; until then the case is held and nothing is paid or released.`
      : `${f.number} is technical, not weather: ${f.aircraft} was AOG from ${log ? hhmmZ(log.logged_at) : "before the window"} with no MEL relief (tech log), and the flight was out of the storm window at both ends${d.window_margin_min ? ` (${d.window_margin_min} min clear)` : ""}. ${d.recoded ? `OCC's code ${d.recode_label?.split(" ")[0]} is recoded to 41. ` : ""}Compensation is owed: ${band.label}.`;
  }
  return { id: `DRAFT-explain:${f.id}`, kind: "explanation", text, numbers_verified: true, llm_commit: f.id === HERO_FLIGHT ? (s.commits.find((c) => c.kind === "llm_call" && c.payload_ref === `explain:${f.id}`)?.hash ?? null) : null, template_fallback: f.id !== HERO_FLIGHT };
}

const OPERATED_DECISION = (s: MockState, storm: StormDef, spec: FlightSpec): FlightDecision => {
  const f = spec.flight;
  const meta = ctxOf(s).meta(f.id);
  return {
    flight_id: f.id,
    cause: "unknown",
    extraordinary: "not_extraordinary",
    ops_cause_code: null,
    recoded: false,
    recode_label: null,
    in_window_dep: "out",
    in_window_arr: "out",
    window_margin_min: null,
    confidence: { score: null, kind: "cause", label: "cause-finding confidence", features: {}, caps: [], calibration_version: CAL },
    reason: "operated: no cancellation, nothing to decide",
    evidence: f.origin === hubOf(storm) ? [{ fact_id: `F:flight:${f.id}:flight.actual_dep`, source_id: `schedule:${f.id}`, field: "flight.actual_dep", value: f.actual_dep, quote: scheduleLine(spec), role: "context", trust_tier: 2, struck: false }, { fact_id: `F:EIDW:${f.actual_dep}:metar`, source_id: `metar:${storm.id}`, field: "metar.at_departure", value: null, quote: nearestObs(storm.metar, f.actual_dep ?? f.sched_dep).raw, role: "context", trust_tier: 1, struck: false }] : [],
    rules_applied: [],
    legal_basis: [],
    outcome: "auto",
    routed_to: null,
    question_id: null,
    known_at: meta.known_at,
    commit: null,
  };
};

export function flightFile(s: MockState, flightId: string, role: Role): FlightFile | null {
  const hit = specOf(s, flightId);
  if (!hit) return null;
  const { storm, spec } = hit;
  const ctx = ctxOf(s);
  const d = decide(storm, spec, ctx) ?? OPERATED_DECISION(s, storm, spec);
  const summary = spec.flight.status === "operated" ? { coupons: spec.flight.pax, elections: {}, full_entitlement_cents: 0, drafted_liability_cents: 0, claim_rate: null, status_line: "operated · nothing to settle", ...pickBand(spec) } : entitlementsSummary(storm, spec, d, ctx);
  const file: FlightFile = {
    flight: clone(spec.flight),
    decision: d,
    entitlements_summary: summary,
    sample_entitlements: spec.flight.status === "operated" ? [] : sampleEntitlements(storm, spec, d, ctx),
    // Day-1 drafts for this flight, the compensation estimate first (later claims and true-ups live on Close).
    journal_preview: s.journal
      .filter((e) => e.source_decision_id === flightId && e.event_date === spec.flight.sched_dep.slice(0, 10))
      .sort((a, b) => Number(b.kind === "compensation_estimate") - Number(a.kind === "compensation_estimate") || a.id.localeCompare(b.id))
      .map((e) => clone(e)),
    timeline: timeline(s, storm, spec, decide(storm, spec, ctx)),
    handoff: flightId === HERO_FLIGHT ? { refunds_already_initiated: 32, not_repeated: true, rights_notices_drafted: 32, drafter_pii_seen: 0, bot_email_said: "weather, no compensation", clearing_account: "2125", clearing_balance_cents: 0, names_merged: "in code, after drafting" } : null,
    explanation: explanation(storm, spec, d, s),
  };
  return mask(file, role);
}

function pickBand(spec: FlightSpec) {
  const b = bandFor(spec.flight.origin, spec.flight.dest);
  return { distance_km: b.distance_km, band_eur: b.band_eur, band_margin_km: b.band_margin_km, band_label: b.label };
}

// ---------- cohorts (for the books) ----------
export function cohortEntitlement(s: MockState, cohort: string): number {
  const ctx = ctxOf(s);
  const hero = specOf(s, HERO_FLIGHT);
  if (cohort === COHORT_ISHA) return 6_000_000;
  if (cohort === COHORT_LH && hero) return fullEntitlementCents(hero.spec, decide(hero.storm, hero.spec, ctx), ctx);
  const ids = cohort === COHORT_MED ? ["NS113@2025-01-24", "NS115@2025-01-24"] : cohort === COHORT_SHORT ? ["NS117@2025-01-24"] : [];
  return ids.reduce((sum, id) => {
    const h = specOf(s, id);
    return h ? sum + fullEntitlementCents(h.spec, decide(h.storm, h.spec, ctx), ctx) : sum;
  }, 0);
}

// ---------- baseline ----------
const BASELINE_ACCESS: AccessDecision[] = [
  { at: "2025-01-24T06:02:00Z", principal: "agent.crm_bot", action: "initiate_refund", resource: "coupons:NS31@2025-01-24", allowed: true, reason: "CRM bot may initiate refunds on direct-sold coupons; Books clears them through 2125" },
  { at: "2025-01-25T05:59:03Z", principal: "agent.reader", action: "read", resource: "tech_log:EI-NSB@2025-01-23", allowed: true, reason: "Reader reads sources incl. PII and emits pseudonymous facts" },
  { at: "2025-01-25T05:59:22Z", principal: "agent.drafter", action: "read", resource: "coupons:NS31@2025-01-24", allowed: true, reason: "redacted: the Drafter sees no PII · names merged in code after drafting" },
  { at: "2025-01-25T07:02:40Z", principal: "ops", action: "read", resource: "claims:CLM-2025-0131", allowed: true, reason: "redacted: Ops sees flights and causes, no passenger data" },
  { at: "2025-01-25T07:30:00Z", principal: "legal", action: "read", resource: "coupons:NS31@2025-01-24:14C", allowed: true, reason: "redacted: Legal gets case facts without PII" },
  { at: "2025-01-25T08:12:00Z", principal: "claims_lead", action: "read", resource: "claims:CLM-2025-0131", allowed: true, reason: "the Claims Lead sees PII for claims" },
];

function createBaseline(): MockState {
  const s: MockState = {
    knownAt: BASELINE_CLOCK,
    tick: 0,
    storms: [clone(EOWYN), clone(HERMINIA)],
    rules: baselineRules(),
    proposals: new Map(),
    questions: baselineQuestions(EOWYN),
    rulings: [],
    trace: [],
    eventStorm: new Map(),
    commits: [],
    journal: baselineJournal(),
    locked: ["2025-01"],
    lockedWrites: 0,
    accessLog: BASELINE_ACCESS.map((a) => ({ ...a })),
    meta: new Map(),
    injected: new Map(),
    confirmed: new Map(),
    ids: { je: 300, q: 6, ruling: 1, inject: 1, draft: 1 },
    metaVersion: 0,
    cache: { key: "", memo: new Map() },
    extRefusals: 0,
    monthEnd: new Set(["2025-02"]),
  };
  const [eowyn, herminia] = s.storms;

  // Onboarding (20 Jan): what it mined from the airline's own history
  const learn = (at: string, summary: string, ref: string) => emit(s, { at, kind: "rule", actor: "agent.engine", summary, ref, chip: "LEARNED" }, EOWYN_ID, { silent: true });
  learn("2025-01-20T09:00:00Z", "Learned from 18 months of claims: takes the 50% reroute cut on long-haul partner reroutes · 41 of 42", "R-MIN-1@1");
  learn("2025-01-20T09:00:05Z", "Learned the claim curves: 35% of owed long-haul passengers claim (history to M18 + tail judgment) · 27% medium · 20% short", "LH-v1");
  for (const r of s.rules) addCommit(s, "rule_event", "agent.engine", "2025-01-20T09:00:10Z", r, `rule:${ruleRef(r)}`, `${ruleRef(r)} recorded · ${r.status}`);
  const herminiaSource = (id: string) => /2025-01-26|@2025-01-25/.test(id);
  const factCommits = (filter: (id: string) => boolean) => {
    for (const src of [...SOURCES].filter((x) => filter(x.id)).sort((a, b) => a.received_at.localeCompare(b.received_at))) {
      addCommit(s, "fact", src.kind === "metar" ? "parser:iem@1" : src.trust_tier === 1 ? "agent.reader" : "normalize@1", src.received_at, { source_id: src.id, sha256: src.sha256 }, `fact:${src.id}`, `${src.title} · sha256 ${src.sha256.slice(0, 12)}`);
      if (src.kind === "tech_log") addCommit(s, "llm_call", "agent.reader", src.received_at, { source_id: src.id, prompt: "reader-v1", model: "claude-opus-5-5" }, `llm:reader:${src.id}`, "Reader extracted the AOG facts · every span verbatim · values re-parsed", [`source:${src.id}`, "prompt:reader-v1"]);
    }
  };
  const entitlementCommits = (storm: StormDef, at: string) => {
    const ctx = ctxOf(s);
    for (const spec of storm.flights) {
      const d = decide(storm, spec, ctx);
      if (!d) continue;
      const full = fullEntitlementCents(spec, d, ctx);
      addCommit(s, "entitlement", "agent.engine", at, { flight: spec.flight.id, full_entitlement_cents: full, liability_cents: liabilityCents(spec, d, ctx) }, `entitlement:${spec.flight.id}`, `${spec.flight.number} · ${spec.flight.pax} entitlements · ${full ? eur(full) : "no compensation"}`, [`decision:${s.meta.get(spec.flight.id)?.commit ?? ""}`]);
    }
  };
  const jeCommits = (filter: (e: JournalEntry) => boolean) => {
    for (const entry of s.journal.filter(filter).sort((a, b) => a.event_date.localeCompare(b.event_date) || a.id.localeCompare(b.id))) addCommit(s, "journal_event", entry.preparer, `${entry.event_date}T23:00:00Z`, entry, `je:${entry.id}`, `${entry.id} · ${entry.memo.split(" · ")[0]}`);
  };
  factCommits((id) => !herminiaSource(id));

  // Storm Éowyn, the morning after
  const e = (at: string, init: Omit<EventInit, "at">) => emit(s, { at, ...init }, EOWYN_ID, { silent: true });
  e("2025-01-25T05:59:01Z", { kind: "fact", actor: "parser:iem@1", summary: `Read ${eowyn.metar.length} real METAR obs at EIDW · storm window ${windowLabel(mainWindow(eowyn))}, peak gust ${mainWindow(eowyn)?.peak_gust_kt} kt`, ref: `metar:${EOWYN_ID}`, chip: "INFO" });
  e("2025-01-25T05:59:02Z", { kind: "fact", actor: "agent.reader", summary: "Read the OCC cancel list (05:12Z): 27 cancellations coded 71/72", ref: `occ_log:${EOWYN_ID}`, chip: "INFO" });
  emit(s, { at: "2025-01-25T05:59:03Z", kind: "llm_call", actor: "agent.reader", summary: "Read the AMOS tech log for EI-NSB: AOG 23 Jan 21:40Z, no MEL relief · 3 facts verified, 0 dropped", ref: "tech_log:EI-NSB@2025-01-23", chip: "INFO" }, EOWYN_ID, { silent: true, inputs: ["source:tech_log:EI-NSB@2025-01-23", "prompt:reader-v1"] });
  for (const spec of eowyn.flights) commitDecision(s, eowyn, spec, "2025-01-25T06:00:00Z");
  entitlementCommits(eowyn, "2025-01-25T05:59:14Z");
  jeCommits((e) => e.event_date === "2025-01-24");
  e("2025-01-25T05:59:10Z", { kind: "decision", actor: "agent.engine", summary: "13 outbound flights inside the DUB window · weather · no compensation; refunds and care still due", ref: EOWYN_ID, chip: "APPLIED" });
  e("2025-01-25T05:59:11Z", { kind: "decision", actor: "agent.engine", summary: "6 return sectors landed inside the DUB window · weather · no compensation; refunds and care still due", ref: EOWYN_ID, chip: "APPLIED" });
  e("2025-01-25T05:59:12Z", { kind: "decision", actor: "agent.engine", summary: "4 overnight inbounds confirmed as destination weather (72)", ref: EOWYN_ID, chip: "APPLIED" });
  e("2025-01-25T05:59:15Z", { kind: "decision", actor: "agent.engine", summary: "NS31 recoded 71 → 41 · 172 payouts drafted", ref: HERO_FLIGHT, chip: "DRAFTED", amount_cents: 3_465_000 });
  e("2025-01-25T05:59:16Z", { kind: "rule", actor: "agent.engine", summary: "R-MIN-1 cited on 14 NS31 partner reroutes · Art. 7(2)(c) 50% cut", ref: "R-MIN-1@1", chip: "CITED" });
  e("2025-01-25T05:59:18Z", { kind: "journal", actor: "agent.engine", summary: "NS31 EU261 compensation liability drafted, pending approval · Dr 4090 / Cr 2140", ref: "JE-000101", chip: "DRAFTED", amount_cents: 3_465_000 });
  e("2025-01-25T05:59:20Z", { kind: "entitlement", actor: "agent.engine", summary: "32 CRM-bot refunds on NS31 already initiated · not repeated · 2125 clears to 0", ref: HERO_FLIGHT, chip: "APPLIED", amount_cents: 1_632_000 });
  emit(s, { at: "2025-01-25T05:59:22Z", kind: "llm_call", actor: "agent.drafter", summary: "Drafted 32 corrected rights notices (Art. 14(2)) · Drafter saw 0 PII · names merged in code", ref: HERO_FLIGHT, chip: "DRAFTED" }, EOWYN_ID, { silent: true, inputs: ["prompt:drafter-v1", "pii_fields:0"] });
  addCommit(s, "llm_call", "agent.drafter", "2025-01-25T05:59:23Z", { draft: `DRAFT-explain:${HERO_FLIGHT}` }, `explain:${HERO_FLIGHT}`, "Drafter wrote the NS31 explanation · numbers verified against the evidence", ["prompt:drafter-v1"]);
  e("2025-01-25T06:00:00Z", { kind: "question", actor: "agent.engine", summary: "Asked the Claims Lead about the 14C service-desk voucher", ref: "Q-1", chip: "ASKED", amount_cents: 60_000 });
  e("2025-01-25T06:00:30Z", { kind: "question", actor: "agent.engine", summary: "Asked Legal once about 3 knock-on returns (NS113, NS115, NS117)", ref: "Q-2", chip: "ASKED", amount_cents: 4_749_600 });
  e("2025-01-25T06:00:31Z", { kind: "journal", actor: "agent.engine", summary: "Held knock-on returns accrued at segment rates (IFRS 15.56) · drafted, pending approval", ref: "JE-000102", chip: "HELD", amount_cents: 4_749_600 });
  e("2025-01-25T06:00:35Z", { kind: "question", actor: "agent.engine", summary: "Asked the Controller about derecognising the Storm Isha tail", ref: "Q-3", chip: "ASKED", amount_cents: 360_000 });
  e("2025-01-25T06:00:40Z", { kind: "journal", actor: "agent.engine", summary: "Care for the night of 24 Jan accrued · drafted, pending approval", ref: "JE-000109", chip: "DRAFTED", amount_cents: 22_700_000 });
  s.accessLog.push({ at: "2025-01-25T06:41:12Z", principal: "agent.drafter", action: "approve_payout", resource: `payouts:${HERO_FLIGHT}`, allowed: false, reason: "SoD · the Drafter prepared these 172 payouts; payouts need the Claims Lead" });
  e("2025-01-25T06:41:12Z", { kind: "access_denied", actor: "agent.drafter", summary: "agent.drafter approve_payout → DENIED · SoD", ref: HERO_FLIGHT, chip: "DENIED" });
  e("2025-01-25T09:00:00Z", { kind: "reminder", actor: "agent.engine", summary: `Reminded the Claims Lead: Q-1 waiting 3h · ${baseCounters(eowyn, ctxOf(s)).settled.toLocaleString("en-US")} others settled`, ref: "Q-1", chip: "INFO" });

  // Storm Herminia, the morning after (its voucher cases wait on Q-1's pattern)
  const h = (at: string, init: Omit<EventInit, "at">) => emit(s, { at, ...init }, HERMINIA_ID, { silent: true });
  h("2025-01-27T05:59:01Z", { kind: "fact", actor: "parser:iem@1", summary: `Read ${herminia.metar.length} real METAR obs at EIDW · storm window ${windowLabel(mainWindow(herminia))}, peak gust ${mainWindow(herminia)?.peak_gust_kt} kt`, ref: `metar:${HERMINIA_ID}`, chip: "INFO" });
  factCommits(herminiaSource);
  for (const spec of herminia.flights) commitDecision(s, herminia, spec, "2025-01-27T06:00:00Z");
  entitlementCommits(herminia, "2025-01-27T05:59:14Z");
  h("2025-01-27T05:59:10Z", { kind: "decision", actor: "agent.engine", summary: "3 flights inside the DUB window · weather · no compensation; refunds and care still due", ref: HERMINIA_ID, chip: "APPLIED" });
  h("2025-01-27T05:59:15Z", { kind: "decision", actor: "agent.engine", summary: "NS112 recoded 71 → 41 · 178 payouts drafted", ref: "NS112@2025-01-26", chip: "DRAFTED", amount_cents: 1_922_400 });
  h("2025-01-27T05:59:16Z", { kind: "decision", actor: "agent.engine", summary: "NS30 BOS→DUB technical (41, as coded) · 168 payouts drafted", ref: "NS30@2025-01-25", chip: "DRAFTED", amount_cents: 3_528_000 });
  h("2025-01-27T05:59:20Z", { kind: "entitlement", actor: "agent.engine", summary: "32 unsigned in-lieu vouchers held · same pattern as Q-1, waiting on the Claims Lead", ref: HERMINIA_ID, chip: "HELD", amount_cents: 1_300_000 });
  jeCommits((e) => e.event_date !== "2025-01-24");
  return s;
}

/** First period on or after `period` that isn't locked (adjustments land there; locked periods stay untouched). */
export function openPeriod(s: MockState, period: string): string {
  let p = period;
  while (s.locked.includes(p)) {
    const [y, m] = p.split("-").map(Number);
    p = m === 12 ? `${y + 1}-01` : `${y}-${String(m + 1).padStart(2, "0")}`;
  }
  return p;
}

export const nextJeId = (s: MockState) => `JE-${String(++s.ids.je).padStart(6, "0")}`;
export const nextQuestionId = (s: MockState) => `Q-${s.ids.q++}`;
export const nextRulingId = (s: MockState) => `RUL-${s.ids.ruling++}`;
export { addMin };
