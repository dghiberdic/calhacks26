import { contours } from "d3-contour";
import { line, curveCatmullRomClosed, curveCatmullRom } from "d3-shape";
import { toMap } from "@/lib/geo";

// Contour an ERA5 MSLP grid into smooth isobars in map space, plus the low/high centres.

export type StormJSON = {
  date: string;
  step: number;
  bbox: { lonMin: number; lonMax: number; latMin: number; latMax: number };
  nx: number;
  ny: number;
  frames: { h: number; mslp: (number | null)[]; u: number[]; v: number[] }[];
};

export type Isobar = { hpa: number; d: string; closed: boolean; r: number };


/** Upsample a grid ×f with bilinear interpolation so contours come out smooth. */
export function upsample(values: number[], nx: number, ny: number, f: number) {
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

export function buildIsobars(storm: StormJSON, frameH: number) {
  const fr = storm.frames.find((f) => f.h === frameH) ?? storm.frames[0];
  const raw = fr.mslp.map((v) => v ?? 1013);
  const F = 3;
  const up = upsample(raw, storm.nx, storm.ny, F);
  const stepU = storm.step / F;
  // d3-contour puts sample i at coordinate i + 0.5
  const toMapPt = (gx: number, gy: number): [number, number] => toMap(storm.bbox.lonMin + (gx - 0.5) * stepU, storm.bbox.latMax - (gy - 0.5) * stepU);

  let lo = Infinity;
  let hi = -Infinity;
  let loAt = 0;
  let hiAt = 0;
  // extremes away from the border
  for (let j = 6; j < up.ny - 6; j++)
    for (let i = 6; i < up.nx - 6; i++) {
      const v = up.values[j * up.nx + i];
      if (v < lo) ((lo = v), (loAt = j * up.nx + i));
      if (v > hi) ((hi = v), (hiAt = j * up.nx + i));
    }
  const thresholds: number[] = [];
  for (let t = Math.ceil(lo / 4) * 4; t < hi; t += 4) thresholds.push(t);
  const gen = contours().size([up.nx, up.ny]).thresholds(thresholds);
  const closedLine = line<[number, number]>().curve(curveCatmullRomClosed.alpha(0.5));
  const openLine = line<[number, number]>().curve(curveCatmullRom.alpha(0.5));
  const loPt = toMapPt((loAt % up.nx) + 0.5, Math.floor(loAt / up.nx) + 0.5);
  const hiPt = toMapPt((hiAt % up.nx) + 0.5, Math.floor(hiAt / up.nx) + 0.5);

  const isobars: Isobar[] = [];
  for (const mp of gen(up.values)) {
    for (const poly of mp.coordinates) {
      for (const ring of poly) {
        const pts = ring as [number, number][];
        if (pts.length < 8) continue;
        const edge = (p: [number, number]) => p[0] <= 0.01 || p[1] <= 0.01 || p[0] >= up.nx - 0.01 || p[1] >= up.ny - 0.01;
        const thin = pts.filter((_, i) => i % 2 === 0);
        const r = Math.hypot(...(() => {
          const c = toMapPt(thin[0][0], thin[0][1]);
          return [c[0] - loPt[0], c[1] - loPt[1]] as [number, number];
        })());
        if (!pts.some(edge)) {
          isobars.push({ hpa: mp.value, d: closedLine(thin.map(([x, y]) => toMapPt(x, y))) ?? "", closed: true, r });
        } else {
          // break at the border, keep interior runs
          let run: [number, number][] = [];
          const flush = () => {
            if (run.length > 4) isobars.push({ hpa: mp.value, d: openLine(run.map(([x, y]) => toMapPt(x, y))) ?? "", closed: false, r });
            run = [];
          };
          thin.forEach((p) => (edge(p) ? flush() : run.push(p)));
          flush();
        }
      }
    }
  }
  isobars.sort((a, b) => a.hpa - b.hpa);
  return { isobars, lo: { pt: loPt, v: Math.round(lo) }, hi: { pt: hiPt, v: Math.round(hi) }, wind: { u: fr.u, v: fr.v } };
}

