// Judge's Desk days (WorldAPI.generate_day, in mock form): Northstar flights between DUB and the chosen
// airport, both directions, decided against that airport's METAR. The browser can't reach IEM, so the
// METAR is generated deterministically per (airport, date) and every line carries "RMK MOCK" so nobody
// mistakes it for a real observation. Like the real generator it always plants, when the day allows:
// 1 OCC weather code contradicted by METAR (an AOG before the window), 3 unsigned in-lieu vouchers on
// an EU departure and 1 on a non-EU departure.
import type { Airport, Flight, MetarObs } from "@/api/types";
import { AIRPORTS, distanceKm, findAirport } from "./airports";
import type { FlightSpec, Group } from "./flights";
import { makeSource } from "./texts";
import { isoZ, position, seeded, stormWindows } from "./util";
import { mainWindow, registerSource, windowLabel, type KnockOnText, type StormDef, type TechLogRef, type VoucherCase } from "./world";

/** Station-days that were stormy in reality (named storms of 2023–25), so a judge's likely picks show a window. */
const KNOWN_STORMS: Record<string, { center: number; hours: number; peak: number; name?: string }> = {
  "EIDW@2024-01-21": { center: 15, hours: 7, peak: 58, name: "Storm Isha" },
  "EIDW@2023-11-02": { center: 6, hours: 5, peak: 47, name: "Storm Ciarán" },
  "EIDW@2023-11-12": { center: 4, hours: 4, peak: 44, name: "Storm Debi" },
  "EIDW@2024-01-23": { center: 14, hours: 6, peak: 52, name: "Storm Jocelyn" },
  "EIDW@2024-12-07": { center: 9, hours: 8, peak: 55, name: "Storm Darragh" },
  "EGLL@2024-01-21": { center: 17, hours: 5, peak: 48, name: "Storm Isha" },
  "EGLL@2023-11-02": { center: 8, hours: 6, peak: 50, name: "Storm Ciarán" },
  "EGCC@2024-01-21": { center: 18, hours: 6, peak: 54, name: "Storm Isha" },
  "EGPH@2024-01-21": { center: 19, hours: 6, peak: 56, name: "Storm Isha" },
  "EHAM@2023-11-02": { center: 10, hours: 6, peak: 52, name: "Storm Ciarán" },
  "LFPG@2023-11-02": { center: 5, hours: 5, peak: 49, name: "Storm Ciarán" },
  "KBOS@2023-12-18": { center: 15, hours: 10, peak: 55 },
  "KJFK@2023-12-18": { center: 15, hours: 8, peak: 45 },
};

const MON = ["JAN", "FEB", "MAR", "APR", "MAY", "JUN", "JUL", "AUG", "SEP", "OCT", "NOV", "DEC"];

function localDate(iso: string, tz: string) {
  try {
    return new Intl.DateTimeFormat("en-CA", { timeZone: tz, year: "numeric", month: "2-digit", day: "2-digit" }).format(new Date(iso));
  } catch {
    return iso.slice(0, 10);
  }
}

