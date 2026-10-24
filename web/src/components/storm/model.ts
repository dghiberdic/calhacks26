import type { FlightRow, MetarObs, StormRun, StormWindow } from "@/api/types";
import { iataOf } from "@/lib/airports";
import { verdictOf, type VerdictKind } from "../verdict";

/** A flight placed on the hub's timeline: departures at STD, arrivals at STA (windows apply at both ends). */
export type Tick = {
  row: FlightRow;
  id: string;
  number: string;
  at: Date;
  lane: "dep" | "arr";
  verdict: VerdictKind;
  code: string | null;
  recoded: boolean;
  recodeLabel: string | null;
};

export type StormFacts = {
  hub: string;
  domain: [Date, Date];
  windows: { start: Date; end: Date; raw: StormWindow }[];
  gustLimitKt: number | null;
  ticks: Tick[];
  techLog: { at: Date; label: string; flightId: string }[];
  byVerdict: Record<VerdictKind, number>;
};

const MONTHS = ["JAN", "FEB", "MAR", "APR", "MAY", "JUN", "JUL", "AUG", "SEP", "OCT", "NOV", "DEC"];

/** "23JAN 21:40Z" → Date (year from the storm date). */
function parseAmosTime(text: string, year: number): Date | null {
  const m = text.match(/\b(\d{1,2})(JAN|FEB|MAR|APR|MAY|JUN|JUL|AUG|SEP|OCT|NOV|DEC)\s+(\d{2}):?(\d{2})Z/);
  if (!m) return null;
  return new Date(Date.UTC(year, MONTHS.indexOf(m[2]), Number(m[1]), Number(m[3]), Number(m[4])));
}

function isoDate(v: unknown): Date | null {
  if (typeof v !== "string" || !/^\d{4}-\d{2}-\d{2}T/.test(v)) return null;
  const d = new Date(v);
  return Number.isNaN(d.getTime()) ? null : d;
}

/** The definition string carries the threshold ("gust>=35kt or …"); read it rather than hard-coding it. */
export function gustThreshold(windows: StormWindow[]): number | null {
  const def = windows.find((w) => w.definition)?.definition ?? "";
  const m = def.match(/gust\s*>=?\s*(\d+)\s*kt/i);
  return m ? Number(m[1]) : null;
}

export function stormFacts(run: StormRun): StormFacts {
  const hub = iataOf(run.station);
  const [y, mo, d] = run.date.split("-").map(Number);
  const dayStart = Date.UTC(y, mo - 1, d);
  // Plan §3: the axis runs from 18:00 the day before to 24:00 UTC.
  const domain: [Date, Date] = [new Date(dayStart - 6 * 3600_000), new Date(dayStart + 24 * 3600_000)];

  const ticks: Tick[] = run.flights.map((row) => {
    const f = row.flight;
    const lane: Tick["lane"] = f.origin === hub ? "dep" : "arr";
    const at = new Date(lane === "dep" ? f.sched_dep : f.sched_arr);
    return {
      row,
      id: f.id,
      number: f.number,
      at,
      lane,
      verdict: verdictOf(row),
      code: row.decision?.ops_cause_code ?? f.ops_cause_code ?? null,
      recoded: !!row.decision?.recoded,
      recodeLabel: row.decision?.recode_label ?? null,
    };
  });

  const techLog: StormFacts["techLog"] = [];
  for (const row of run.flights) {
    for (const e of row.decision?.evidence ?? []) {
      if (!/tech_log/i.test(e.source_id)) continue;
      const at = isoDate(e.value) ?? (e.quote ? parseAmosTime(e.quote, y) : null);
      if (at && !techLog.some((t) => t.at.getTime() === at.getTime())) techLog.push({ at, label: `tech log ${row.flight.number}`, flightId: row.flight.id });
    }
  }

  const byVerdict = { weather: 0, notweather: 0, held: 0, operated: 0, pending: 0 } as Record<VerdictKind, number>;
  for (const t of ticks) byVerdict[t.verdict] += 1;

  return {
    hub,
    domain,
    windows: run.windows.map((w) => ({ start: new Date(w.start), end: new Date(w.end), raw: w })),
    gustLimitKt: gustThreshold(run.windows),
    ticks,
    techLog,
    byVerdict,
  };
}

/** METAR rows with a time, sorted, for the curves and the hover tooltip. */
export function metarSeries(metar: MetarObs[]) {
  return metar
    .map((o) => ({ at: new Date(o.valid), gust: o.gust ?? null, sknt: o.sknt ?? null, raw: o.raw, obs: o }))
    .filter((o) => !Number.isNaN(o.at.getTime()))
    .sort((a, b) => a.at.getTime() - b.at.getTime());
}

/** The window the story is about: the longest one the engine found (Éowyn also has a short one at 23:30Z). */
export function mainWindowOf<W extends { start: string; end: string }>(windows: W[]): W | null {
  return windows.reduce<W | null>((best, w) => (!best || Date.parse(w.end) - Date.parse(w.start) > Date.parse(best.end) - Date.parse(best.start) ? w : best), null);
}
