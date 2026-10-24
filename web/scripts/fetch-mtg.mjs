// Fetch EUMETSAT MTG-I (0°) FCI RGB frames from the EUMETView WMS (no account needed; CC BY 4.0,
// attribution "Contains modified EUMETSAT data, <year>"), validate them, compress to WebP with sharp,
// and write frames.json for the hero's satellite loop.
//
//   node scripts/fetch-mtg.mjs --date 2025-12-09 [--from 07:00] [--to 21:30] [--every 30] [--true 12:00,15:00]
//        [--bbox -32,12,40,64] [--size 2200x1200] [--quality 72] [--out public/data/bram] [--raw <dir>]
//
// Raw server JPEGs are cached in --raw (default $TMPDIR/mtg-<date>; valid cached files are reused, so
// re-running only re-compresses). <out> gets <name>.webp — or <name>.jpg too when WebP isn't smaller.
// bbox is lonMin,lonMax,latMin,latMax in EPSG:4326 (plate carrée), so frames map linearly onto lon/lat.
import { mkdirSync, existsSync, readFileSync, writeFileSync, copyFileSync, statSync } from "node:fs";
import { join, resolve } from "node:path";
import { tmpdir } from "node:os";
import sharp from "sharp";

const args = Object.fromEntries(
  process.argv.slice(2).reduce((acc, a, i, all) => (a.startsWith("--") ? [...acc, [a.slice(2), all[i + 1] && !all[i + 1].startsWith("--") ? all[i + 1] : "1"]] : acc), []),
);
const date = args.date ?? "2025-12-09";
const [lonMin, lonMax, latMin, latMax] = (args.bbox ?? "-32,12,40,64").split(",").map(Number);
const [W, H] = (args.size ?? "2200x1200").split("x").map(Number);
const quality = +(args.quality ?? 72);
const outDir = resolve(args.out ?? join("public", "data", "bram"));
const rawDir = resolve(args.raw ?? join(tmpdir(), `mtg-${date}`));
const GEO = "mtg_fd:rgb_geocolour";
const TRUE = "mtg_fd:rgb_truecolour";
const MIN_BYTES = 20 * 1024; // a blank 2200×1200 render is a few KB; real frames are 300 KB+
mkdirSync(outDir, { recursive: true });
mkdirSync(rawDir, { recursive: true });

const toMin = (s) => s.split(":").reduce((h, m) => h * 60 + +m);
const hhmm = (min) => `${String(Math.floor(min / 60)).padStart(2, "0")}:${String(min % 60).padStart(2, "0")}`;
const jobs = [];
for (let m = toMin(args.from ?? "07:00"); m <= toMin(args.to ?? "21:30"); m += +(args.every ?? 30))
  jobs.push({ layer: GEO, t: hhmm(m), name: `geo-${hhmm(m).replace(":", "")}` });
for (const t of (args.true ?? "12:00,15:00").split(",").filter(Boolean))
  jobs.push({ layer: TRUE, t, name: `true-${t.replace(":", "")}` });

const wmsUrl = (layer, t) =>
  "https://view.eumetsat.int/geoserver/wms?" +
  new URLSearchParams({
    service: "WMS",
    version: "1.3.0",
    request: "GetMap",
    layers: layer,
    styles: "",
    format: "image/jpeg",
    crs: "EPSG:4326",
    bbox: `${latMin},${lonMin},${latMax},${lonMax}`, // WMS 1.3.0 + EPSG:4326 → lat,lon axis order
    width: String(W),
    height: String(H),
    time: `${date}T${t}:00Z`,
  });

/** null when the buffer is a plausible frame, otherwise the reason it isn't. */
async function problem(buf, type = "image/jpeg") {
  if (!type.startsWith("image/jpeg")) return `${type || "no content-type"}: ${buf.toString("utf8", 0, 400).replace(/<[^>]+>|\s+/g, " ").trim().slice(0, 140)}`;
  if (buf.length < MIN_BYTES) return `tiny (${(buf.length / 1024).toFixed(1)} KB)`;
  try {
    const img = sharp(buf);
    const { width, height } = await img.metadata();
    if (width !== W || height !== H) return `wrong size ${width}×${height}`;
    const { channels } = await img.stats();
    if (channels.every((c) => c.stdev < 3)) return "blank (uniform image)";
  } catch (e) {
    return `undecodable: ${e.message}`;
  }
  return null;
}