/** 48 half-hourly obs for the UTC day; a storm bump (gusts ≥36 kt) on stormy days, light winds otherwise. */
export function syntheticMetar(ap: Airport, date: string, stormy: { center: number; hours: number; peak: number } | null): MetarObs[] {
  const rnd = seeded(`metar:${ap.icao}@${date}`);
  const us = ap.icao.startsWith("K") || ap.icao.startsWith("C");
  const calmMax = 14 + Math.floor(rnd() * 9);
  const baseDir = 180 + Math.floor(rnd() * 9) * 10;
  const temp = Math.round(2 + rnd() * 10);
  const obs: MetarObs[] = [];
  for (let i = 0; i < 48; i++) {
    const h = i / 2;
    const valid = `${date}T${String(Math.floor(h)).padStart(2, "0")}:${i % 2 ? "30" : "00"}:00Z`;
    let sknt = Math.round(5 + rnd() * 9);
    let gust: number | null = rnd() < 0.25 ? Math.min(calmMax, sknt + 6 + Math.round(rnd() * 6)) : null;
    let wx: string | null = null;
    let vis = us ? "10SM" : "9999";
    let vsby = 6.21;
    if (stormy) {
      const dist = Math.abs(h - stormy.center);
      const half = stormy.hours / 2;
      if (dist <= half) {
        gust = Math.round(stormy.peak - (dist / half) * (stormy.peak - 36));
        sknt = Math.min(34, Math.round(gust * 0.55));
        wx = dist < half / 2 ? "RA" : "-RA";
        vis = us ? "3SM" : "6000";
        vsby = 3.73;
      } else if (dist <= half + 1.5) {
        gust = 26 + Math.round(rnd() * 6);
        sknt = Math.round(14 + rnd() * 6);
        wx = "-RA";
      }
    }
    if (!stormy && gust !== null) gust = Math.min(gust, calmMax);
    if (gust !== null && gust <= sknt) gust = null;
    if (!stormy && i === 27) gust = calmMax; // the day's max gust, quoted in the "no storm window" message
    const dir = String(Math.round((baseDir + (rnd() - 0.5) * 60) / 10) * 10).padStart(3, "0");
    const dd = date.slice(8, 10);
    const hhmm = valid.slice(11, 16).replace(":", "");
    const wind = `${dir}${String(sknt).padStart(2, "0")}${gust ? `G${gust}` : ""}KT`;
    const press = us ? `A${2950 + Math.round(rnd() * 60)}` : `Q${String(980 + Math.round(rnd() * 30)).padStart(4, "0")}`;
    const raw = `${ap.icao} ${dd}${hhmm}Z ${wind} ${vis} ${wx ? `${wx} ` : ""}${wx ? "BKN012" : "FEW030"} ${String(temp).padStart(2, "0")}/${String(Math.max(0, temp - 3)).padStart(2, "0")} ${press} RMK MOCK`;
    obs.push({ station: ap.icao, valid, sknt, gust, drct: Number(dir), vsby_sm: vsby, wxcodes: wx, raw });
  }
  return obs;
}

type Leg = { number: string; origin: string; dest: string; dep: string; arr: string; pax: number; tail: string; type: string };

/** Northstar's rotations for the day: 3 short/medium-haul rotations, or 1 long-haul rotation, DUB ↔ X. */
function legsFor(hub: Airport, date: string): Leg[] {
  const rnd = seeded(`legs:${hub.icao}@${date}`);
  const idx = Math.max(0, AIRPORTS.findIndex((a) => a.icao === hub.icao));
  const at = (min: number) => isoZ(Date.parse(`${date}T00:00:00Z`) + min * 60_000);
  const legs: Leg[] = [];
  if (hub.icao === "EIDW") {
    const dests = [
      { iata: "LHR", dep: 7 * 60 },
      { iata: "AMS", dep: 9 * 60 + 30 },
      { iata: "CDG", dep: 12 * 60 + 10 },
      { iata: "BOS", dep: 16 * 60 + 30 },
    ];
    dests.forEach((d, i) => {
      const km = distanceKm("DUB", d.iata);
      const block = Math.round((km / 13.3 + 30) / 5) * 5;
      const long = km > 3500;
      const n = 600 + i * 2;
      const tail = `EI-NV${"ABCDEFGH"[i]}`;
      const pax = long ? 160 + Math.round(rnd() * 20) : 150 + Math.round(rnd() * 36);
      const backDep = d.dep + block + (long ? 120 : 45);
      legs.push({ number: `NS${n}`, origin: "DUB", dest: d.iata, dep: at(d.dep), arr: at(d.dep + block), pax, tail, type: long ? "A321XLR" : "A320neo" });
      legs.push({ number: `NS${n + 1}`, origin: d.iata, dest: "DUB", dep: at(backDep), arr: at(backDep + block), pax: pax - 4, tail, type: long ? "A321XLR" : "A320neo" });
    });
    return legs;
  }
  const km = distanceKm("DUB", hub.iata);
  const long = km > 3500;
  const block = Math.round((km / 13.3 + 30) / 5) * 5;
  const base = 500 + idx * 6;
  const outs = long ? [11 * 60 + 5, 16 * 60 + 30] : [6 * 60 + 30, 11 * 60 + 40, 17 * 60 + 10];
  outs.forEach((dep, i) => {
    const tail = `EI-N${"PQRSTUVWXYZ"[idx % 11]}${"ABC"[i]}`;
    const type = long ? "A330-300" : "A320neo";
    const pax = long ? 228 + Math.round(rnd() * 40) : 150 + Math.round(rnd() * 36);
    const backDep = dep + block + (long ? 120 : 45);
    legs.push({ number: `NS${base + i * 2}`, origin: "DUB", dest: hub.iata, dep: at(dep), arr: at(dep + block), pax, tail, type });
    legs.push({ number: `NS${base + i * 2 + 1}`, origin: hub.iata, dest: "DUB", dep: at(backDep), arr: at(backDep + block), pax: pax - 3 - Math.round(rnd() * 6), tail, type });
  });
  return legs;
}

