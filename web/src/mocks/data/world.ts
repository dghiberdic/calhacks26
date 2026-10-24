// The two real storm days as data: METAR (real), windows (computed from that METAR with the contract's
// definition, never hard-coded), Northstar's flights, the raw sources every quote comes from, and the
// real-world context the plan cites. The engine-like logic that turns this into decisions is in engine.ts.
// Desk-generated days (desk.ts) build the same StormDef shape and register their own sources.
import type { Evidence, MetarObs, Source, StormWindow } from "@/api/types";
import { findAirport } from "./airports";
import { EOWYN_METAR, HERMINIA_METAR } from "./metar";
import { EOWYN_FLIGHTS, EOWYN_ID, HERMINIA_FLIGHTS, HERMINIA_ID, type FlightSpec } from "./flights";
import * as T from "./texts";
import { hhmmZ, nearestObs, stormWindows } from "./util";

export type TechLogRef = {
  source: string;
  text: string;
  logged_at: string;
  ata: string;
  span: string;
  /** One-line reason override (e.g. a rotation from a technical AOG). */
  reason?: string;
  /** The OCC line for this flight when it isn't the storm's batch (e.g. NS30 coded 41). */
  occ?: { source: string; quote: string; at?: string };
};
export type VoucherCase = { coupon_id: string; flight_id: string; departs_eu: boolean; amount_cents: number; source_id: string };
export type KnockOnText = { spares: string; pss: string; hours: number };

export type StormDef = {
  id: string;
  name: string | null;
  station: string;
  date: string;
  metar: MetarObs[];
  windows: StormWindow[];
  flights: FlightSpec[];
  real_context: Record<string, unknown>;
  /** Set for days with no storm window, e.g. "max gust 18 kt · no storm window". */
  message: string | null;
  kind: "eowyn" | "herminia" | "desk";
  /** The OCC batch for the day and its verbatim code spans. */
  occ: { source: string; text: string; span71: string; span72: string };
  /** AMOS tech-log lines behind each technical decision, by flight id. */
  techLogs: Record<string, TechLogRef>;
  /** Spares and PSS lines behind each knock-on return, by flight number. */
  knockOn: Record<string, KnockOnText>;
  /** Unsigned in-lieu voucher cases (the Q1 pattern); Éowyn and Herminia use the defaults in engine.ts. */
  vouchers?: VoucherCase[];
};

export const hubOf = (storm: Pick<StormDef, "station">) => findAirport(storm.station)?.iata ?? "DUB";

export const EOWYN: StormDef = {
  id: EOWYN_ID,
  name: "Storm Éowyn",
  station: "EIDW",
  date: "2025-01-24",
  metar: EOWYN_METAR,
  windows: stormWindows(EOWYN_METAR, "EIDW"),
  flights: EOWYN_FLIGHTS,
  real_context: {
    name: "Storm Éowyn",
    eurocontrol_departures: 179,
    normal_departures: "~292–316",
    reported_cancellations_dep: 119,
    reported_cancellations_arr: 109,
    red_warning: "06:00-11:00",
    orange_warning: "until 16:00",
    metar_source: "IEM asos.py (real)",
  },
  message: null,
  kind: "eowyn",
  occ: { source: `occ_log:${EOWYN_ID}`, text: T.OCC_EOWYN, span71: T.OCC_EOWYN_71, span72: T.OCC_EOWYN_72 },
  techLogs: { "NS31@2025-01-24": { source: "tech_log:EI-NSB@2025-01-23", text: T.TECHLOG_NS31, logged_at: "2025-01-23T21:40:00Z", ata: "2913", span: "EXT LEAK EDP CASE DRAIN PORT, EXCEEDS AMM LIMIT" } },
  knockOn: {
    NS113: { spares: T.SPARES_KNOCK_ON.NS113, pss: T.PSS_KNOCK_ON.NS113, hours: 5.75 },
    NS115: { spares: T.SPARES_KNOCK_ON.NS115, pss: T.PSS_KNOCK_ON.NS115, hours: 5.33 },
    NS117: { spares: T.SPARES_KNOCK_ON.NS117, pss: T.PSS_KNOCK_ON.NS117, hours: 4.33 },
  },
};