async function fetchFrame(job) {
  const raw = join(rawDir, `${job.name}.jpg`);
  if (existsSync(raw) && !("force" in args) && !(await problem(readFileSync(raw)))) return { ok: true, cached: true };
  const t0 = Date.now();
  try {
    const res = await fetch(wmsUrl(job.layer, job.t), { signal: AbortSignal.timeout(120_000) });
    const buf = Buffer.from(await res.arrayBuffer());
    const why = res.ok ? await problem(buf, res.headers.get("content-type") ?? "") : `HTTP ${res.status}`;
    if (why) return { ok: false, why };
    writeFileSync(raw, buf);
    return { ok: true, kb: buf.length / 1024, s: (Date.now() - t0) / 1000 };
  } catch (e) {
    return { ok: false, why: e.name === "TimeoutError" ? "timeout (120 s)" : String(e.cause?.code ?? e.message) };
  }
}

// pass 1 (2 in flight — EUMETView is a shared public service), then one deferred retry per failure
const failed = [];
let next = 0;
await Promise.all(
  [0, 1].map(async () => {
    while (next < jobs.length) {
      const job = jobs[next++];
      const r = await fetchFrame(job);
      console.log(`  ${job.name} ${r.ok ? (r.cached ? "cached" : `${r.kb.toFixed(0)} KB ${r.s.toFixed(1)} s`) : `FAILED ${r.why}`}`);
      if (!r.ok) failed.push(job);
    }
  }),
);
const omitted = [];
if (failed.length) {
  console.log(`retrying ${failed.length} frame(s) once after a pause…`);
  await new Promise((r) => setTimeout(r, 15_000));
  for (const job of failed) {
    const r = await fetchFrame(job);
    console.log(`  ${job.name} retry ${r.ok ? `ok ${r.kb.toFixed(0)} KB` : `FAILED ${r.why} → omitted`}`);
    if (!r.ok) omitted.push({ t: job.t, layer: job.layer, reason: r.why });
  }
}

// compress: WebP q<quality>; keep the server JPEG as well only when WebP isn't smaller
let jpgBytes = 0;
let outBytes = 0;
const done = jobs.filter((j) => !omitted.some((o) => o.t === j.t && o.layer === j.layer));
for (const job of done) {
  const raw = join(rawDir, `${job.name}.jpg`);
  const jpgSize = statSync(raw).size;
  const webp = await sharp(raw).webp({ quality, effort: 6 }).toBuffer();
  writeFileSync(join(outDir, `${job.name}.webp`), webp);
  job.file = `${job.name}.webp`;
  outBytes += webp.length;
  if (webp.length >= jpgSize) {
    copyFileSync(raw, join(outDir, `${job.name}.jpg`));
    job.file = `${job.name}.jpg`;
    outBytes += jpgSize;
    console.log(`  ${job.name}: WebP ${webp.length} ≥ JPEG ${jpgSize} bytes → kept JPEG too`);
  }
  jpgBytes += jpgSize;
}

const manifest = {
  source: "EUMETSAT MTG-I (0°) FCI full disc, Geo Colour RGB, via EUMETView WMS (view.eumetsat.int)",
  licence: "CC BY 4.0",
  attribution: `Contains modified EUMETSAT data, ${date.slice(0, 4)}`,
  layer: GEO,
  date,
  crs: "EPSG:4326",
  bbox: { lonMin, lonMax, latMin, latMax },
  width: W,
  height: H,
  frames: done.filter((j) => j.layer === GEO).map((j) => ({ t: j.t, file: j.file })),
  truecolour: { layer: TRUE, frames: done.filter((j) => j.layer === TRUE).map((j) => ({ t: j.t, file: j.file })) },
  ...(omitted.length ? { omitted } : {}),
};
writeFileSync(join(outDir, "frames.json"), JSON.stringify(manifest, null, 2) + "\n");
const mb = (b) => (b / 1048576).toFixed(1);
console.log(
  `wrote ${join(outDir, "frames.json")}: ${manifest.frames.length} geocolour + ${manifest.truecolour.frames.length} truecolour frames, ` +
    `${omitted.length} omitted; JPEG ${mb(jpgBytes)} MB → output ${mb(outBytes)} MB (raw cache ${rawDir})`,
);
