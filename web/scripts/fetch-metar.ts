// Download a day of METAR/SPECI from the Iowa Environmental Mesonet archive and decode it with
// src/lib/metar.ts into the hero's compact JSON.
//
//   npx tsx scripts/fetch-metar.ts --station EIDW --date 2025-12-09 [--out public/data/bram] [--csv local.csv]
//
// Writes <out>/metar-<date>.json: [{ t, raw, dir, kt, gust, vis, wx, qnh }] (t = "HH:MM" UTC)
import { readFileSync, writeFileSync, mkdirSync } from "node:fs";
import { join, resolve } from "node:path";
import { parseMetar, stormWindow } from "../src/lib/metar";

const args = new Map<string, string>();
process.argv.slice(2).forEach((a, i, all) => a.startsWith("--") && args.set(a.slice(2), all[i + 1] ?? ""));
const station = args.get("station") ?? "EIDW";
const date = args.get("date") ?? "2025-12-09";
const outDir = resolve(args.get("out") ?? join("public", "data", "bram"));

const next = new Date(Date.parse(`${date}T00:00:00Z`) + 86_400_000).toISOString().slice(0, 10);
const url =
  "https://mesonet.agron.iastate.edu/cgi-bin/request/asos.py?" +
  `station=${station}&data=metar&sts=${date}T00:00Z&ets=${next}T00:00Z&tz=Etc/UTC&format=onlycomma&report_type=3&report_type=4`;

async function main() {
  const csv = args.get("csv")
    ? readFileSync(args.get("csv")!, "utf8")
    : await fetch(url).then((res) => {
        if (!res.ok) throw new Error(`IEM ${res.status}`);
        return res.text();
      });

  // station,valid,metar — the report itself never contains commas
  const rows = csv
    .trim()
    .split("\n")
    .slice(1)
    .map((line) => {
      const [, valid, ...rest] = line.split(",");
      return { valid: valid.trim(), raw: rest.join(",").trim() };
    })
    .filter((r) => r.raw && r.valid.startsWith(date));

  const seen = new Set<string>();
  type Row = { t: string; raw: string; dir: number | null; kt: number | null; gust: number | null; vis: number | null; wx: string[]; qnh: number | null };
  const out: Row[] = [];
  for (const { valid, raw } of rows) {
    const m = parseMetar(raw);
    if (seen.has(m.raw)) continue; // IEM occasionally repeats a bulletin verbatim
    seen.add(m.raw);
    const t = valid.slice(11, 16);
    if (m.t && m.t !== t) console.warn(`  ${t}: report time ${m.t} differs from IEM valid time`);
    out.push({ t, raw: m.raw, dir: m.dir, kt: m.kt, gust: m.gust, vis: m.vis, wx: m.wx, qnh: m.qnh });
  }

  mkdirSync(outDir, { recursive: true });
  const file = join(outDir, `metar-${date}.json`);
  writeFileSync(file, "[\n" + out.map((r) => "  " + JSON.stringify(r)).join(",\n") + "\n]\n");
  console.log(`wrote ${file}: ${out.length} reports`);
  for (const limit of [40, 45])
    console.log(`  gust ≥ ${limit} kt:`, stormWindow(out, limit).map((w) => `${w.start}–${w.end} (peak G${w.peakGust} @ ${w.peakAt})`).join(", ") || "none");
}

main().catch((e) => {
  console.error(e);
  process.exit(1);
});
