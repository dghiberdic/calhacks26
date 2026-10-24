import type { FlightFile, StormWindow, TimelineMark } from "@/api/types";
import { electionsOf, summaryText } from "./lib";

/**
 * The airline's answer to a compensation claim on a weather cancellation, assembled from the file's own
 * evidence: Art. 5(3) needs the named circumstance, the causal link for *this* flight, and what was known
 * when the decision was taken. Display only: verdicts and euros don't change, and a person approves any reply.
 */
export type WeatherDefence = {
  /** The end of the flight that sat inside the storm, and its scheduled time there. */
  end: "dep" | "arr";
  at: string;
  station: string;
  /** The computed storm window around that time, when the hub's run has it. */
  window: StormWindow | null;
  /** Minutes from the scheduled time to the window's close: the "why not wait?" a claimant will ask. */
  minutesToClose: number | null;
  /** The tier-1 METAR line for that time, verbatim. */
  metar: string | null;
  /** What OCC knew before deciding: warnings received, then the batch cancel list. */
  known: TimelineMark[];
  occ: TimelineMark | null;
  /** Real context the claimant can also find: warnings, and how many departures the airport still ran. */
  warnings: string[];
  departures: string | null;
  /** What the passengers chose, and what is still owed regardless. */
  elections: [string, number][];
  stillOwed: string | null;
};

const WARNING = /warning|status red|status orange|met [eé]ireann/i;
const text = (m: TimelineMark) => `${m.label ?? ""} ${m.text ?? ""}`;

export function weatherDefence(file: FlightFile, hub: string, windows: StormWindow[] | undefined, realContext: Record<string, unknown> | undefined): WeatherDefence | null {
  const d = file.decision;
  if (d.cause !== "weather" || d.extraordinary !== "extraordinary") return null;
  const end = d.in_window_dep === "in" ? "dep" : d.in_window_arr === "in" ? "arr" : null;
  if (!end) return null;

  const at = end === "dep" ? file.flight.sched_dep : file.flight.sched_arr;
  const station = end === "dep" ? file.flight.origin : file.flight.dest;
  const t = Date.parse(at);
  // The run's windows are the hub's; an outstation's weather stands on its own METAR line.
  const window = station === hub ? ((windows ?? []).find((w) => Date.parse(w.start) <= t && t <= Date.parse(w.end)) ?? null) : null;
  const minutesToClose = window ? Math.round((Date.parse(window.end) - t) / 60_000) : null;

  const isMetar = (field: string, sourceId: string) => field.startsWith("metar.") || /metar/i.test(sourceId);
  const metar = d.evidence.find((e) => e.trust_tier === 1 && e.role === "supports" && isMetar(e.field, e.source_id))?.quote ?? null;
  const marks = [...(file.timeline ?? [])].filter((m) => m.at).sort((a, b) => Date.parse(a.at!) - Date.parse(b.at!));
  const occ = marks.find((m) => m.kind === "occ") ?? null;
  const decidedAt = Date.parse(occ?.at ?? d.known_at);
  const known = marks.filter((m) => m !== occ && Date.parse(m.at!) <= decidedAt && (m.kind === "warning" || WARNING.test(text(m))));

  const rc = realContext ?? {};
  const warnings = [
    rc.red_warning ? `Red ${String(rc.red_warning).replace("-", "–")}` : null,
    rc.orange_warning ? `Orange ${String(rc.orange_warning)}` : null,
  ].filter((w): w is string => !!w);
  const departures =
    rc.eurocontrol_departures !== undefined
      ? `${Number(rc.eurocontrol_departures).toLocaleString("en-US")} departures (Eurocontrol)${rc.normal_departures ? ` against ${String(rc.normal_departures)} on a normal day` : ""}`
      : null;

  return {
    end,
    at,
    station,
    window,
    minutesToClose,
    metar,
    known,
    occ,
    warnings,
    departures,
    elections: electionsOf(file.entitlements_summary),
    stillOwed: summaryText(file.entitlements_summary, "headline"),
  };
}
