import type { Blame, CfoMetrics, Evidence, FlightDecision, FlightFile, FlightRow, JournalEntry, MetarObs, Question, Role, Rule, StormRun, StormWindow } from "@/api/types";
import { mainWindowOf } from "@/components/storm/model";
import { verdictOf, type VerdictKind } from "@/components/verdict";
import { airport, iataOf } from "@/lib/airports";
import { count, eur, zulu, zuluDay } from "@/lib/format";

/**
 * Everything the story says comes from the API; this module only picks and shapes it. Identifiers
 * (which storm, which flight) are the plan's demo world; no count or amount is typed in here.
 */
export const HERO_FLIGHT = "NS31@2025-01-24";
export const NEXT_STORM = "EIDW@2025-01-26";

export const ms = (iso: string | null | undefined) => (iso ? Date.parse(iso) : NaN);

/** "2025-01-24T16:30:00Z" → "16:30". */
export function hhmm(iso: string | null | undefined): string {
  const t = ms(iso);
  if (Number.isNaN(t)) return "";
  const d = new Date(t);
  return `${String(d.getUTCHours()).padStart(2, "0")}:${String(d.getUTCMinutes()).padStart(2, "0")}`;
}

/** The METAR report nearest to a time (what a dispatcher was looking at). */
export function nearestObs(metar: MetarObs[] | undefined, iso: string): MetarObs | null {
  const t = ms(iso);
  if (!metar?.length || Number.isNaN(t)) return null;
  return metar.reduce((a, b) => (Math.abs(ms(b.valid) - t) < Math.abs(ms(a.valid) - t) ? b : a));
}

/** The storm's main window (the shared helper: the longest one the engine computed). */
export const mainWindow = (windows: StormWindow[] | undefined): StormWindow | null => (windows?.length ? mainWindowOf(windows) : null);

/** The flight the re-check recoded (NS31 on Éowyn). */
export function focusRow(run: StormRun | undefined): FlightRow | null {
  return run?.flights.find((r) => r.decision?.recoded) ?? null;
}

/** Evidence from one kind of source (tech_log, occ_log, metar, mcc_log …), by the source id's prefix. */
export function evidenceFrom(decision: FlightDecision | null | undefined, kind: string): Evidence | null {
  const re = new RegExp(`(^|[^a-z])${kind}`, "i");
  return decision?.evidence.find((e) => re.test(e.source_id) && !!e.quote) ?? decision?.evidence.find((e) => re.test(e.source_id)) ?? null;
}

const MONTHS = ["JAN", "FEB", "MAR", "APR", "MAY", "JUN", "JUL", "AUG", "SEP", "OCT", "NOV", "DEC"];

/** "23JAN 21:40Z …" → that instant (the year comes from the storm date). */
export function amosTime(text: string | null | undefined, year: number): Date | null {
  const m = text?.match(/\b(\d{1,2})(JAN|FEB|MAR|APR|MAY|JUN|JUL|AUG|SEP|OCT|NOV|DEC)\s+(\d{2}):?(\d{2})Z/);
  if (!m) return null;
  return new Date(Date.UTC(year, MONTHS.indexOf(m[2]), Number(m[1]), Number(m[3]), Number(m[4])));
}

/** "05:12Z OCC DM: …" → "05:12Z". */
export const leadingZulu = (text: string | null | undefined) => text?.match(/\b(\d{2}:\d{2}Z)\b/)?.[1] ?? null;

/** A log line split after each full stop, for a card that reveals it line by line. Keeps "N/S." with its sentence. */
export function sentences(text: string | null | undefined): string[] {
  if (!text) return [];
  return text
    .split(/(?<=\.)\s+(?=[A-Z0-9])/)
    .map((s) => s.trim())
    .filter(Boolean);
}

/** The tech-log entry behind the recode: its verbatim line, when it was logged, and its ATA chapter. */
export function techLog(file: FlightFile | undefined, run: StormRun | undefined) {
  const d = file?.decision;
  const e = evidenceFrom(d, "tech_log");
  const quote = e?.quote ?? null;
  const year = Number((run?.date ?? file?.flight.date ?? "").slice(0, 4)) || new Date().getUTCFullYear();
  const valueAt = typeof e?.value === "string" && /^\d{4}-\d{2}-\d{2}T/.test(e.value) ? new Date(e.value) : null;
  const at = valueAt ?? amosTime(quote, year);
  const ataRaw = d?.evidence.find((x) => /ata/i.test(x.field) && /tech_log/i.test(x.source_id))?.value;
  const ata = typeof ataRaw === "string" || typeof ataRaw === "number" ? String(ataRaw).replace(/^(\d{2})(\d{2})$/, "$1-$2") : null;
  return quote || at ? { quote, at, ata, lines: sentences(quote) } : null;
}

