import { K, type Box } from "../data/geo";

/** ERA5 10 m wind on a regular grid, in knots (u east, v north). */
export type WindGrid = { nx: number; ny: number; lonMin: number; latMax: number; step: number; u: ArrayLike<number>; v: ArrayLike<number> };

type Particle = { x: number; y: number; age: number; life: number };

/**
 * Particles advected through the real wind field and drawn as fading trails on a transparent 2D
 * canvas, in the same map space as the SVG chart. Gale-force air (≥ 34 kt) draws brighter. The grid's
 * u and v may change under it every frame (the hero blends ERA5 hours as its clock runs).
 */
export class WindParticles {
  alpha = 0;
  private readonly ctx: CanvasRenderingContext2D;
  private readonly canvas: HTMLCanvasElement;
  private readonly grid: WindGrid;
  private readonly count: number;
  private readonly dpr = Math.min(window.devicePixelRatio || 1, 2);
  private ps: Particle[] = [];
  private w = 0;
  private h = 0;

  constructor(canvas: HTMLCanvasElement, grid: WindGrid, count: number) {
    this.canvas = canvas;
    this.grid = grid;
    this.count = count;
    this.ctx = canvas.getContext("2d")!;
  }

  setSize(w: number, h: number) {
    this.w = w;
    this.h = h;
    this.canvas.width = Math.round(w * this.dpr);
    this.canvas.height = Math.round(h * this.dpr);
    this.ctx.setTransform(this.dpr, 0, 0, this.dpr, 0, 0);
  }

  clear() {
    this.ctx.clearRect(0, 0, this.w, this.h);
  }

  /** Bilinear sample of the wind (kt) at map-space x, y. */
  private sample(x: number, y: number): [number, number] {
    const g = this.grid;
    const gx = (x / K - g.lonMin) / g.step;
    const gy = (g.latMax + y) / g.step;
    if (gx < 0 || gy < 0 || gx >= g.nx - 1 || gy >= g.ny - 1) return [0, 0];
    const i = gx | 0;
    const j = gy | 0;
    const fx = gx - i;
    const fy = gy - j;
    const k = j * g.nx + i;
    const lerp = (a: ArrayLike<number>) => (a[k] * (1 - fx) + a[k + 1] * fx) * (1 - fy) + (a[k + g.nx] * (1 - fx) + a[k + g.nx + 1] * fx) * fy;
    return [lerp(g.u), lerp(g.v)];
  }

  private spawn(view: Box, p: Particle = { x: 0, y: 0, age: 0, life: 0 }): Particle {
    p.x = view[0] + Math.random() * (view[2] - view[0]);
    p.y = view[1] + Math.random() * (view[3] - view[1]);
    p.age = 0;
    p.life = 60 + Math.random() * 90;
    return p;
  }

  frame(view: Box, dt: number) {
    const { ctx } = this;
    if (!this.ps.length) for (let i = 0; i < this.count; i++) this.ps.push(this.spawn(view));

    // fade the existing trails
    ctx.globalCompositeOperation = "destination-in";
    ctx.fillStyle = "rgba(0,0,0,0.88)";
    ctx.fillRect(0, 0, this.w, this.h);
    ctx.globalCompositeOperation = "source-over";
    if (this.alpha <= 0.001) return;

    const sx = this.w / (view[2] - view[0]);
    const sy = this.h / (view[3] - view[1]);
    const k = 0.0011 * (view[2] - view[0]) * Math.min(dt, 0.05) * 60;
    ctx.lineWidth = 1;
    ctx.lineCap = "round";
    // two passes: calm air faint, gale-force bright
    for (const gale of [false, true]) {
      ctx.beginPath();
      ctx.strokeStyle = gale ? `rgba(244,246,249,${0.6 * this.alpha})` : `rgba(200,208,219,${0.24 * this.alpha})`;
      for (const p of this.ps) {
        const [u, v] = this.sample(p.x, p.y);
        if (Math.hypot(u, v) > 34 !== gale) continue;
        const nx = p.x + u * K * k;
        const ny = p.y - v * k;
        ctx.moveTo((p.x - view[0]) * sx, (p.y - view[1]) * sy);
        ctx.lineTo((nx - view[0]) * sx, (ny - view[1]) * sy);
        p.x = nx;
        p.y = ny;
      }
      ctx.stroke();
    }
    for (const p of this.ps) {
      p.age++;
      if (p.age > p.life || p.x < view[0] || p.x > view[2] || p.y < view[1] || p.y > view[3]) this.spawn(view, p);
    }
  }
}
