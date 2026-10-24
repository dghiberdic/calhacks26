import { contours } from "d3-contour";
import { line, curveCatmullRomClosed } from "d3-shape";

// ---------------------------------------------------------------------------
// Isobars: contour a mean-sea-level-pressure grid into smooth closed paths.
// ---------------------------------------------------------------------------

export type Grid = { w: number; h: number; values: ArrayLike<number> };

export type Isobar = { hpa: number; d: string; length: number };

const smoothRing = line<[number, number]>()
  .x((p) => p[0])
  .y((p) => p[1])
  .curve(curveCatmullRomClosed.alpha(0.5));

function ringLength(ring: [number, number][]) {
  let L = 0;
  for (let i = 1; i < ring.length; i++) L += Math.hypot(ring[i][0] - ring[i - 1][0], ring[i][1] - ring[i - 1][1]);
  return L;
}

/** Contour a pressure grid every `step` hPa. Coordinates stay in grid units. */
export function isobars(grid: Grid, step = 4, minRing = 6): Isobar[] {
  let lo = Infinity;
  let hi = -Infinity;
  for (let i = 0; i < grid.values.length; i++) {
    const v = grid.values[i];
    if (v < lo) lo = v;
    if (v > hi) hi = v;
  }
  const thresholds: number[] = [];
  for (let t = Math.ceil(lo / step) * step; t <= hi; t += step) thresholds.push(t);

  const gen = contours().size([grid.w, grid.h]).thresholds(thresholds).smooth(true);
  const out: Isobar[] = [];
  for (const mp of gen(Array.from(grid.values))) {
    for (const poly of mp.coordinates) {
      for (const ring of poly) {
        const pts = ring as [number, number][];
        // Drop rings hugging the grid border: d3-contour closes contours along the edge.
        const onEdge = pts.filter(([x, y]) => x <= 0.01 || y <= 0.01 || x >= grid.w - 0.01 || y >= grid.h - 0.01).length;
        if (pts.length < minRing) continue;
        // Thin the ring so the spline stays calm.
        const thin = pts.filter((_, i) => i % 2 === 0) as [number, number][];
        const d = onEdge > 2 ? openPath(pts, grid) : smoothRing(thin) ?? "";
        if (!d) continue;
        out.push({ hpa: mp.value, d, length: ringLength(pts) });
      }
    }
  }
  return out;
}

/** A contour that touches the border: draw only its interior run(s) as open paths. */
function openPath(pts: [number, number][], grid: Grid) {
  const inside = (p: [number, number]) => p[0] > 0.01 && p[1] > 0.01 && p[0] < grid.w - 0.01 && p[1] < grid.h - 0.01;
  const runs: [number, number][][] = [];
  let cur: [number, number][] = [];
  for (const p of pts) {
    if (inside(p)) cur.push(p);
    else if (cur.length) {
      runs.push(cur);
      cur = [];
    }
  }
  if (cur.length) runs.push(cur);
  const f = (n: number) => +n.toFixed(2);
  return runs
    .filter((r) => r.length > 3)
    .map((r) => {
      const thin = r.filter((_, i) => i % 2 === 0 || i === r.length - 1);
      // Catmull-Rom (open) via quadratic midpoints keeps it smooth without an extra dep.
      let d = `M${f(thin[0][0])},${f(thin[0][1])}`;
      for (let i = 1; i < thin.length - 1; i++) {
        const mx = (thin[i][0] + thin[i + 1][0]) / 2;
        const my = (thin[i][1] + thin[i + 1][1]) / 2;
        d += ` Q${f(thin[i][0])},${f(thin[i][1])} ${f(mx)},${f(my)}`;
      }
      const last = thin[thin.length - 1];
      d += ` L${f(last[0])},${f(last[1])}`;
      return d;
    })
    .join(" ");
}

// Deterministic PRNG so server and client draw the same field.
export function mulberry32(seed: number) {
  let a = seed >>> 0;
  return () => {
    a |= 0;
    a = (a + 0x6d2b79f5) | 0;
    let t = Math.imul(a ^ (a >>> 15), 1 | a);
    t = (t + Math.imul(t ^ (t >>> 7), 61 | t)) ^ t;
    return ((t ^ (t >>> 14)) >>> 0) / 4294967296;
  };
}

export type PressureCentre = { x: number; y: number; delta: number; rx: number; ry: number; rot?: number };

