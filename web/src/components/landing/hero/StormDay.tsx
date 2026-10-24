"use client";

import { useEffect, useMemo, useRef, useState } from "react";
import { LAND_ATLANTIC, GRATICULE } from "@/data/geo/land";
import { AIRPORTS, K, greatCircle, pathOf, toMap, type View } from "@/lib/geo";
import { FLIGHTS, OPERATED, STORM, metarAt } from "@/data/scenario";
import { gsap, ScrollTrigger, useGSAP, prefersReducedMotion } from "@/components/motion/gsap";
import { SatelliteLayer } from "./SatelliteLayer";
import { WindParticles, type WindGrid } from "./WindParticles";
import { buildIsobars, type StormJSON, type Isobar } from "./synoptic";

type FramesJSON = { attribution: string; bbox: { lonMin: number; lonMax: number; latMin: number; latMax: number }; frames: { t: string; file: string }[] };
type Hour = { h: number; isobars: Isobar[]; lo: { pt: [number, number]; v: number }; u: number[]; v: number[] };

const BASE = "/data/bram";
const T0 = 7; // 07:00Z
const T1 = 21.5; // 21:30Z
const toHours = (s: string) => Number(s.slice(0, 2)) + Number(s.slice(3, 5)) / 60;
const fmt = (t: number) => {
  const m = Math.round((t * 60) / 5) * 5;
  return `${String(Math.floor(m / 60)).padStart(2, "0")}:${String(m % 60).padStart(2, "0")}`;
};

const CAPTIONS: { from: number; to: number; text: string; tone?: "owed" }[] = [
  { from: 7, to: 7.9, text: "07:00Z. Light rain at Dublin, 8 knots. A normal Tuesday." },
  { from: 7.9, to: 9.5, text: "07:55Z. EI-NSA is grounded at Dublin: a hydraulic leak on engine 1.", tone: "owed" },
  { from: 9.5, to: 11, text: "Storm Bram is coming north from the Azores on a jet streak." },
  { from: 11, to: 13.5, text: "11:00Z. Orange wind warning for Dublin." },
  { from: 13.5, to: 15.4, text: "13:30Z. Gusts pass 40 knots. Departures start to cancel." },
  { from: 15.4, to: 17, text: "15:30Z. Peak gust, 50 knots." },
  { from: 17, to: 19, text: "Still above limits until the 19:00Z report." },
  { from: 19, to: 21.2, text: "19:00Z. The wind eases. Three evening flights leave on time." },
  { from: 21.2, to: 22, text: "21:30Z. NS31 to Boston is cancelled anyway. Clear skies: you can see Dublin from orbit.", tone: "owed" },
];

const DUB = toMap(AIRPORTS.DUB.lon, AIRPORTS.DUB.lat);
const VIEW_START: View = { cx: -9.5 * K, cy: -53.2, w: 30 * K };
const VIEW_END: View = { cx: -7.6 * K, cy: -53.55, w: 13 * K };