/** When OCC sent its cancel list: the timeline mark, else a time at the head of the quoted line. */
export function occTime(file: FlightFile | undefined): string | null {
  const mark = file?.timeline.find((m) => /occ/i.test(`${m.kind ?? ""} ${m.source_id ?? ""}`));
  if (typeof mark?.at === "string") return `${hhmm(mark.at)}Z`;
  return leadingZulu(evidenceFrom(file?.decision, "occ")?.quote);
}

/** The aircraft type as the schedule line spells it ("A321XLR"), if the evidence quotes one. */
export function aircraftType(file: FlightFile | undefined): string | null {
  const q = file?.decision.evidence.find((e) => /^schedule/i.test(e.source_id))?.quote;
  return q?.match(/\b(A3\d{2}[A-Z]*|B7\d{2}[A-Z0-9-]*)\b/)?.[1] ?? null;
}

/** Short place names for the split-flap board (names only; codes and times come from the API). */
const CITY: Record<string, string> = {
  LHR: "London",
  CDG: "Paris",
  AMS: "Amsterdam",
  FRA: "Frankfurt",
  BCN: "Barcelona",
  MAD: "Madrid",
  LIS: "Lisbon",
  FCO: "Rome",
  MUC: "Munich",
  ATH: "Athens",
  JFK: "New York",
  EWR: "Newark",
  ORD: "Chicago",
  YYZ: "Toronto",
  BOS: "Boston",
};
export const cityOf = (iata: string) => CITY[iata] ?? airport(iata)?.name ?? iata;

export type BoardRow = {
  id: string;
  number: string;
  at: string;
  time: string;
  iata: string;
  city: string;
  /** what OCC typed: "71" / "72" */
  coded: string | null;
  verdict: VerdictKind;
  /** after the re-check: the recode ("41"), or who it's routed to */
  after: string | null;
  routedTo: Role | null;
  recoded: boolean;
};

/** The cancellations as two boards at the hub: departures at STD, arrivals at STA. */
export function boardRows(run: StormRun | undefined): { departures: BoardRow[]; arrivals: BoardRow[] } {
  if (!run) return { departures: [], arrivals: [] };
  const hub = iataOf(run.station);
  const rows = run.flights
    .filter((r) => r.flight.status === "cancelled")
    .map((r): BoardRow => {
      const f = r.flight;
      const dep = f.origin === hub;
      const at = dep ? f.sched_dep : f.sched_arr;
      const d = r.decision;
      const coded = f.ops_cause_code ?? d?.ops_cause_code ?? null;
      const recodedTo = d?.recoded ? (d.recode_label?.split("→").pop()?.trim() ?? null) : null;
      return {
        id: f.id,
        number: f.number,
        at,
        time: hhmm(at),
        iata: dep ? f.dest : f.origin,
        city: cityOf(dep ? f.dest : f.origin),
        coded,
        verdict: verdictOf(r),
        after: recodedTo,
        routedTo: d?.routed_to ?? null,
        recoded: !!d?.recoded,
      };
    });
  const byTime = (a: BoardRow, b: BoardRow) => ms(a.at) - ms(b.at) || a.number.localeCompare(b.number, "en", { numeric: true });
  const departing = new Set(run.flights.filter((r) => r.flight.origin === hub).map((r) => r.flight.id));
  return {
    departures: rows.filter((r) => departing.has(r.id)).sort(byTime),
    arrivals: rows.filter((r) => !departing.has(r.id)).sort(byTime),
  };
}

/** Far ends of every cancelled flight, for the route arcs (unique, with coordinates). */
export function routeEnds(run: StormRun | undefined) {
  if (!run) return [];
  const hub = iataOf(run.station);
  const seen = new Map<string, { iata: string; lon: number; lat: number; notweather: boolean }>();
  for (const r of run.flights) {
    if (r.flight.status !== "cancelled") continue;
    const end = r.flight.origin === hub ? r.flight.dest : r.flight.origin;
    const ap = airport(end);
    if (!ap) continue;
    const prev = seen.get(end);
    seen.set(end, { iata: end, lon: ap.lon, lat: ap.lat, notweather: (prev?.notweather ?? false) || verdictOf(r) === "notweather" });
  }
  return [...seen.values()];
}

const num = (v: unknown): number | null => (typeof v === "number" && Number.isFinite(v) ? v : null);

