import type { Grid } from "./synoptic";

/**
 * The hero's 24 hours, 23 Jan 18:00Z → 24 Jan 18:00Z: Meteosat infrared every 15 minutes (EUMETSAT) and
 * ERA5 pressure and wind every hour, on one clock. The video (public/story/eowyn-ir.mp4) runs one hour of
 * storm per second: 16 frames a second, 3.75 minutes apart (optical-flow in-betweens of the 15-minute scans).
 *
 * Where the files come from (built once, offline):
 * - eowyn-ir.mp4 / eowyn-ir-12z.webp: EUMETView WMS (view.eumetsat.int/geoserver/ows), layer msg_fes:ir108
 *   (MSG SEVIRI IR 10.8 µm, 0° service), EPSG:4326, lon −50…20, lat 35…70, 1400×700, one GetMap per
 *   15 minutes with TIME=. Grey 255 (off the disk) → 0, data 1…241 → 14…255; three in-betweens per scan from
 *   DIS optical flow in both directions (OpenCV); H.264 High at ~1.2 Mbit/s (WebCodecs in Chrome) in a
 *   hand-written faststart MP4, a keyframe every 4 s. © EUMETSAT 2025.
 * - eowyn-era5.bin: Open-Meteo archive API, models=era5, hourly pressure_msl, wind_speed_10m and
 *   wind_direction_10m (kn) on the same 1.5° grid as data/eowyn-era5-12z.json (which is its 12:00Z hour).
 *   Little-endian int16, per hour: mslp (hPa − 900) × 10, then u, then v (kt × 10), rows north → south.
 */
export const LOOP = {
  t0: Date.UTC(2025, 0, 23, 18),
  hours: 24,
  /** storm minutes per second of video */
  rate: 60,
  scan: 15,
} as const;
export const LOOP_END = LOOP.t0 + LOOP.hours * 3600_000;
/** Reduced motion, the poster and the first paint: the 12:00Z hour on the 24th. */
export const STILL_AT = Date.UTC(2025, 0, 24, 12);
export const STILL_MIN = (STILL_AT - LOOP.t0) / 60_000;
/** Map-space box of the satellite frames (plate carrée, lon −50…20, lat 35…70). */
export const SAT_BOX = { lonMin: -50, lonMax: 20, latMin: 35, latMax: 70 } as const;
/** 15-minute steps in the loop (97: both ends included). */
export const STEPS = (LOOP.hours * 60) / LOOP.scan + 1;

/** ERA5 hours (eowyn-era5.bin, see the story data notes): mslp in hPa, wind in kt. */
export type Series = { grid: Grid; mslp: Float32Array[]; u: Float32Array[]; v: Float32Array[] };

export async function loadSeries(url: string, grid: Grid): Promise<Series> {
  const res = await fetch(url);
  if (!res.ok) throw new Error(`ERA5 series: ${res.status}`);
  const raw = new Int16Array(await res.arrayBuffer());
  const n = grid.nx * grid.ny;
  const hours = raw.length / (3 * n);
  const out: Series = { grid, mslp: [], u: [], v: [] };
  for (let h = 0; h < hours; h++) {
    const base = h * 3 * n;
    const p = new Float32Array(n);
    const u = new Float32Array(n);
    const v = new Float32Array(n);
    for (let k = 0; k < n; k++) {
      p[k] = 900 + raw[base + k] / 10;
      u[k] = raw[base + n + k] / 10;
      v[k] = raw[base + 2 * n + k] / 10;
    }
    out.mslp.push(p);
    out.u.push(u);
    out.v.push(v);
  }
  return out;
}

/** Linear blend of two hourly fields into `out`, at `minutes` into the loop. */
export function blendInto(out: Float32Array, frames: Float32Array[], minutes: number) {
  const h = Math.max(0, Math.min(frames.length - 1, minutes / 60));
  const i = Math.min(frames.length - 2, Math.floor(h));
  const f = h - i;
  const a = frames[i];
  const b = frames[i + 1];
  for (let k = 0; k < out.length; k++) out[k] = a[k] + (b[k] - a[k]) * f;
  return out;
}

/** "24 Jan 03:15Z" pieces for a loop minute. */
export function clockAt(minutes: number) {
  const d = new Date(LOOP.t0 + minutes * 60_000);
  const hh = String(d.getUTCHours()).padStart(2, "0");
  const mm = String(d.getUTCMinutes()).padStart(2, "0");
  return { ms: d.getTime(), time: `${hh}:${mm}Z`, day: d.getUTCDate() };
}