/** Storm Bram, 9 Dec 2025, from orbit: scroll runs the clock from 07:00Z to 21:30Z. */
export function StormDay() {
  const root = useRef<HTMLDivElement>(null);
  const svgRef = useRef<SVGSVGElement>(null);
  const glRef = useRef<HTMLCanvasElement>(null);
  const pRef = useRef<HTMLCanvasElement>(null);
  const hud = useRef<{ clock?: HTMLSpanElement | null; metar?: HTMLParagraphElement | null; caption?: HTMLParagraphElement | null; count?: HTMLSpanElement | null; head?: SVGGElement | null; low?: SVGGElement | null }>({});
  const [storm, setStorm] = useState<StormJSON | null>(null);
  const [frames, setFrames] = useState<FramesJSON | null>(null);
  const [hours, setHours] = useState<Hour[]>([]);
  const [noGL, setNoGL] = useState(false);
  const view = useRef<View>({ ...VIEW_START });
  const state = useRef({ t: T0, reveal: 0, particles: 0 });

  useEffect(() => {
    let alive = true;
    Promise.all([fetch(`${BASE}/storm-2025-12-09.json`).then((r) => r.json()), fetch(`${BASE}/frames.json`).then((r) => r.json())]).then(([s, f]) => {
      if (!alive) return;
      setStorm(s);
      setFrames(f);
    });
    return () => {
      alive = false;
    };
  }, []);

  // Contour every hour we show, first hour immediately, the rest when the browser is idle.
  useEffect(() => {
    if (!storm) return;
    let cancelled = false;
    const make = (h: number): Hour => {
      const b = buildIsobars(storm, h);
      const fr = storm.frames.find((f) => f.h === h)!;
      return { h, isobars: b.isobars, lo: b.lo, u: fr.u, v: fr.v };
    };
    // eslint-disable-next-line react-hooks/set-state-in-effect -- first hour paints immediately
    setHours([make(T0)]);
    const rest = Array.from({ length: 22 - T0 }, (_, i) => T0 + 1 + i);
    const idle = (cb: () => void) => (typeof window.requestIdleCallback === "function" ? window.requestIdleCallback(() => cb()) : setTimeout(cb, 30));
    const step = () => {
      if (cancelled || !rest.length) return;
      const h = rest.shift()!;
      setHours((prev) => [...prev, make(h)]);
      idle(step);
    };
    idle(step);
    return () => {
      cancelled = true;
    };
  }, [storm]);

  const timeline = useMemo(() => {
    const x = (t: number) => ((t - T0) / (22 - T0)) * 100;
    return {
      x,
      window: { a: x(toHours(STORM.windowStart)), b: x(toHours(STORM.windowEnd)) },
      cancelled: FLIGHTS.filter((f) => f.verdict === "weather").map((f) => ({ id: f.id, x: x(toHours(f.sched)), t: toHours(f.sched) })),
      operated: OPERATED.map((o) => x(toHours(o.sched))),
      fault: x(toHours("07:55")),
      ns31: x(21.5),
    };
  }, []);

  const ns31Arc = useMemo(() => pathOf(greatCircle(AIRPORTS.DUB, AIRPORTS.BOS, 64)), []);

  // Render loop: satellite + particles + HUD, all driven by state refs (no React re-render per frame).
  useEffect(() => {
    if (!storm || !frames || !glRef.current || !pRef.current || !root.current || hours.length === 0) return;
    const fb = frames.bbox;
    let sat: SatelliteLayer;
    try {
      sat = new SatelliteLayer({
        canvas: glRef.current,
        image: `${BASE}/${frames.frames[0].file}`,
        satBox: [fb.lonMin * K, -fb.latMax, fb.lonMax * K, -fb.latMin],
        origin: DUB,
      });
    } catch {
      // No WebGL (old projector, locked-down browser): show the real 12:00Z frame instead.
      // eslint-disable-next-line react-hooks/set-state-in-effect -- one-off fallback when the GPU context fails
      setNoGL(true);
      return;
    }
    const grid: WindGrid = { nx: storm.nx, ny: storm.ny, lonMin: storm.bbox.lonMin, latMax: storm.bbox.latMax, step: storm.step, u: hours[0].u.slice(), v: hours[0].v.slice() };
    const wind = new WindParticles(pRef.current, grid, window.innerWidth < 768 ? 1100 : 2400);
    const frameTimes = frames.frames.map((f) => toHours(f.t));
    const el = root.current;
    let W = 0;
    let H = 0;
    const resize = () => {
      W = el.clientWidth;
      H = el.clientHeight;
      sat.setSize(W, H);
      wind.setSize(W, H);
    };
    resize();
    const ro = new ResizeObserver(resize);
    ro.observe(el);
    let visible = true;
    const io = new IntersectionObserver(([e]) => (visible = e.isIntersecting));
    io.observe(el);

    const byHour = new Map(hours.map((h) => [h.h, h]));
    let lastKey = "";
    let lastMin = -1;
    let last = performance.now();
    const groups = () => svgRef.current?.querySelectorAll<SVGGElement>("[data-hour]") ?? [];

    const tick = () => {
      if (!visible) return;
      const now = performance.now();
      const dt = (now - last) / 1000;
      last = now;
      const { t } = state.current;

      // view
      const v = view.current;
      const h = v.w * (H / Math.max(W, 1));
      const box: [number, number, number, number] = [v.cx - v.w / 2, v.cy - h / 2, v.cx + v.w / 2, v.cy + h / 2];
      const key = box.map((n) => n.toFixed(3)).join(",");
      if (key !== lastKey) {
        svgRef.current?.setAttribute("viewBox", `${box[0]} ${box[1]} ${box[2] - box[0]} ${box[3] - box[1]}`);
        svgRef.current?.style.setProperty("--u", String(v.w / Math.max(W, 1)));
        if (lastKey) wind.clear();
        lastKey = key;
      }

      // satellite frames around t
      let i = frameTimes.findIndex((ft) => ft > t) - 1;
      if (i < 0) i = t >= frameTimes[frameTimes.length - 1] ? frameTimes.length - 1 : 0;
      const j = Math.min(frameTimes.length - 1, i + 1);
      const mix = j === i ? 0 : Math.min(1, Math.max(0, (t - frameTimes[i]) / (frameTimes[j] - frameTimes[i])));
      for (const k of [i - 1, i, j, j + 1]) if (frames.frames[k]) sat.frame(`${BASE}/${frames.frames[k].file}`);
      sat.setFrames(sat.frame(`${BASE}/${frames.frames[i].file}`), sat.frame(`${BASE}/${frames.frames[j].file}`), mix);
      sat.reveal = state.current.reveal;
      sat.render(box, now / 1000);

      // isobars + low centre + wind for the two hours around t
      const h0 = Math.min(22, Math.max(T0, Math.floor(t)));
      const h1 = Math.min(22, h0 + 1);
      const f = Math.min(1, Math.max(0, t - h0));
      const A = byHour.get(h0);
      const B = byHour.get(h1) ?? A;
      {
        groups().forEach((g) => {
          const gh = Number(g.dataset.hour);
          const o = gh === h0 ? 1 - f : gh === h1 && B !== A ? f : 0;
          g.style.opacity = String(o);
          g.style.visibility = o > 0.01 ? "visible" : "hidden";
        });
      }
      if (A && B) {
        const lx = A.lo.pt[0] + (B.lo.pt[0] - A.lo.pt[0]) * f;
        const ly = A.lo.pt[1] + (B.lo.pt[1] - A.lo.pt[1]) * f;
        hud.current.low?.setAttribute("transform", `translate(${lx} ${ly})`);
        const lt = hud.current.low?.querySelector("[data-v]");
        if (lt) lt.textContent = String(Math.round(A.lo.v + (B.lo.v - A.lo.v) * f));
        for (let k = 0; k < grid.u.length; k++) {
          grid.u[k] = A.u[k] + (B.u[k] - A.u[k]) * f;
          grid.v[k] = A.v[k] + (B.v[k] - A.v[k]) * f;
        }
      }
      wind.alpha = state.current.particles;
      wind.frame(box, dt);

      // HUD (only when the displayed minute changes)
      const min = Math.round(t * 12);
      if (min !== lastMin) {
        lastMin = min;
        const label = fmt(t);
        if (hud.current.clock) hud.current.clock.textContent = `${label}Z`;
        if (hud.current.metar) hud.current.metar.textContent = metarAt(label).raw;
        const cap = CAPTIONS.find((c) => t >= c.from && t < c.to) ?? CAPTIONS[CAPTIONS.length - 1];
        if (hud.current.caption && hud.current.caption.dataset.text !== cap.text) {
          hud.current.caption.dataset.text = cap.text;
          hud.current.caption.textContent = cap.text;
          hud.current.caption.style.color = cap.tone === "owed" ? "#ff9a80" : "#f4f6f8";
          gsap.fromTo(hud.current.caption, { opacity: 0, y: 8 }, { opacity: 1, y: 0, duration: 0.35, ease: "power2.out", overwrite: true });
        }
        const n = timeline.cancelled.filter((c) => c.t <= t).length + (t >= 21.45 ? 1 : 0);
        if (hud.current.count) hud.current.count.textContent = String(n);
        hud.current.head?.setAttribute("transform", `translate(${timeline.x(t)} 0)`);
        svgRef.current?.parentElement?.querySelectorAll<HTMLElement>("[data-cx]").forEach((el2) => {
          const ct = Number(el2.dataset.cx);
          el2.dataset.on = String(ct <= t);
        });
      }
    };
    gsap.ticker.add(tick);
    sat.ready.then(() => ScrollTrigger.refresh());
    return () => {
      gsap.ticker.remove(tick);
      ro.disconnect();
      io.disconnect();
      sat.dispose();
    };
  }, [storm, frames, hours, timeline]);

  useGSAP(
    () => {
      if (prefersReducedMotion()) {
        state.current.reveal = 1;
        state.current.t = 15.5;
        return;
      }
      const s = gsap.timeline({
        scrollTrigger: { trigger: root.current, start: "top top", end: "+=280%", scrub: 0.9, pin: true, anticipatePin: 1, refreshPriority: 3 },
      });
      s.to(".sd-copy", { opacity: 0, y: -24, duration: 0.6, ease: "power2.in" }, 0)
        .to(state.current, { reveal: 1, duration: 1.1, ease: "power1.inOut" }, 0.1)
        .to(state.current, { particles: 0.24, duration: 1 }, 0.3)
        .to(".sd-lines", { opacity: 0.32, duration: 0.8 }, 0.4)
        .fromTo(".sd-hud", { opacity: 0, y: 12 }, { opacity: 1, y: 0, duration: 0.5 }, 0.6)
        .to(state.current, { t: T1, duration: 8, ease: "none" }, 1.0)
        .to(view.current, { cx: VIEW_END.cx, cy: VIEW_END.cy, w: VIEW_END.w, duration: 8, ease: "power1.inOut" }, 1.0)
        .to(state.current, { particles: 0.12, duration: 1 }, 8.2)
        .fromTo(".sd-ns31", { opacity: 0 }, { opacity: 1, duration: 0.4 }, 8.7)
        .fromTo(".sd-ns31-arc", { drawSVG: 0, opacity: 1 }, { drawSVG: "100%", opacity: 1, duration: 0.6, ease: "power2.out" }, 8.75)
        .to({}, { duration: 0.8 });
    },
    { scope: root },
  );

  // Intro plot of the first hour's chart
  useGSAP(
    () => {
      if (!hours.length || prefersReducedMotion()) return;
      const intro = gsap.timeline({ defaults: { ease: "plotter" } });
      intro
        .from(".sd-grat", { drawSVG: 0, duration: 1.3, ease: "power2.inOut" })
        .from(".sd-land", { drawSVG: 0, duration: 2.4 }, 0.15)
        .from("[data-hour='7'] path", { drawSVG: 0, duration: 1.4, stagger: 0.05 }, 0.6)
        .from(".sd-low", { opacity: 0, scale: 0.5, transformOrigin: "center", duration: 0.6, ease: "back.out(2)" }, 1.5)
        .to(state.current, { particles: 1, duration: 1.6, ease: "power1.inOut" }, 1.4)
        .from(".sd-dub", { opacity: 0, scale: 0, transformOrigin: "center", duration: 0.5, ease: "back.out(3)" }, 2.0);
    },
    { scope: root, dependencies: [hours.length > 0] },
  );

  return (
    <div ref={root} className="relative h-svh w-full overflow-hidden bg-night">
      <canvas ref={glRef} className="absolute inset-0 h-full w-full" aria-hidden="true" />
      {noGL && (
        // eslint-disable-next-line @next/next/no-img-element
        <img src={`${BASE}/true-1200.webp`} alt="EUMETSAT image of Storm Bram over Ireland at 12:00 UTC on 9 December 2025" className="absolute inset-0 h-full w-full object-cover opacity-80" />
      )}
      <svg ref={svgRef} className="absolute inset-0 h-full w-full" viewBox="-20 -60 30 18" preserveAspectRatio="xMidYMid slice" aria-hidden="true" style={{ ["--u" as string]: 0.02 }}>
        <g className="sd-lines" fill="none" strokeLinecap="round" strokeLinejoin="round">
          <path className="sd-grat" d={GRATICULE} stroke="#8e9aa8" strokeOpacity="0.18" style={{ strokeWidth: "calc(var(--u) * 1)" }} />
          <path className="sd-land" d={LAND_ATLANTIC} stroke="#d5dde6" strokeOpacity="0.85" style={{ strokeWidth: "calc(var(--u) * 1.15)" }} />
          {hours.map((hr) => (
            <g key={hr.h} data-hour={hr.h} style={{ opacity: hr.h === T0 ? 1 : 0, visibility: hr.h === T0 ? "visible" : "hidden" }}>
              {hr.isobars.map((b, i) => (
                <path key={i} d={b.d} stroke="#eef1f4" strokeOpacity={b.hpa % 20 === 0 ? 0.95 : 0.6} style={{ strokeWidth: `calc(var(--u) * ${b.hpa % 20 === 0 ? 1.9 : 1.1})` }} />
              ))}
            </g>
          ))}
        </g>
        <g ref={(el) => void (hud.current.low = el)} className="sd-low">
          <text textAnchor="middle" dominantBaseline="central" fill="#ff7a5c" style={{ fontSize: "calc(var(--u) * 44px)", fontWeight: 700, fontFamily: "var(--font-archivo)" }}>
            L
          </text>
          <text data-v textAnchor="middle" fill="#eef1f4" style={{ fontSize: "calc(var(--u) * 14px)", fontFamily: "var(--font-b612-mono)", transform: "translateY(calc(var(--u) * 38px))" }}>
            {hours[0]?.lo.v ?? ""}
          </text>
        </g>
        <path className="sd-ns31-arc" d={ns31Arc} fill="none" stroke="#ff7a5c" style={{ strokeWidth: "calc(var(--u) * 1.8)", opacity: 0 }} />
        <g className="sd-dub" transform={`translate(${DUB[0]} ${DUB[1]})`}>
          <circle fill="#ff7a5c" style={{ r: "calc(var(--u) * 5px)" } as React.CSSProperties} />
          <circle fill="none" stroke="#ff7a5c" strokeOpacity="0.55" style={{ r: "calc(var(--u) * 13px)", strokeWidth: "calc(var(--u) * 1)" } as React.CSSProperties} />
          <text fill="#eef1f4" style={{ fontSize: "calc(var(--u) * 13px)", fontFamily: "var(--font-b612-mono)", transform: "translate(calc(var(--u) * 17px), calc(var(--u) * 4px))" }}>
            EIDW
          </text>
        </g>
      </svg>
      <canvas ref={pRef} className="pointer-events-none absolute inset-0 h-full w-full" aria-hidden="true" />

      <div className="pointer-events-none absolute inset-x-0 top-0 h-48 bg-gradient-to-b from-night/80 to-transparent" />
      <div className="pointer-events-none absolute inset-x-0 bottom-0 h-3/5 bg-gradient-to-t from-night/95 via-night/45 to-transparent" />

      {/* opening copy */}
      <div className="sd-copy absolute inset-x-0 bottom-0 px-5 pb-14 md:px-16 md:pb-20">
        <h1 className="display max-w-[13ch] text-[clamp(52px,8.6vw,150px)] text-[#f4f6f8]">Every storm leaves a bill.</h1>
        <p className="mt-6 max-w-[46ch] text-[17px] leading-relaxed text-haze md:text-[19px]">
          StormCheck works out the real cause of every cancelled flight from the weather and the aircraft&rsquo;s own logs, then drafts what each passenger is owed by 9&nbsp;AM.
        </p>
        <p className="mt-10 flex items-center gap-3 text-[14px] text-mist">
          <span className="inline-block h-8 w-px animate-pulse bg-mist/60" aria-hidden="true" />
          Scroll to replay Storm Bram, 9 Dec 2025
        </p>
      </div>

      {/* time-lapse HUD */}
      <div className="sd-hud pointer-events-none absolute inset-0 opacity-0">
        <div className="absolute left-5 top-20 md:left-16 md:top-24">
          <span ref={(el) => void (hud.current.clock = el)} className="block font-mono text-[clamp(40px,5.2vw,76px)] leading-none text-[#f4f6f8]">
            07:00Z
          </span>
          <p ref={(el) => void (hud.current.metar = el)} className="mt-3 hidden max-w-[62ch] font-mono text-[13px] text-haze md:block">
            {metarAt("07:00").raw}
          </p>
        </div>
        <div className="absolute inset-x-5 bottom-8 md:inset-x-16 md:bottom-12">
          <div className="flex items-end justify-between gap-6">
            <p ref={(el) => void (hud.current.caption = el)} className="display-tight max-w-[30ch] text-[clamp(22px,2.4vw,36px)] leading-tight text-[#f4f6f8]">
              {CAPTIONS[0].text}
            </p>
            <p className="shrink-0 text-right text-[14px] text-haze">
              <span ref={(el) => void (hud.current.count = el)} className="display-tight block text-[44px] text-[#f4f6f8]">
                0
              </span>
              of 14 cancelled
            </p>
          </div>
          <svg viewBox="0 0 100 10" preserveAspectRatio="none" className="mt-6 h-6 w-full overflow-visible" aria-hidden="true">
            <rect x={timeline.window.a} y="2" width={timeline.window.b - timeline.window.a} height="6" fill="#8e9aa8" fillOpacity="0.28" />
            <line x1="0" x2="100" y1="5" y2="5" stroke="#5c6672" strokeWidth="0.15" vectorEffect="non-scaling-stroke" />
            {timeline.cancelled.map((c) => (
              <line key={c.id} x1={c.x} x2={c.x} y1="2.5" y2="7.5" stroke="#cfd8e2" strokeWidth="2" vectorEffect="non-scaling-stroke" />
            ))}
            {timeline.operated.map((x, i) => (
              <line key={i} x1={x} x2={x} y1="2.5" y2="7.5" stroke="#5fd08a" strokeWidth="2" vectorEffect="non-scaling-stroke" />
            ))}
            <line x1={timeline.fault} x2={timeline.fault} y1="0" y2="10" stroke="#ff7a5c" strokeWidth="2" vectorEffect="non-scaling-stroke" />
            <line x1={timeline.ns31} x2={timeline.ns31} y1="0" y2="10" stroke="#ff7a5c" strokeWidth="3" vectorEffect="non-scaling-stroke" />
            <g ref={(el) => void (hud.current.head = el)}>
              <line x1="0" x2="0" y1="-2" y2="12" stroke="#ffffff" strokeWidth="1.5" vectorEffect="non-scaling-stroke" />
            </g>
          </svg>
          <div className="mt-2 flex justify-between font-mono text-[11px] text-mist">
            <span>07:00Z</span>
            <span>Storm window {STORM.windowStart}–{STORM.windowEnd}Z</span>
            <span>22:00Z</span>
          </div>
        </div>
      </div>

      <div className="sd-ns31 pointer-events-none absolute right-5 top-24 max-w-[300px] rounded-lg border border-[#ff7a5c]/40 bg-[#1d1210]/80 p-4 opacity-0 backdrop-blur md:right-16">
        <p className="font-mono text-[13px] text-[#ff9a80]">NS31 DUB → BOS · 21:30Z</p>
        <p className="mt-1 text-[14px] text-[#f4f6f8]">Cancelled. Coded weather by Ops. The sky over Dublin is clear.</p>
      </div>

      <p className="pointer-events-none absolute bottom-2 right-5 text-[11px] text-mist/80 md:right-16">
        ERA5 reanalysis · {frames?.attribution ?? "Contains modified EUMETSAT data, 2025"}
      </p>
    </div>
  );
}