/**
 * The euros for the hero flight, from its Flight File first (entitlements_summary, contract request #5),
 * then the CFO view. Anything the API doesn't give stays null and the story leaves that step out.
 */
export function money(file: FlightFile | undefined, cfo: CfoMetrics | undefined) {
  const s = (file?.entitlements_summary ?? {}) as Record<string, unknown>;
  const sample = file?.sample_entitlements ?? [];
  const owed = sample.filter((e) => e.status === "owed");
  const elections = (s.elections ?? {}) as Record<string, unknown>;
  const reduction = (s.reduction_7_2 ?? {}) as Record<string, unknown>;
  const je: JournalEntry | null = file?.journal_preview.find((j) => j.kind === "compensation_estimate") ?? file?.journal_preview[0] ?? null;
  const jeAmount = je ? je.lines.reduce((a, l) => a + (l.dr_cents ?? 0), 0) : null;
  return {
    full: num(s.full_entitlement_cents) ?? num(cfo?.full_entitlement_cents),
    drafted: num(s.drafted_liability_cents) ?? jeAmount ?? num(cfo?.drafted_liability_cents),
    cash: num(cfo?.cash_basis_cents),
    sensitivity: num(cfo?.sensitivity_5pp_cents),
    claimRate: num(s.claim_rate),
    payouts: num(s.payouts_drafted) ?? num(s.coupons) ?? file?.flight.pax ?? null,
    statusLine: typeof s.status_line === "string" ? s.status_line : null,
    band: num(s.band_eur) ?? owed[0]?.band_eur ?? sample[0]?.band_eur ?? null,
    distanceKm: num(s.distance_km) ?? owed[0]?.distance_km ?? sample[0]?.distance_km ?? null,
    reduced: num(reduction.coupons) ?? num(elections.reroute_partner),
    je,
  };
}

/** Q1: the question the Claims Lead is asked about the service-desk voucher (sources disagree). */
export function voucherQuestion(questions: Question[] | undefined): Question | null {
  if (!questions?.length) return null;
  return (
    questions.find((q) => q.routed_to === "claims_lead" && q.reason_tag === "sources-disagree") ??
    questions.find((q) => /voucher/i.test(`${q.pattern} ${q.title}`)) ??
    null
  );
}

/** The rule a ruling on that question became (R-CL-1), once it exists. */
export function ruleFrom(rules: Rule[] | undefined, q: Question | null): Rule | null {
  if (!rules?.length) return null;
  return (
    rules.find((r) => r.tier === "claims_lead_ruling" && r.status !== "retired" && (q ? r.origin_example?.includes(q.case_refs[0] ?? "\u0000") || /voucher/i.test(r.kind) : true)) ??
    rules.find((r) => r.tier === "claims_lead_ruling") ??
    null
  );
}

// ---------- every euro, traced ----------
export type ChainTone = "money" | "rule" | "fault" | "metar" | "plain";
export type ChainStep = { key: string; label: string; quote: string | null; meta: string; tone: ChainTone; struck?: boolean };

const kindOf = (sourceId: string) => sourceId.split(":")[0];
const toneOfSource = (sourceId: string): ChainTone => (/tech_log|mcc_log/.test(sourceId) ? "fault" : /^metar/.test(sourceId) ? "metar" : "plain");

/** GET /blame, as chain steps (the server's own labels and quotes). */
export function chainFromBlame(blame: Blame | undefined): ChainStep[] {
  return (blame?.steps ?? []).map((s, i) => {
    const text = `${s.label} ${s.commit.payload_ref} ${s.quote ?? ""}`;
    const tone: ChainTone = s.commit.kind === "journal_event" || /€/.test(s.label) ? "money" : s.commit.kind === "rule_event" || s.commit.kind === "ruling" ? "rule" : /tech[ _-]?log|AOG|EDP/i.test(text) ? "fault" : /METAR|EIDW \d{6}Z/.test(text) ? "metar" : "plain";
    // one commit can stand behind several steps (a rule and its ruling), so the key carries the position
    return { key: `${i}:${s.commit.hash}`, label: s.label, quote: s.quote ?? null, meta: `${s.commit.kind.replace(/_/g, " ")} · ${s.commit.hash.slice(0, 8)} · ${s.commit.actor}`, tone };
  });
}