export type DeskDay = StormDef;

export function generateDay(icao: string, date: string): DeskDay {
  const hub = findAirport(icao);
  if (!hub) throw new Error("unknown airport");
  const id = `${hub.icao}@${date}`;
  const known = KNOWN_STORMS[id];
  const rnd = seeded(`day:${id}`);
  const stormy = known ?? (rnd() < 0.4 ? { center: 8 + rnd() * 7, hours: 3 + rnd() * 4, peak: 40 + Math.round(rnd() * 18) } : null);
  const metar = syntheticMetar(hub, date, stormy);
  const windows = stormWindows(metar, hub.icao);
  const w = mainWindow({ windows });
  const hubIata = hub.iata;
  const legs = legsFor(hub, date);
  const pos = (iata: string, t: string) => (iata === hubIata ? position(metar, windows, t).pos : "out");
  const occAt = w ? isoZ(Date.parse(w.start) - 90 * 60_000) : `${date}T05:00:00Z`;
  const ddmon = `${date.slice(8, 10)}${MON[Number(date.slice(5, 7)) - 1]}`;

  // Decide which legs were cancelled, and why (the engine re-derives the cause from the facts).
  const group = new Map<string, Group>();
  const code = new Map<string, string>();
  for (const l of legs) {
    if (pos(l.origin, l.dep) === "in") {
      group.set(l.number, "outbound_weather"); // the departure end decides
      code.set(l.number, "71");
    } else if (pos(l.dest, l.arr) === "in") {
      group.set(l.number, "return_weather"); // the arrival end decides
      code.set(l.number, l.origin === "DUB" ? "72" : "71");
    }
  }
  // A return whose outbound was cancelled has no aircraft: knock-on, if calm at both ends.
  for (let i = 0; i + 1 < legs.length; i += 2) {
    const [outLeg, back] = [legs[i], legs[i + 1]];
    if (group.has(outLeg.number) && !group.has(back.number)) {
      group.set(back.number, "knock_on");
      code.set(back.number, "71");
    }
  }
  // Plant the miscode: the last outbound that is out of window at both ends, coded 71 by OCC, with an AOG logged before the window.
  const techLogs: Record<string, TechLogRef> = {};
  const vouchers: VoucherCase[] = [];
  const knockOn: Record<string, KnockOnText> = {};
  let miscode: Leg | null = null;
  if (w) {
    for (let i = legs.length - 2; i >= 0; i -= 2) {
      const l = legs[i];
      if (l.origin === "DUB" && !group.has(l.number)) {
        miscode = l;
        break;
      }
    }
  }
  const sources: { id: string; kind: Parameters<typeof makeSource>[1]; title: string; text: string; at: string }[] = [];
  if (miscode && w) {
    const back = legs[legs.indexOf(miscode) + 1];
    const loggedAt = isoZ(Math.min(Date.parse(w.start) - 150 * 60_000, Date.parse(miscode.dep) - 300 * 60_000));
    const logText = `${loggedAt.slice(8, 10)}${MON[Number(loggedAt.slice(5, 7)) - 1]} ${loggedAt.slice(11, 16)}Z ${miscode.tail} DUB. ENG 1 OIL PRESS LO ON GND RUN. OIL PUMP RPLCMT REQD. NO MEL RELIEF. A/C AOG.`;
    const logSource = `tech_log:${miscode.tail}@${loggedAt.slice(0, 10)}`;
    sources.push({ id: logSource, kind: "tech_log", title: `AMOS tech log · ${miscode.tail} · ${loggedAt.slice(11, 16)}Z`, text: logText, at: loggedAt });
    group.set(miscode.number, "technical");
    code.set(miscode.number, "71");
    techLogs[`${miscode.number}@${localDate(miscode.dep, "Europe/Dublin")}`] = { source: logSource, text: logText, logged_at: loggedAt, ata: "7930", span: "ENG 1 OIL PRESS LO ON GND RUN. OIL PUMP RPLCMT REQD." };
    if (back && !group.has(back.number)) {
      group.set(back.number, "technical");
      code.set(back.number, "93");
      const occLine = `${ddmon} OCC: ${back.number} ${back.origin}-${back.dest} CNL RSN 93 (${miscode.tail} AOG DUB).`;
      const occSource = `occ_log:${back.number}@${date}`;
      sources.push({ id: occSource, kind: "occ_log", title: `OCC · ${back.number}`, text: occLine, at: occAt });
      techLogs[`${back.number}@${localDate(back.dep, (findAirport(back.origin) ?? hub).tz)}`] = { source: logSource, text: logText, logged_at: loggedAt, ata: "7930", span: "ENG 1 OIL PRESS LO ON GND RUN. OIL PUMP RPLCMT REQD.", reason: `rotation: ${miscode.tail} AOG at DUB (technical), coded 93`, occ: { source: occSource, quote: occLine, at: occAt } };
    }
  }

  // Flights
  const specs: FlightSpec[] = legs.map((l, i) => {
    const g = group.get(l.number) ?? "operated";
    const tz = (findAirport(l.origin) ?? hub).tz;
    const d = localDate(l.dep, tz);
    const delay = Math.round(rnd() * 14) + 4;
    const flight: Flight = {
      id: `${l.number}@${d}`,
      number: l.number,
      date: d,
      origin: l.origin,
      dest: l.dest,
      sched_dep: l.dep,
      sched_arr: l.arr,
      aircraft: l.tail,
      status: g === "operated" ? "operated" : "cancelled",
      actual_dep: g === "operated" ? isoZ(Date.parse(l.dep) + delay * 60_000) : null,
      actual_arr: g === "operated" ? isoZ(Date.parse(l.arr) + delay * 60_000) : null,
      pax: l.pax,
      ops_cause_code: g === "operated" ? null : (code.get(l.number) ?? "71"),
      outbound_pair_id: i % 2 === 1 ? `${legs[i - 1].number}@${localDate(legs[i - 1].dep, "Europe/Dublin")}` : null,
      inbound_flight_id: i % 2 === 1 ? `${legs[i - 1].number}@${localDate(legs[i - 1].dep, "Europe/Dublin")}` : null,
      notified_at: g === "operated" ? null : occAt,
      operating_carrier_eu: true,
    };
    return { flight, group: g, type: l.type };
  });

  // OCC batch for the day: every cancellation coded weather, pairs as "NS504/505" (the real OCC's habit).
  const cancelled = specs.filter((s) => s.flight.status === "cancelled" && s.flight.ops_cause_code !== "93");
  const pairs: string[] = [];
  for (const s of cancelled) {
    const n = Number(s.flight.number.slice(2));
    if (n % 2 === 0 && cancelled.some((x) => x.flight.number === `NS${n + 1}`)) pairs.push(`NS${n}/${n + 1}`);
    else if (n % 2 === 1 && cancelled.some((x) => x.flight.number === `NS${n - 1}`)) continue;
    else pairs.push(s.flight.number);
  }
  const occText = `${occAt.slice(11, 16)}Z OCC DM: ${hubIata} WX CNL LIST → NETLINE, RSN 71. ${pairs.join(" ")}. ASM SENT.`;
  const occSource = `occ_log:${id}`;
  sources.push({ id: occSource, kind: "occ_log", title: `OCC cancel list · ${hubIata} · ${occAt.slice(11, 16)}Z`, text: occText, at: occAt });
  // Knock-on texts: no spare within 3 h, earliest reroute offered.
  const sparesLines: string[] = [];
  const pssLines: string[] = [];
  for (const s of specs.filter((x) => x.group === "knock_on")) {
    const spareDep = isoZ(Date.parse(s.flight.sched_dep) + 250 * 60_000);
    const spares = `No tail at ${s.flight.origin}. Earliest ferry ex-DUB → ${s.flight.origin} dep ${spareDep.slice(11, 16)}Z = STD+4h10.`;
    const pss = `${s.flight.number} ${ddmon} ${s.flight.origin}-${s.flight.dest} CNL · ${s.flight.pax} PAX · REROUTE OFFERED: EARLIEST AVAILABLE, ANY CARRIER`;
    knockOn[s.flight.number] = { spares, pss, hours: 4.17 };
    sparesLines.push(spares);
    pssLines.push(pss);
  }
  if (sparesLines.length) {
    sources.push({ id: `spares:${id}`, kind: "spares", title: `Spares log · ${hubIata}`, text: sparesLines.join("\n"), at: occAt });
    sources.push({ id: `pss:${id}`, kind: "pss", title: "PSS reaccommodation · knock-on returns", text: pssLines.join("\n"), at: occAt });
  }
  // Vouchers on the miscoded outbound (EU departure) and on its return when that leaves a non-EU airport.
  if (miscode) {
    const out = specs.find((s) => s.flight.number === miscode.number);
    const back = specs.find((s) => s.flight.number === `NS${Number(miscode.number.slice(2)) + 1}`);
    const crmSource = `crm:${id}:desk`;
    const lines: string[] = [];
    if (out) {
      for (const seat of ["7C", "12A", "18F"]) vouchers.push({ coupon_id: `${out.flight.id}:${seat}`, flight_id: out.flight.id, departs_eu: true, amount_cents: 30_000, source_id: crmSource });
      lines.push(`${ddmon} DUB SVC DESK · 3 VOUCHERS EUR 300.00 ISSUED IN LIEU OF COMPENSATION · ${out.flight.number}/${ddmon} · STATUS ACCEPTED · SIGNATURE: NONE CAPTURED`);
    }
    const backAp = back ? findAirport(back.flight.origin) : undefined;
    if (back && backAp && !backAp.eu && back.group === "technical") {
      vouchers.push({ coupon_id: `${back.flight.id}:9D`, flight_id: back.flight.id, departs_eu: false, amount_cents: 30_000, source_id: crmSource });
      lines.push(`${ddmon} ${back.flight.origin} SVC DESK · VOUCHER EUR 300.00 ISSUED IN LIEU OF COMPENSATION · ${back.flight.number}/${ddmon} · STATUS ACCEPTED · SIGNATURE: NONE CAPTURED`);
    }
    if (lines.length) sources.push({ id: crmSource, kind: "crm", title: `CRM · ${hubIata} service-desk vouchers`, text: lines.join("\n"), at: occAt });
  }
  sources.push({ id: `metar:${id}`, kind: "metar", title: `${hub.icao} METAR ${date} (synthetic, mock mode)`, text: metar.map((o) => o.raw).join("\n"), at: `${date}T23:59:00Z` });
  for (const src of sources) registerSource(makeSource(src.id, src.kind, src.title, src.text, src.at));

  const maxGust = Math.max(...metar.map((o) => o.gust ?? o.sknt ?? 0));
  return {
    id,
    name: known?.name ?? null,
    station: hub.icao,
    date,
    metar,
    windows,
    flights: specs,
    real_context: { name: known?.name ?? null, metar_source: "synthetic (mock mode, no network)", occ_at: occAt, window: windowLabel(w) },
    message: windows.length ? null : `max gust ${maxGust} kt · no storm window`,
    kind: "desk",
    occ: { source: occSource, text: occText, span71: `${hubIata} WX CNL LIST → NETLINE, RSN 71`, span72: `${hubIata} WX CNL LIST → NETLINE, RSN 71` },
    techLogs,
    knockOn,
    vouchers,
  };
}
