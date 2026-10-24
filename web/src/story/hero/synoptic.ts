import { contours } from "d3-contour";
import { curveCatmullRom, curveCatmullRomClosed, line } from "d3-shape";
import { toMap } from "../data/geo";

/** One ERA5 hour on a regular lat/lon grid (data/eowyn-era5-12z.json, from the Open-Meteo archive). */
export type Era5 = {
  source: string;
  date: string;
  step: number;
  bbox: { lonMin: number; lonMax: number; latMin: number; latMax: number };
  nx: number;
  ny: number;
  frame: { h: number; mslp: (number | null)[]; u: (number | null)[]; v: (number | null)[] };
};

/** The grid every ERA5 field in the story shares (rows north → south, 1.5° apart). */
export type Grid = { nx: number; ny: number; step: number; lonMin: number; latMax: number };

export type Isobar = { hpa: number; d: string };
export type Centre = { pt: [number, number]; hpa: number };
export type Chart = { isobars: Isobar[]; low: Centre; high: Centre };

/** Catmull-Rom weights for the four samples around a point at fraction t. */
function cubic(t: number): [number, number, number, number] {
  const t2 = t * t;
  const t3 = t2 * t;
  return [-0.5 * t3 + t2 - 0.5 * t, 1.5 * t3 - 2.5 * t2 + 1, -1.5 * t3 + 2 * t2 + 0.5 * t, 0.5 * t3 - 0.5 * t2];
}

/**
 * Upsample a grid ×f with bicubic (Catmull-Rom) interpolation, so the contours come out round where the
 * 1.5° grid is coarse: the tight rings at the centre of a deep low would be polygons with bilinear.
 */
function upsample(values: ArrayLike<number>, nx: number, ny: number, f: number) {
  const NX = (nx - 1) * f + 1;
  const NY = (ny - 1) * f + 1;
  const out = new Float64Array(NX * NY);
  const at = (i: number, j: number) => values[Math.min(ny - 1, Math.max(0, j)) * nx + Math.min(nx - 1, Math.max(0, i))];
  const wx: [number, number, number, number][] = [];
  for (let k = 0; k < f; k++) wx.push(cubic(k / f));
  for (let J = 0; J < NY; J++) {
    const j = Math.min(ny - 2, Math.floor(J / f));
    const wy = J === NY - 1 ? cubic(1) : wx[J - j * f];
    for (let I = 0; I < NX; I++) {
      const i = Math.min(nx - 2, Math.floor(I / f));
      const w = I === NX - 1 ? cubic(1) : wx[I - i * f];
      let v = 0;
      for (let b = 0; b < 4; b++) {
        const row = at(i - 1, j - 1 + b) * w[0] + at(i, j - 1 + b) * w[1] + at(i + 1, j - 1 + b) * w[2] + at(i + 2, j - 1 + b) * w[3];
        v += row * wy[b];
      }
      out[J * NX + I] = v;
    }
  }
  return { values: out, nx: NX, ny: NY };
}

const closed = line<[number, number]>().curve(curveCatmullRomClosed.alpha(0.5));
const open = line<[number, number]>().curve(curveCatmullRom.alpha(0.5));

/**
 * Contour one MSLP field every 4 hPa into smooth isobars in map space, plus the low and high centres.
 * Pure (no DOM): the hero calls it for the first paint and its worker for every 15 minutes of the loop.
 */
export function contourField(mslp: ArrayLike<number>, grid: Grid): Chart {
  const F = 3;
  const up = upsample(mslp, grid.nx, grid.ny, F);
  const stepU = grid.step / F;
  // d3-contour puts sample i at coordinate i + 0.5
  const at = (gx: number, gy: number): [number, number] => toMap(grid.lonMin + (gx - 0.5) * stepU, grid.latMax - (gy - 0.5) * stepU);

  let lo = Infinity;
  let hi = -Infinity;
  let loAt = 0;
  let hiAt = 0;
  // extremes away from the border
  for (let j = 6; j < up.ny - 6; j++)
    for (let i = 6; i < up.nx - 6; i++) {
      const v = up.values[j * up.nx + i];
      if (v < lo) [lo, loAt] = [v, j * up.nx + i];
      if (v > hi) [hi, hiAt] = [v, j * up.nx + i];
    }
  const thresholds: number[] = [];
  for (let t = Math.ceil(lo / 4) * 4; t < hi; t += 4) thresholds.push(t);
  const edge = (p: [number, number]) => p[0] <= 0.01 || p[1] <= 0.01 || p[0] >= up.nx - 0.01 || p[1] >= up.ny - 0.01;

  const isobars: Isobar[] = [];
  for (const mp of contours().size([up.nx, up.ny]).thresholds(thresholds)(Array.from(up.values))) {
    for (const poly of mp.coordinates) {
      for (const ring of poly) {
        const pts = ring as [number, number][];
        if (pts.length < 8) continue;
        // long lines lose every other vertex (the curve smooths them back); short rings keep all of theirs
        const thin = pts.length > 48 ? pts.filter((_, i) => i % 2 === 0) : pts;
        if (!pts.some(edge)) {
          isobars.push({ hpa: mp.value, d: closed(thin.map(([x, y]) => at(x, y))) ?? "" });
          continue;
        }
        // d3-contour closes rings along the grid border: keep only the interior runs, as open lines.
        let run: [number, number][] = [];
        const flush = () => {
          if (run.length > 4) isobars.push({ hpa: mp.value, d: open(run.map(([x, y]) => at(x, y))) ?? "" });
          run = [];
        };
        thin.forEach((p) => (edge(p) ? flush() : run.push(p)));
        flush();
      }
    }
  }
  isobars.sort((a, b) => a.hpa - b.hpa);
  const centre = (k: number, v: number): Centre => ({ pt: at((k % up.nx) + 0.5, Math.floor(k / up.nx) + 0.5), hpa: Math.round(v) });
  return { isobars, low: centre(loAt, lo), high: centre(hiAt, hi) };
}

/** The single embedded hour (first paint, reduced motion): its chart and its wind. */
export function buildChart(era5: Era5): Chart & { u: number[]; v: number[] } {
  const grid: Grid = { nx: era5.nx, ny: era5.ny, step: era5.step, lonMin: era5.bbox.lonMin, latMax: era5.bbox.latMax };
  return {
    ...contourField(
      era5.frame.mslp.map((v) => v ?? 1013),
      grid,
    ),
    u: era5.frame.u.map((v) => v ?? 0),
    v: era5.frame.v.map((v) => v ?? 0),
  };
}