/** Plain words for an evidence field and value, when the timeline has no label for that line. */
function evidenceLabel(e: Evidence): string {
  const v = e.value;
  switch (e.field) {
    case "aog.logged_at":
      return typeof v === "string" ? `Tech log, ${zuluDay(v)}` : "Tech log";
    case "aog.mel_relief":
      return v === false ? "No MEL relief: the aircraft is on the ground" : "MEL relief";
    case "aog.ata":
      return `ATA ${String(v).replace(/^(\d{2})(\d{2})$/, "$1-$2")}: the engine-driven pump`;
    case "aog.rts_est":
      return typeof v === "string" ? `Back in service ${zuluDay(v)} at the earliest` : "Return to service";
    case "metar.sknt_at_aog":
      return `${String(v)} kt at Dublin when the fault was logged`;
    case "metar.max_gust_kt_from_16z":
      return `Gusts at most ${String(v)} kt from 16:00Z`;
    case "flight.in_window_dep":
      return v === "out" ? "Departure outside the storm window" : `Departure ${String(v)} the storm window`;
    case "flight.sched_dep":
      return typeof v === "string" ? `Scheduled out ${zulu(v)}` : "Schedule";
    case "spare.long_range_at_dub":
      return v === false ? "No long-range spare at Dublin" : "Spare at Dublin";
    case "flight.ops_cause_code":
      return `OCC coded it ${String(v)}`;
    default:
      return `${e.field} = ${typeof v === "string" ? v : JSON.stringify(v)}`;
  }
}

/**
 * The same chain from the Flight File, for a server without /blame: the drafted euros, the entitlement
 * they come from, the rule that decided the cause, then every piece of evidence as the engine ranked it,
 * with the timeline's own label where it has one. The OCC code that lost is shown struck.
 */
export function chainFromFile(file: FlightFile | undefined, rules: Rule[] | undefined, m: ReturnType<typeof money>): ChainStep[] {
  if (!file) return [];
  const d = file.decision;
  const s = (file.entitlements_summary ?? {}) as Record<string, unknown>;
  const steps: ChainStep[] = [];
  if (m.drafted !== null) steps.push({ key: "je", label: `${eur(m.drafted)} drafted`, quote: m.je?.memo ?? null, meta: m.je ? `${m.je.id} · ${m.je.status === "draft" ? "not yet posted" : m.je.status}${m.je.built_from ? ` · built from ${m.je.built_from} sources` : ""}` : "EU261 compensation liability", tone: "money" });
  if (m.full !== null) {
    const parts = Array.isArray(s.compensation_breakdown) ? (s.compensation_breakdown as { count: number; band_eur: number }[]).map((b) => `${count(b.count)} × €${b.band_eur}`).join(" + ") : null;
    const reduction = (s.reduction_7_2 ?? null) as { rule_ref?: string; support?: string; label?: string } | null;
    steps.push({ key: "ent", label: `${eur(m.full)} full Art. 7 entitlement`, quote: [parts, typeof s.band_label === "string" ? s.band_label : null].filter(Boolean).join(" · ") || null, meta: reduction ? [reduction.rule_ref, reduction.support, reduction.label].filter(Boolean).join(" · ") : "if every passenger claims", tone: "money" });
  }
  for (const ref of d.rules_applied) {
    const [id, version] = ref.split("@");
    const rule = rules?.find((r) => r.id === id && (!version || String(r.version) === version));
    steps.push({ key: ref, label: `${d.cause.replace(/_/g, " ")}, ${d.extraordinary.replace(/_/g, " ")}`.replace(/^./, (c) => c.toUpperCase()), quote: rule?.origin_example ?? null, meta: [ref, ...d.legal_basis].join(" · "), tone: "rule" });
  }
  // The evidence as the engine ranked it: one step per log (its full line), every METAR hour it quoted,
  // context only when it is weather. Spares stay out: they don't bear on a technical fault (plan §1.2).
  const seen = new Set<string>();
  for (const e of d.evidence) {
    const kind = kindOf(e.source_id);
    if (e.role === "context" && kind !== "metar") continue;
    if (kind !== "metar" && seen.has(e.source_id)) continue;
    seen.add(e.source_id);
    const mark = file.timeline.find((t) => t.source_id === e.source_id && t.text === e.quote);
    steps.push({
      key: `${e.fact_id}`,
      label: typeof mark?.label === "string" && kind !== "occ_log" ? mark.label : evidenceLabel(e),
      quote: e.quote ?? null,
      meta: [e.source_id, `tier ${e.trust_tier}`, typeof mark?.at === "string" ? zuluDay(mark.at) : null, e.struck ? "struck" : null].filter(Boolean).join(" · "),
      tone: toneOfSource(e.source_id),
      struck: !!e.struck,
    });
  }
  // one line per source quote: drop repeats of the same quoted line
  return steps.filter((x, i) => !x.quote || steps.findIndex((y) => y.quote === x.quote && y.tone === x.tone) === i);
}
