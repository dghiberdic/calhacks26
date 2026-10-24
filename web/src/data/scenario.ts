// The storm night, as the UI sees it. Numbers follow FINAL_IDEA.md; weather is the real METAR for
// Storm Bram at Dublin. When the engine's API lands, this module becomes the adapter's fallback fixture.
import BRAM_METAR from "./bram-metar.json";

export type Verdict = "weather" | "technical" | "review" | "operated";

export type Flight = {
  id: string;
  dest: string;
  city: string;
  sched: string; // local (Dublin = UTC in winter)
  reg: string;
  type: "A320" | "A321" | "A330";
  pax: number;
  km: number;
  coded: "WX" | "—";
  verdict: Verdict;
  confidence: number;
  note: string;
};

export const AIRLINE = { name: "Northstar Air", code: "NS", hub: "DUB", hubIcao: "EIDW" };

export type MetarReport = { t: string; raw: string; dir: number | null; kt: number | null; gust: number | null };

/** Real EIDW reports for Storm Bram, 9 Dec 2025 (Iowa Environmental Mesonet archive). */
export const METAR: MetarReport[] = (BRAM_METAR as MetarReport[]).map((r) => ({ t: r.t, raw: r.raw, dir: r.dir, kt: r.kt, gust: r.gust }));

const toMinutes = (t: string) => Number(t.slice(0, 2)) * 60 + Number(t.slice(3, 5));
export const metarAt = (t: string) => METAR.reduce((a, b) => (Math.abs(toMinutes(b.t) - toMinutes(t)) < Math.abs(toMinutes(a.t) - toMinutes(t)) ? b : a));

export const STORM = {
  name: "Storm Bram",
  station: "EIDW",
  date: "2025-12-09",
  dateLabel: "9 DEC",
  // From METAR: gusts at or above 40 kt from 13:30Z to 18:30Z (window closes with the 19:00Z report).
  windowStart: "13:30",
  windowEnd: "19:00",
  limitKt: 40,
  peak: { t: "15:30", gust: 50 },
};

/** EU261 Art. 7 compensation tier by great-circle distance. */
export const tier = (km: number) => (km <= 1500 ? 250 : km <= 3500 ? 400 : 600);

const gustNote = (t: string) => {
  const m = metarAt(t);
  return `Gusts ${m.gust ?? m.kt} kt at departure (${m.t}Z METAR)`;
};

const F = (id: string, dest: string, city: string, sched: string, reg: string, type: Flight["type"], pax: number, km: number, confidence: number): Flight => ({
  id, dest, city, sched, reg, type, pax, km, coded: "WX", verdict: "weather", confidence, note: gustNote(sched),
});

export const FLIGHTS: Flight[] = [
  F("NS102", "LHR", "London", "13:35", "EI-NSE", "A320", 168, 449, 96),
  F("NS21", "JFK", "New York", "13:50", "EI-NSK", "A330", 262, 5103, 95),
  F("NS27", "BOS", "Boston", "14:05", "EI-NSB", "A321", 196, 4802, 95),
  F("NS214", "CDG", "Paris", "14:20", "EI-NSF", "A320", 171, 784, 93),
  F("NS25", "EWR", "Newark", "14:40", "EI-NSC", "A321", 188, 5078, 90),
  F("NS41", "ORD", "Chicago", "15:00", "EI-NSL", "A330", 250, 5939, 91),
  F("NS306", "AMS", "Amsterdam", "15:20", "EI-NSG", "A320", 160, 758, 94),
  F("NS51", "IAD", "Washington", "15:45", "EI-NSD", "A321", 190, 5451, 97),
  F("NS55", "PHL", "Philadelphia", "16:10", "EI-NSH", "A321", 184, 5297, 96),
  F("NS23", "JFK", "New York", "16:40", "EI-NSM", "A330", 268, 5103, 96),
  F("NS61", "YYZ", "Toronto", "17:15", "EI-NSJ", "A321", 179, 5257, 94),
  F("NS71", "MCO", "Orlando", "17:50", "EI-NSN", "A330", 246, 6576, 93),
  F("NS81", "SEA", "Seattle", "18:30", "EI-NSP", "A330", 236, 7302, 90),
  { id: "NS31", dest: "BOS", city: "Boston", sched: "21:30", reg: "EI-NSA", type: "A321", pax: 212, km: 4802, coded: "WX", verdict: "technical", confidence: 91, note: "Grounded 07:55, hydraulic leak, before the storm" },
];

export const OPERATED: Pick<Flight, "id" | "dest" | "city" | "sched" | "reg">[] = [
  { id: "NS33", dest: "BOS", city: "Boston", sched: "19:45", reg: "EI-NSB" },
  { id: "NS29", dest: "JFK", city: "New York", sched: "20:10", reg: "EI-NSK" },
  { id: "NS45", dest: "ORD", city: "Chicago", sched: "20:40", reg: "EI-NSL" },
];

export const NS31 = {
  flight: FLIGHTS[FLIGHTS.length - 1],
  techLog: {
    time: "07:55",
    ata: "29-11",
    entry: "HYD G RSVR LO LVL. LEAK FOUND AT ENG 1 EDP CASE DRAIN LINE. A/C U/S PENDING PART.",
    by: "B1 engineer · line station DUB",
  },
  exposure: 212 * 600,
  claimRate: 0.35,
  provision: Math.round(212 * 600 * 0.35),
  marginMin: toMinutes("13:30") - toMinutes("07:55"), // fault logged before the storm window opened
};

/** Hourly max wind and gust at EIDW from the real METAR (kt). */
export const METAR_HOURLY: { h: number; dir: number; kt: number; gust: number }[] = Array.from({ length: 24 }, (_, h) => {
  const inHour = METAR.filter((r) => Number(r.t.slice(0, 2)) === h);
  const kt = Math.max(0, ...inHour.map((r) => r.kt ?? 0));
  const gust = Math.max(kt, ...inHour.map((r) => r.gust ?? 0));
  return { h, dir: inHour[inHour.length - 1]?.dir ?? 0, kt, gust };
});

export const fmtDuration = (min: number) => `${Math.floor(min / 60)} h ${String(min % 60).padStart(2, "0")} min`;

export const metarString = (h: number) => metarAt(`${String(h).padStart(2, "0")}:00`).raw;

export const totals = () => {
  const cancelled = FLIGHTS.length;
  const pax = FLIGHTS.reduce((s, f) => s + f.pax, 0);
  const weather = FLIGHTS.filter((f) => f.verdict === "weather").length;
  return { cancelled, pax, weather, owedFlights: cancelled - weather };
};
