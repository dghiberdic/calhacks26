// The storm night, as the UI sees it. Numbers follow FINAL_IDEA.md; when the engine's API
// lands, this module becomes the adapter's fallback fixture.

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

export const STORM = {
  name: "Storm night",
  station: "EIDW",
  date: "2025-01-24",
  dateLabel: "24 JAN",
  windowStart: "11:00",
  windowEnd: "19:00",
  limitKt: 45, // gust limit used by the cause engine for the storm window
};

/** EU261 Art. 7 compensation tier by great-circle distance. */
export const tier = (km: number) => (km <= 1500 ? 250 : km <= 3500 ? 400 : 600);

export const FLIGHTS: Flight[] = [
  { id: "NS102", dest: "LHR", city: "London", sched: "11:10", reg: "EI-NSE", type: "A320", pax: 168, km: 449, coded: "WX", verdict: "weather", confidence: 97, note: "Departure inside storm window" },
  { id: "NS21", dest: "JFK", city: "New York", sched: "11:25", reg: "EI-NSK", type: "A330", pax: 262, km: 5103, coded: "WX", verdict: "weather", confidence: 96, note: "Gusts 58 kt at departure" },
  { id: "NS27", dest: "BOS", city: "Boston", sched: "11:50", reg: "EI-NSB", type: "A321", pax: 196, km: 4802, coded: "WX", verdict: "weather", confidence: 96, note: "Gusts 61 kt at departure" },
  { id: "NS214", dest: "CDG", city: "Paris", sched: "12:20", reg: "EI-NSF", type: "A320", pax: 171, km: 784, coded: "WX", verdict: "weather", confidence: 97, note: "Departure inside storm window" },
  { id: "NS25", dest: "EWR", city: "Newark", sched: "12:45", reg: "EI-NSC", type: "A321", pax: 188, km: 5078, coded: "WX", verdict: "weather", confidence: 95, note: "Gusts 64 kt at departure" },
  { id: "NS41", dest: "ORD", city: "Chicago", sched: "13:15", reg: "EI-NSL", type: "A330", pax: 250, km: 5939, coded: "WX", verdict: "weather", confidence: 96, note: "Gusts 68 kt at departure" },
  { id: "NS306", dest: "AMS", city: "Amsterdam", sched: "13:40", reg: "EI-NSG", type: "A320", pax: 160, km: 758, coded: "WX", verdict: "weather", confidence: 97, note: "Departure inside storm window" },
  { id: "NS51", dest: "IAD", city: "Washington", sched: "14:30", reg: "EI-NSD", type: "A321", pax: 190, km: 5451, coded: "WX", verdict: "weather", confidence: 95, note: "Gusts 66 kt at departure" },
  { id: "NS55", dest: "PHL", city: "Philadelphia", sched: "15:05", reg: "EI-NSH", type: "A321", pax: 184, km: 5297, coded: "WX", verdict: "weather", confidence: 95, note: "Gusts 62 kt at departure" },
  { id: "NS23", dest: "JFK", city: "New York", sched: "15:40", reg: "EI-NSM", type: "A330", pax: 268, km: 5103, coded: "WX", verdict: "weather", confidence: 94, note: "Gusts 59 kt at departure" },
  { id: "NS61", dest: "YYZ", city: "Toronto", sched: "16:35", reg: "EI-NSJ", type: "A321", pax: 179, km: 5257, coded: "WX", verdict: "weather", confidence: 93, note: "Gusts 55 kt at departure" },
  { id: "NS71", dest: "MCO", city: "Orlando", sched: "17:20", reg: "EI-NSN", type: "A330", pax: 246, km: 6576, coded: "WX", verdict: "weather", confidence: 92, note: "Gusts 52 kt at departure" },
  { id: "NS81", dest: "SEA", city: "Seattle", sched: "18:10", reg: "EI-NSP", type: "A330", pax: 236, km: 7302, coded: "WX", verdict: "weather", confidence: 90, note: "Gusts 49 kt at departure" },
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
  marginHours: 3.08, // fault logged 3h05m before the storm window opened
};

/** Hourly METAR-derived wind at EIDW (kt). Shaped to the story: above limits 11:00–19:00. */
export const METAR_HOURLY: { h: number; dir: number; kt: number; gust: number }[] = [
  { h: 0, dir: 200, kt: 14, gust: 22 }, { h: 1, dir: 200, kt: 15, gust: 24 }, { h: 2, dir: 205, kt: 16, gust: 26 },
  { h: 3, dir: 205, kt: 17, gust: 27 }, { h: 4, dir: 210, kt: 18, gust: 29 }, { h: 5, dir: 210, kt: 19, gust: 30 },
  { h: 6, dir: 215, kt: 21, gust: 32 }, { h: 7, dir: 215, kt: 22, gust: 34 }, { h: 8, dir: 220, kt: 24, gust: 36 },
  { h: 9, dir: 220, kt: 27, gust: 39 }, { h: 10, dir: 225, kt: 30, gust: 43 }, { h: 11, dir: 230, kt: 36, gust: 52 },
  { h: 12, dir: 235, kt: 41, gust: 61 }, { h: 13, dir: 240, kt: 46, gust: 68 }, { h: 14, dir: 240, kt: 44, gust: 66 },
  { h: 15, dir: 245, kt: 42, gust: 62 }, { h: 16, dir: 250, kt: 39, gust: 57 }, { h: 17, dir: 255, kt: 36, gust: 53 },
  { h: 18, dir: 260, kt: 33, gust: 49 }, { h: 19, dir: 265, kt: 28, gust: 41 }, { h: 20, dir: 270, kt: 23, gust: 34 },
  { h: 21, dir: 270, kt: 19, gust: 29 }, { h: 22, dir: 275, kt: 16, gust: 25 }, { h: 23, dir: 280, kt: 14, gust: 23 },
];

export const metarString = (h: number) => {
  const m = METAR_HOURLY[h];
  const hh = String(h).padStart(2, "0");
  const wind = `${String(m.dir).padStart(3, "0")}${String(m.kt).padStart(2, "0")}${m.gust ? `G${m.gust}` : ""}KT`;
  return `EIDW 24${hh}00Z ${wind} 9999 ${m.kt > 30 ? "-RA " : ""}SCT012 BKN020 ${m.kt > 30 ? "10/07 Q0958" : "09/06 Q0971"}`;
};

export const totals = () => {
  const cancelled = FLIGHTS.length;
  const pax = FLIGHTS.reduce((s, f) => s + f.pax, 0);
  const weather = FLIGHTS.filter((f) => f.verdict === "weather").length;
  return { cancelled, pax, weather, owedFlights: cancelled - weather };
};
