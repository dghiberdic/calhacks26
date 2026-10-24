/**
 * Rain on a transparent 2D canvas: three depths of streaks blown a little off vertical, and rings opening on
 * the wet apron. Drawn at the screen's pixel density (up to 2×), so it stays sharp over the 4K render. One
 * path per layer per frame; nothing runs while it is stopped.
 */
type Drop = { x: number; y: number; v: number; len: number };
type Ring = { x: number; y: number; age: number; life: number; r: number };

const LAYERS = [
  { n: 260, speed: [900, 1150], len: [10, 18], width: 0.8, alpha: 0.16 },
  { n: 150, speed: [1300, 1600], len: [22, 38], width: 1.1, alpha: 0.24 },
  { n: 40, speed: [1900, 2300], len: [60, 110], width: 1.6, alpha: 0.2 },
] as const;

export class Rain {
  private readonly ctx: CanvasRenderingContext2D;
  private readonly dpr = Math.min(window.devicePixelRatio || 1, 2);
  private w = 0;
  private h = 0;
  private layers: Drop[][] = [];
  private rings: Ring[] = [];
  private raf = 0;
  private last = 0;
  /** Horizontal drift per unit of fall (the wind from the left). */
  slant = 0.2;
  /** Where the apron starts, as a share of the height: rings only open below it. */
  ground = 0.6;

  private readonly canvas: HTMLCanvasElement;

  constructor(canvas: HTMLCanvasElement) {
    this.canvas = canvas;
    this.ctx = canvas.getContext("2d")!;
  }

  setSize(w: number, h: number) {
    this.w = w;
    this.h = h;
    this.canvas.width = Math.round(w * this.dpr);
    this.canvas.height = Math.round(h * this.dpr);
    this.ctx.setTransform(this.dpr, 0, 0, this.dpr, 0, 0);
    // density follows the area, so a phone isn't a curtain and a wide screen isn't sparse
    const k = Math.max(0.35, Math.min(1.6, (w * h) / (1440 * 900)));
    this.layers = LAYERS.map((L) =>
      Array.from({ length: Math.round(L.n * k) }, () => ({
        x: Math.random() * (w + h * this.slant) - h * this.slant,
        y: Math.random() * h,
        v: L.speed[0] + Math.random() * (L.speed[1] - L.speed[0]),
        len: L.len[0] + Math.random() * (L.len[1] - L.len[0]),
      })),
    );
    this.rings = [];
  }

  /** One frame: advance by dt seconds and draw. dt = 0 draws a still frame (reduced motion). */
  frame(dt: number) {
    const { ctx, w, h } = this;
    ctx.clearRect(0, 0, w, h);
    ctx.lineCap = "round";
    LAYERS.forEach((L, i) => {
      ctx.beginPath();
      ctx.lineWidth = L.width;
      ctx.strokeStyle = `rgba(214,226,246,${L.alpha})`;
      for (const d of this.layers[i] ?? []) {
        d.y += d.v * dt;
        d.x += d.v * dt * this.slant;
        if (d.y - d.len > h) {
          d.y = -Math.random() * 80;
          d.x = Math.random() * (w + h * this.slant) - h * this.slant;
        }
        ctx.moveTo(d.x, d.y);
        ctx.lineTo(d.x - d.len * this.slant, d.y - d.len);
      }
      ctx.stroke();
    });
    // rings on the standing water: a few a second, flattened by the low camera
    if (dt > 0) {
      const spawn = dt * 26 * Math.max(0.4, w / 1440);
      for (let s = spawn; s > 0; s--) {
        if (Math.random() > s) continue;
        const y = this.ground + Math.random() * (1 - this.ground);
        this.rings.push({ x: Math.random() * w, y: y * h, age: 0, life: 0.55 + Math.random() * 0.4, r: (6 + Math.random() * 10) * (0.6 + (y - this.ground) * 2.2) });
      }
    }
    ctx.lineWidth = 1;
    for (const r of this.rings) {
      r.age += dt;
      const t = r.age / r.life;
      if (t >= 1) continue;
      ctx.strokeStyle = `rgba(214,226,246,${0.22 * (1 - t)})`;
      ctx.beginPath();
      ctx.ellipse(r.x, r.y, r.r * (0.3 + t), r.r * (0.3 + t) * 0.22, 0, 0, Math.PI * 2);
      ctx.stroke();
    }
    this.rings = this.rings.filter((r) => r.age < r.life);
  }

  start() {
    if (this.raf) return;
    this.last = performance.now();
    const loop = (now: number) => {
      this.raf = requestAnimationFrame(loop);
      const dt = Math.min(0.05, (now - this.last) / 1000);
      this.last = now;
      this.frame(dt);
    };
    this.raf = requestAnimationFrame(loop);
  }

  stop() {
    cancelAnimationFrame(this.raf);
    this.raf = 0;
  }
}