export const HERMINIA: StormDef = {
  id: HERMINIA_ID,
  name: "Storm Herminia",
  station: "EIDW",
  date: "2025-01-26",
  metar: HERMINIA_METAR,
  windows: stormWindows(HERMINIA_METAR, "EIDW"),
  flights: HERMINIA_FLIGHTS,
  real_context: { name: "Storm Herminia", metar_source: "IEM asos.py (real)" },
  message: null,
  kind: "herminia",
  occ: { source: `occ_log:${HERMINIA_ID}`, text: T.OCC_HERMINIA, span71: T.OCC_HERMINIA_71, span72: T.OCC_HERMINIA_71 },
  techLogs: {
    "NS112@2025-01-26": { source: "tech_log:EI-NSJ@2025-01-26", text: T.TECHLOG_NS112_HERMINIA, logged_at: "2025-01-26T08:40:00Z", ata: "3611", span: "ENG 1 BLEED DUCT CLAMP FAILED, HOT AIR LEAK PYLON AREA" },
    "NS30@2025-01-25": {
      source: "tech_log:EI-NSN@2025-01-25",
      text: T.TECHLOG_NS30_HERMINIA,
      logged_at: "2025-01-25T22:05:00Z",
      ata: "3242",
      span: "BRK 3 WEAR PIN FLUSH. BRAKE CHANGE REQD.",
      reason: "fault logged at BOS, coded 41",
      occ: { source: "occ_log:NS30@2025-01-25", quote: T.OCC_NS30_HERMINIA, at: "2025-01-25T22:30:00Z" },
    },
  },
  knockOn: {},
};

/** The main window: the longest one (Éowyn also has a minor 23:30–00:30Z window). */
export function mainWindow(storm: Pick<StormDef, "windows">): StormWindow | null {
  return storm.windows.reduce<StormWindow | null>((best, w) => (!best || Date.parse(w.end) - Date.parse(w.start) > Date.parse(best.end) - Date.parse(best.start) ? w : best), null);
}

export const windowLabel = (w: StormWindow | null) => (w ? `${hhmmZ(w.start).replace("Z", "")}–${hhmmZ(w.end)}` : "no window");

// ---------- sources (every Evidence.quote is a substring of one of these) ----------
const S = T.makeSource;
export const SOURCES: Source[] = [
  S("metar:EIDW@2025-01-24", "metar", "EIDW METAR 23 Jan 18:00Z → 24 Jan 23:30Z (IEM)", EOWYN_METAR.map((o) => o.raw).join("\n"), "2025-01-25T05:58:00Z", "https://mesonet.agron.iastate.edu/cgi-bin/request/asos.py?station=EIDW"),
  S("metar:EIDW@2025-01-26", "metar", "EIDW METAR 26 Jan (IEM)", HERMINIA_METAR.map((o) => o.raw).join("\n"), "2025-01-27T05:58:00Z", "https://mesonet.agron.iastate.edu/cgi-bin/request/asos.py?station=EIDW"),
  S("tech_log:EI-NSB@2025-01-23", "tech_log", "AMOS tech log · EI-NSB · 23 Jan 21:40Z", T.TECHLOG_NS31, "2025-01-23T21:41:00Z"),
  S("mcc_log:EI-NSB@2025-01-23", "mcc_log", "MCC log · EI-NSB · 23 Jan 22:15Z", T.MCC_NS31, "2025-01-23T22:15:00Z"),
  S("spares:EIDW@2025-01-24", "spares", "Spares log · DUB · 24 Jan", [T.SPARES_EOWYN, T.SPARES_KNOCK_ON.NS113, T.SPARES_KNOCK_ON.NS115, T.SPARES_KNOCK_ON.NS117].join("\n"), "2025-01-24T05:40:00Z"),
  S("occ_log:EIDW@2025-01-24", "occ_log", "OCC cancel list · 24 Jan 05:12Z", T.OCC_EOWYN, "2025-01-24T05:12:00Z"),
  S("pss:EIDW@2025-01-24", "pss", "PSS reaccommodation · knock-on returns", [T.PSS_KNOCK_ON.NS113, T.PSS_KNOCK_ON.NS115, T.PSS_KNOCK_ON.NS117].join("\n"), "2025-01-24T13:30:00Z"),
  S("crm:NS31@2025-01-24:14C", "crm", "CRM · NS31/14C service-desk voucher", T.CRM_14C, "2025-01-24T14:52:00Z"),
  S("crm:NS31@2025-01-24:bot", "crm", "CRM bot · NS31 refunds 06:02–09:40Z", [T.CRM_BOT_FIRST, T.CRM_BOT_LAST].join("\n"), "2025-01-24T09:40:00Z"),
  S("claim:CLM-2025-0131", "claim", "Claim CLM-2025-0131 · NS31/14C", T.CLAIM_14C, "2025-01-25T01:17:00Z"),
  S("tech_log:EI-NSJ@2025-01-26", "tech_log", "AMOS tech log · EI-NSJ · 26 Jan 08:40Z", T.TECHLOG_NS112_HERMINIA, "2025-01-26T08:41:00Z"),
  S("tech_log:EI-NSN@2025-01-25", "tech_log", "AMOS tech log · EI-NSN · 25 Jan 22:05Z", T.TECHLOG_NS30_HERMINIA, "2025-01-25T22:06:00Z"),
  S("occ_log:EIDW@2025-01-26", "occ_log", "OCC cancel list · 26 Jan 09:55Z", T.OCC_HERMINIA, "2025-01-26T09:55:00Z"),
  S("occ_log:NS30@2025-01-25", "occ_log", "OCC · NS30 25 Jan 22:30Z", T.OCC_NS30_HERMINIA, "2025-01-25T22:30:00Z"),
  S("crm:NS112@2025-01-26:desk", "crm", "CRM · NS112 service-desk vouchers", T.CRM_HERMINIA_DESK, "2025-01-26T14:10:00Z"),
  S("crm:NS30@2025-01-25:desk", "crm", "CRM · NS30 BOS service-desk voucher", T.CRM_HERMINIA_BOS, "2025-01-26T00:40:00Z"),
];

