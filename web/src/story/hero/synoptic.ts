import { contours } from "d3-contour";
import { curveCatmullRom, curveCatmullRomClosed, line } from "d3-shape";
import { toMap } from "../data/geo";

/** One ERA5 hour on a regular lat/lon grid (public/story/eowyn-era5-12z.json, from the Open-Meteo archive). */
export type Era5 = {
  source: string;
  date: string;
  step: number;
  bbox: { lonMin: number; lonMax: number; latMin: number; latMax: number };
  nx: number;
  ny: number;
  frame: { h: number; mslp: (number | null)[]; u: (number | null)[]; v: (number | null)[] };
};

export type Isobar = { hpa: number; d: string };
export type Centre = { pt: [number, number]; hpa: number };
export type Chart = { isobars: Isobar[]; low: Centre; high: Centre; u: number[]; v: number[] };

/** Upsample a grid ×f with bilinear interpolation so the contours come out smooth. */
function upsample(values: number[], nx: number, ny: number, f: number) {
  const NX = (nx - 1) * f + 1;
  const NY = (ny - 1) * f + 1;
  const out = new Array<number>(NX * NY);
  for (let J = 0; J < NY; J++) {
    const gy = J / f;
    const j = Math.min(ny - 2, Math.floor(gy));
    const fy = gy - j;
    for (let I = 0; I < NX; I++) {
      const gx = I / f;
      const i = Math.min(nx - 2, Math.floor(gx));
      const fx = gx - i;
      const a = values[j * nx + i];
      const b = values[j * nx + i + 1];
      const c = values[(j + 1) * nx + i];
      const d = values[(j + 1) * nx + i + 1];
      out[J * NX + I] = (a * (1 - fx) + b * fx) * (1 - fy) + (c * (1 - fx) + d * fx) * fy;
    }
  }
  return { values: out, nx: NX, ny: NY };
}

/** Contour MSLP every 4 hPa into smooth isobars in map space, plus the low and high centres. */
export function buildChart(era5: Era5): Chart {
  const { frame, nx, ny, bbox, step } = era5;
  const F = 3;
  const up = upsample(
    frame.mslp.map((v) => v ?? 1013),
    nx,
    ny,
    F,
  );
  const stepU = step / F;
  // d3-contour puts sample i at coordinate i + 0.5
  const at = (gx: number, gy: number): [number, number] => toMap(bbox.lonMin + (gx - 0.5) * stepU, bbox.latMax - (gy - 0.5) * stepU);

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
  const closed = line<[number, number]>().curve(curveCatmullRomClosed.alpha(0.5));
  const open = line<[number, number]>().curve(curveCatmullRom.alpha(0.5));
  const edge = (p: [number, number]) => p[0] <= 0.01 || p[1] <= 0.01 || p[0] >= up.nx - 0.01 || p[1] >= up.ny - 0.01;

  const isobars: Isobar[] = [];
  for (const mp of contours().size([up.nx, up.ny]).thresholds(thresholds)(up.values)) {
    for (const poly of mp.coordinates) {
      for (const ring of poly) {
        const pts = ring as [number, number][];
        if (pts.length < 8) continue;
        const thin = pts.filter((_, i) => i % 2 === 0);
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
  return {
    isobars,
    low: centre(loAt, lo),
    high: centre(hiAt, hi),
    u: frame.u.map((v) => v ?? 0),
    v: frame.v.map((v) => v ?? 0),
  };
}
