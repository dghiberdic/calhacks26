// Self-test for src/lib/metar.ts: edge-case asserts, then re-decode the stored Storm Bram day and
// print it with its storm windows.   npx tsx scripts/metar-selftest.ts [path/to/metar-<date>.json]
import { readFileSync } from "node:fs";
import { join } from "node:path";
import { deepStrictEqual as eq } from "node:assert/strict";
import { parseMetar, stormWindow } from "../src/lib/metar";

const pick = (raw: string) => {
  const m = parseMetar(raw);
  return { dir: m.dir, kt: m.kt, gust: m.gust, vis: m.vis, wx: m.wx, qnh: m.qnh };
};

// ── edge cases ──
eq(pick("EIDW 091530Z 22028G50KT 190V250 9999 FEW015 BKN020 14/10 Q0977 NOSIG"), { dir: 220, kt: 28, gust: 50, vis: 9999, wx: [], qnh: 977 });
eq(pick("COR EIDW 091830Z 25021G40KT 9999 FEW014 SCT025 10/05 Q0987 NOSIG"), { dir: 250, kt: 21, gust: 40, vis: 9999, wx: [], qnh: 987 });
eq(parseMetar("COR EIDW 091830Z 25021G40KT 9999 FEW014 SCT025 10/05 Q0987 NOSIG").cor, true);
eq(pick("EGLL 091020Z VRB03KT CAVOK 08/04 Q1021="), { dir: null, kt: 3, gust: null, vis: 9999, wx: [], qnh: 1021 });
eq(pick("METAR UUEE 091030Z 27008MPS 0800 R24L/1200U +SHSN VCTS BKN010CB M02/M03 Q0998 RESHSN"), { dir: 270, kt: 16, gust: null, vis: 800, wx: ["+SHSN", "VCTS"], qnh: 998 });
eq(pick("KBOS 091954Z 31015G28KT 1 1/2SM -RA BR OVC008 03/02 A2992 RMK AO2 PK WND 31032/1932"), { dir: 310, kt: 15, gust: 28, vis: 2414, wx: ["-RA", "BR"], qnh: 1013.2 });
eq(pick("EIDW 090100Z 14012G23KT 110V180 9000 -RA SCT003 BKN006 11/10 Q0994 TEMPO 22045G60KT +TSRA"), { dir: 140, kt: 12, gust: 23, vis: 9000, wx: ["-RA"], qnh: 994 }); // TREND ignored
const ws = parseMetar("EIDW 091730Z 24022G41KT 210V270 9999 FEW014 SCT022 BKN032 11/06 Q0985 WS R28L NOSIG");
eq([ws.windshear, ws.varDir, ws.trend, ws.temp, ws.dew, ws.t, ws.day], [["R28L"], [210, 270], "NOSIG", 11, 6, "17:30", 9]);
eq(stormWindow([{ t: "23:00", gust: 45 }, { t: "23:30", gust: 30 }, { t: "00:00", gust: 48 }, { t: "00:30", gust: 20 }]).map((w) => [w.start, w.end, w.durationMin, w.peakGust]), [["23:00", "00:30", 90, 48]]); // midnight + lull < 60 merges
eq(stormWindow([{ t: "10:00", gust: 41 }, { t: "10:30", gust: 44 }])[0].ongoing, true);

// ── the stored day ──
const file = process.argv[2] ?? join(process.cwd(), "public/data/bram/metar-2025-12-09.json");
type Row = { t: string; raw: string; dir: number | null; kt: number | null; gust: number | null; vis: number | null; wx: string[]; qnh: number | null };
const day: Row[] = JSON.parse(readFileSync(file, "utf8"));
for (const r of day) eq({ t: r.t, ...pick(r.raw) }, { t: r.t, dir: r.dir, kt: r.kt, gust: r.gust, vis: r.vis, wx: r.wx, qnh: r.qnh }, `JSON out of sync with parser at ${r.t}`);

const pad = (v: unknown, n: number) => String(v ?? "–").padStart(n);
console.log(`${file}\n  time  dir  kt gust   vis  qnh  wx`);
for (const r of day) console.log(`  ${r.t} ${pad(r.dir ?? (r.raw.includes("VRB") ? "VRB" : null), 4)} ${pad(r.kt, 3)} ${pad(r.gust, 4)} ${pad(r.vis, 5)} ${pad(r.qnh, 4)}  ${r.wx.join(" ")}`);
const peak = day.reduce((a, b) => ((b.gust ?? 0) > (a.gust ?? 0) ? b : a));
console.log(`\npeak gust ${peak.gust} kt at ${peak.t} UTC (${peak.raw})`);
for (const limit of [40, 45]) {
  console.log(`storm window(s), gust ≥ ${limit} kt:`);
  for (const w of stormWindow(day, limit))
    console.log(`  ${w.start}–${w.end} UTC  ${w.durationMin} min, ${w.reports} reports ≥ ${limit} (last ${w.last}), peak G${w.peakGust} at ${w.peakAt}${w.ongoing ? ", ongoing" : ""}`);
}
console.log("\nall metar self-tests passed");