const SOURCE_BY_ID = new Map(SOURCES.map((s) => [s.id, s]));
export const sourceById = (id: string) => SOURCE_BY_ID.get(id);
/** Desk days and injections add their own sources (deterministic texts, so re-registering is harmless). */
export function registerSource(src: Source) {
  SOURCE_BY_ID.set(src.id, src);
  return src;
}

/** One schedule line per flight (tier 2), e.g. "NS31 24JAN DUB 1630 BOS 2345 A321XLR EI-NSB 172". */
export function scheduleLine(spec: FlightSpec): string {
  const f = spec.flight;
  const d = new Date(f.sched_dep);
  const mon = ["JAN", "FEB", "MAR", "APR", "MAY", "JUN", "JUL", "AUG", "SEP", "OCT", "NOV", "DEC"][d.getUTCMonth()];
  const hhmm = (iso: string) => iso.slice(11, 16).replace(":", "");
  return `${f.number} ${String(d.getUTCDate()).padStart(2, "0")}${mon} ${f.origin} ${hhmm(f.sched_dep)} ${f.dest} ${hhmm(f.sched_arr)} ${spec.type} ${f.aircraft} ${f.pax}`;
}

// ---------- evidence helpers ----------
export function ev(source_id: string, field: string, value: unknown, quote: string | null, role: Evidence["role"], struck = false, subject?: string): Evidence {
  const src = sourceById(source_id);
  const tier = src?.trust_tier ?? (source_id.startsWith("schedule:") ? 2 : 3);
  if (quote && src?.text && !src.text.includes(quote)) throw new Error(`mock quote not in source ${source_id}: ${quote}`);
  return { fact_id: `F:${subject ?? source_id}:${field}`, source_id, field, value, quote, role, trust_tier: tier, struck };
}

/** METAR evidence for time `t` at the storm's station: the nearest observation, quoted raw. */
export function metarEv(storm: StormDef, t: string, field: string, value: unknown, role: Evidence["role"] = "supports"): Evidence {
  const o = nearestObs(storm.metar, t);
  return { ...ev(`metar:${storm.id}`, field, value, o.raw, role, false, `${storm.station}@${o.valid.slice(0, 16)}Z`), trust_tier: 1 };
}

export function scheduleEv(spec: FlightSpec, role: Evidence["role"] = "context"): Evidence {
  const f = spec.flight;
  return { fact_id: `F:flight:${f.id}:flight.sched_dep`, source_id: `schedule:${f.id}`, field: "flight.sched_dep", value: f.sched_dep, quote: scheduleLine(spec), role, trust_tier: 2, struck: false };
}