/** Synthetic MSLP field (for art direction / offline fallback). */
export function syntheticField(w: number, h: number, centres: PressureCentre[], base = 1012, seed = 7): Grid {
  const rnd = mulberry32(seed);
  const waves = Array.from({ length: 5 }, () => ({ kx: (rnd() - 0.5) * 0.12, ky: (rnd() - 0.5) * 0.12, ph: rnd() * 6.28, a: 0.4 + rnd() * 0.9 }));
  const values = new Float64Array(w * h);
  for (let j = 0; j < h; j++) {
    for (let i = 0; i < w; i++) {
      let v = base;
      for (const c of centres) {
        const rot = c.rot ?? 0;
        const dx = i - c.x;
        const dy = j - c.y;
        const u = dx * Math.cos(rot) + dy * Math.sin(rot);
        const q = -dx * Math.sin(rot) + dy * Math.cos(rot);
        v += c.delta * Math.exp(-((u * u) / (c.rx * c.rx) + (q * q) / (c.ry * c.ry)));
      }
      for (const wv of waves) v += wv.a * Math.sin(i * wv.kx + j * wv.ky + wv.ph);
      values[j * w + i] = v;
    }
  }
  return { w, h, values };
}

// ---------------------------------------------------------------------------
// Wind barbs (WMO convention): staff points to where the wind blows FROM.
// Pennant = 50 kt, full barb = 10 kt, half barb = 5 kt. Northern-hemisphere side.
// ---------------------------------------------------------------------------

export function windBarb(cx: number, cy: number, dirDeg: number, kt: number, L = 22): { staff: string; feathers: string; pennants: string } {
  const f = (n: number) => +n.toFixed(2);
  const a = ((dirDeg - 90) * Math.PI) / 180; // 0° = from north → staff points up
  const ux = Math.cos(a);
  const uy = Math.sin(a);
  // Feathers sit clockwise of the staff (NH convention).
  const px = -uy;
  const py = ux;
  const tipX = cx + ux * L;
  const tipY = cy + uy * L;
  const staff = `M${f(cx)},${f(cy)} L${f(tipX)},${f(tipY)}`;

  let rem = Math.round(kt / 5) * 5;
  const pennants: string[] = [];
  const feathers: string[] = [];
  const gap = L * 0.14;
  const fl = L * 0.46;
  let pos = 0;
  while (rem >= 50) {
    const sx = tipX - ux * pos;
    const sy = tipY - uy * pos;
    const ex = tipX - ux * (pos + gap * 1.3);
    const ey = tipY - uy * (pos + gap * 1.3);
    pennants.push(`M${f(sx)},${f(sy)} L${f(sx + px * fl + ux * fl * 0.12)},${f(sy + py * fl + uy * fl * 0.12)} L${f(ex)},${f(ey)} Z`);
    pos += gap * 1.5;
    rem -= 50;
  }
  while (rem >= 10) {
    const sx = tipX - ux * pos;
    const sy = tipY - uy * pos;
    feathers.push(`M${f(sx)},${f(sy)} L${f(sx + px * fl + ux * fl * 0.32)},${f(sy + py * fl + uy * fl * 0.32)}`);
    pos += gap;
    rem -= 10;
  }
  if (rem >= 5) {
    if (pos === 0) pos = gap; // a lone half barb sits inboard of the tip
    const sx = tipX - ux * pos;
    const sy = tipY - uy * pos;
    feathers.push(`M${f(sx)},${f(sy)} L${f(sx + px * fl * 0.5 + ux * fl * 0.16)},${f(sy + py * fl * 0.5 + uy * fl * 0.16)}`);
  }
  return { staff, feathers: feathers.join(" "), pennants: pennants.join(" ") };
}

// ---------------------------------------------------------------------------
// Synoptic fronts: a path plus evenly spaced symbols along it.
// ---------------------------------------------------------------------------

export function frontSymbols(path: SVGPathElement, kind: "cold" | "warm" | "occluded", spacing = 26, size = 7) {
  const L = path.getTotalLength();
  const out: { d: string; kind: "cold" | "warm" }[] = [];
  let k = 0;
  for (let s = spacing * 0.6; s < L - size; s += spacing, k++) {
    const p0 = path.getPointAtLength(s);
    const p1 = path.getPointAtLength(Math.min(L, s + size * 1.6));
    const ux = (p1.x - p0.x) / Math.hypot(p1.x - p0.x, p1.y - p0.y);
    const uy = (p1.y - p0.y) / Math.hypot(p1.x - p0.x, p1.y - p0.y);
    const nx = uy;
    const ny = -ux;
    const sym: "cold" | "warm" = kind === "occluded" ? (k % 2 ? "warm" : "cold") : kind;
    if (sym === "cold") {
      out.push({ kind: "cold", d: `M${p0.x},${p0.y} L${(p0.x + p1.x) / 2 + nx * size},${(p0.y + p1.y) / 2 + ny * size} L${p1.x},${p1.y} Z` });
    } else {
      const r = Math.hypot(p1.x - p0.x, p1.y - p0.y) / 2;
      out.push({ kind: "warm", d: `M${p0.x},${p0.y} A${r},${r} 0 0,1 ${p1.x},${p1.y} Z` });
    }
  }
  return out;
}
