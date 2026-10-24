// Wind particles advected through a real 10 m wind grid (kt, u east / v north), drawn as
// fading trails on a transparent 2D canvas in the same map space as the SVG layer.
import { K } from "@/lib/geo";

export type WindGrid = {
  nx: number;
  ny: number;
  lonMin: number;
  latMax: number;
  step: number;
  u: number[];
  v: number[];
};

type P = { x: number; y: number; age: number; life: number };

export class WindParticles {
  private ctx: CanvasRenderingContext2D;
  private ps: P[] = [];
  private dpr = Math.min(window.devicePixelRatio, 1.5);
  private w = 0;
  private h = 0;
  alpha = 0;
  speed = 1;

  constructor(
    private canvas: HTMLCanvasElement,
    private grid: WindGrid,
    private count = 2600,
  ) {
    this.ctx = canvas.getContext("2d")!;
  }

  setSize(w: number, h: number) {
    this.w = w;
    this.h = h;
    this.canvas.width = Math.round(w * this.dpr);
    this.canvas.height = Math.round(h * this.dpr);
    this.ctx.setTransform(this.dpr, 0, 0, this.dpr, 0, 0);
  }

  /** Bilinear sample of wind (kt) at map-space x, y. */
  private sample(x: number, y: number): [number, number] {
    const g = this.grid;
    const lon = x / K;
    const lat = -y;
    const gx = (lon - g.lonMin) / g.step;
    const gy = (g.latMax - lat) / g.step;
    if (gx < 0 || gy < 0 || gx >= g.nx - 1 || gy >= g.ny - 1) return [0, 0];
    const i = gx | 0;
    const j = gy | 0;
    const fx = gx - i;
    const fy = gy - j;
    const at = (a: number[], ii: number, jj: number) => a[jj * g.nx + ii];
    const lerp2 = (a: number[]) =>
      (at(a, i, j) * (1 - fx) + at(a, i + 1, j) * fx) * (1 - fy) + (at(a, i, j + 1) * (1 - fx) + at(a, i + 1, j + 1) * fx) * fy;
    return [lerp2(g.u), lerp2(g.v)];
  }

  private spawn(view: [number, number, number, number], p?: P): P {
    const q = p ?? ({} as P);
    q.x = view[0] + Math.random() * (view[2] - view[0]);
    q.y = view[1] + Math.random() * (view[3] - view[1]);
    q.age = 0;
    q.life = 60 + Math.random() * 90;
    return q;
  }

  clear() {
    this.ctx.clearRect(0, 0, this.w, this.h);
  }

  frame(view: [number, number, number, number], dt: number) {
    const { ctx } = this;
    if (this.ps.length === 0) for (let i = 0; i < this.count; i++) this.ps.push(this.spawn(view));

    // fade existing trails
    ctx.globalCompositeOperation = "destination-in";
    ctx.fillStyle = "rgba(0,0,0,0.9)";
    ctx.fillRect(0, 0, this.w, this.h);
    ctx.globalCompositeOperation = "source-over";
    if (this.alpha <= 0.001) return;

    const sx = this.w / (view[2] - view[0]);
    const sy = this.h / (view[3] - view[1]);
    const k = 0.0011 * (view[2] - view[0]) * this.speed * Math.min(dt, 0.05) * 60;
    ctx.lineWidth = 1;
    ctx.lineCap = "round";

    // two passes: calm air faint, gale-force bright
    for (const pass of [0, 1]) {
      ctx.beginPath();
      ctx.strokeStyle = pass ? `rgba(244,246,248,${0.75 * this.alpha})` : `rgba(200,210,222,${0.32 * this.alpha})`;
      for (const p of this.ps) {
        const [u, v] = this.sample(p.x, p.y);
        const spd = Math.hypot(u, v);
        if ((spd > 34 ? 1 : 0) !== pass) continue;
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
