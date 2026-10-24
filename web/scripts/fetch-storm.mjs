// Fetch real reanalysis (ERA5 via Open-Meteo archive) MSLP + 10 m wind on a lat/lon grid,
// plus a NASA GIBS MODIS true-colour frame, for the hero's synoptic map.
//
//   node scripts/fetch-storm.mjs --date 2025-01-24 [--hours 0,3,6,9,12,15,18,21] [--step 1.5]
//
// Writes public/data/storm-<date>.json and public/data/sat-<date>.jpg
import { writeFileSync, mkdirSync } from "node:fs";
import { join } from "node:path";

const args = Object.fromEntries(
  process.argv.slice(2).reduce((acc, a, i, all) => (a.startsWith("--") ? [...acc, [a.slice(2), all[i + 1] && !all[i + 1].startsWith("--") ? all[i + 1] : "1"]] : acc), []),
);
const date = args.date ?? "2025-01-24";
const step = +(args.step ?? 1.5);
const hours = (args.hours ?? "0,3,6,9,12,15,18,21").split(",").map(Number);
const bbox = { lonMin: -60, lonMax: 18, latMin: 34, latMax: 70 }; // North Atlantic → Europe
const outDir = join(process.cwd(), "public", "data");
mkdirSync(outDir, { recursive: true });

const lons = [];
const lats = [];
for (let lon = bbox.lonMin; lon <= bbox.lonMax + 1e-9; lon += step) lons.push(+lon.toFixed(3));
for (let lat = bbox.latMax; lat >= bbox.latMin - 1e-9; lat -= step) lats.push(+lat.toFixed(3)); // north → south rows
const pts = [];
for (const lat of lats) for (const lon of lons) pts.push([lat, lon]);
console.log(`grid ${lons.length}×${lats.length} = ${pts.length} points, hours ${hours.join(",")}`);

const sleep = (ms) => new Promise((r) => setTimeout(r, ms));
const satOnly = "sat-only" in args;
const BATCH = 180; // Open-Meteo counts each location as a call; stay under ~600/min
const results = new Array(pts.length);
for (let i = 0; !satOnly && i < pts.length; i += BATCH) {
  const chunk = pts.slice(i, i + BATCH);
  const url =
    "https://archive-api.open-meteo.com/v1/archive?" +
    new URLSearchParams({
      latitude: chunk.map((p) => p[0]).join(","),
      longitude: chunk.map((p) => p[1]).join(","),
      start_date: date,
      end_date: date,
      hourly: "pressure_msl,wind_speed_10m,wind_direction_10m",
      wind_speed_unit: "kn",
      timezone: "GMT",
      cell_selection: "nearest",
    });
  for (let attempt = 0; ; attempt++) {
    const res = await fetch(url);
    if (res.ok) {
      const j = await res.json();
      const arr = Array.isArray(j) ? j : [j];
      arr.forEach((loc, k) => (results[i + k] = loc.hourly));
      break;
    }
    const body = await res.text();
    if (attempt > 4) throw new Error(`open-meteo ${res.status}: ${body.slice(0, 200)}`);
    console.log(`  retry after ${res.status} ${body.slice(0, 120)}`);
    await sleep(20000 * (attempt + 1));
  }
  console.log(`  ${Math.min(i + BATCH, pts.length)}/${pts.length}`);
  if (i + BATCH < pts.length) await sleep(21000);
}

const frames = satOnly ? [] : hours.map((h) => {
  const mslp = [];
  const u = [];
  const v = [];
  for (const r of results) {
    const p = r.pressure_msl[h];
    const spd = r.wind_speed_10m[h];
    const dir = r.wind_direction_10m[h];
    // meteorological "from" direction → vector the air moves along (east, north)
    const rad = (dir * Math.PI) / 180;
    mslp.push(p == null ? null : +p.toFixed(1));
    u.push(spd == null ? 0 : +(-spd * Math.sin(rad)).toFixed(1));
    v.push(spd == null ? 0 : +(-spd * Math.cos(rad)).toFixed(1));
  }
  return { h, mslp, u, v };
});

const out = {
  source: "ERA5 reanalysis via Open-Meteo archive API (open-meteo.com, CC BY 4.0)",
  date,
  step,
  bbox,
  nx: lons.length,
  ny: lats.length,
  lons,
  lats,
  units: { mslp: "hPa", wind: "kt (u east, v north)" },
  frames,
};
if (!satOnly) writeFileSync(join(outDir, `storm-${date}.json`), JSON.stringify(out));
console.log("wrote", join(outDir, `storm-${date}.json`));

// NASA GIBS MODIS Terra true colour (public domain), plate carrée, 60 px/degree
const [sLonMin, sLonMax, sLatMin, sLatMax] = (args.satbox ?? "-84,22,22,71").split(",").map(Number);
const sb = { lonMin: sLonMin, lonMax: sLonMax, latMin: sLatMin, latMax: sLatMax };
const ppd = +(args.ppd ?? 30);
const W = Math.round((sb.lonMax - sb.lonMin) * ppd);
const H = Math.round((sb.latMax - sb.latMin) * ppd);
const layer = args.layer ?? "MODIS_Terra_CorrectedReflectance_TrueColor";
const satUrl =
  "https://gibs.earthdata.nasa.gov/wms/epsg4326/best/wms.cgi?" +
  new URLSearchParams({
    SERVICE: "WMS",
    REQUEST: "GetMap",
    VERSION: "1.3.0",
    LAYERS: layer,
    STYLES: "",
    FORMAT: "image/jpeg",
    CRS: "EPSG:4326",
    BBOX: `${sb.latMin},${sb.lonMin},${sb.latMax},${sb.lonMax}`,
    WIDTH: String(W),
    HEIGHT: String(H),
    TIME: date,
  });
const sat = await fetch(satUrl);
if (!sat.ok) throw new Error(`gibs ${sat.status}`);
writeFileSync(join(outDir, `sat-${date}.jpg`), Buffer.from(await sat.arrayBuffer()));
writeFileSync(join(outDir, `sat-${date}.json`), JSON.stringify({ source: `NASA GIBS ${layer}`, date, bbox: sb, width: W, height: H }));
console.log("wrote", join(outDir, `sat-${date}.jpg`), W, "x", H);
