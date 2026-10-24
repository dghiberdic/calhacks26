import { memo, useImperativeHandle, useLayoutEffect, useMemo, useRef, useState, useSyncExternalStore, type CSSProperties, type Ref } from "react";
import { airport } from "@/lib/airports";
import { count } from "@/lib/format";
import { asset } from "../data/assets";
import era5Json from "../data/eowyn-era5-12z.json";
import { boxOf, greatCircle, K, pathOf, toMap, viewFor, type Box, type View } from "../data/geo";
import { COAST, GRATICULE } from "../data/geo-lines";
import { ms, routeEnds } from "../data/model";
import { useStory } from "../data/context";
import { gsap, MEDIA, PLOTTED, prefersReducedMotion, UNPLOTTED, useGSAP } from "../motion/gsap";
import { PIN_PRIORITY } from "../motion/useAutoRefresh";
import { Pending } from "../ui";
import { blendInto, clockAt, LOOP, loadSeries, SAT_BOX, STEPS, STILL_MIN, type Series } from "./loop";
import { buildChart, type Chart, type Era5, type Grid } from "./synoptic";
import { WindParticles } from "./WindParticles";
import type { SatelliteLayer } from "./SatelliteLayer";
import type { IsobarJob, IsobarResult } from "./isobars.worker";

const era5 = era5Json as Era5;
const GRID: Grid = { nx: era5.nx, ny: era5.ny, step: era5.step, lonMin: era5.bbox.lonMin, latMax: era5.bbox.latMax };
const NIGHT = "#080d17"; // --color-navy-950
const STILL_STEP = Math.round(STILL_MIN / LOOP.scan);
/** Isobar paths kept in the DOM; each 15-minute step fills as many as it needs. */
const POOL = 56;
const MONTHS = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"];

// three.js arrives alongside the first paint, not before it: the line chart and the wind run without it.
let satModule: Promise<typeof import("./SatelliteLayer")> | null = null;
const loadSat = () => (satModule ??= import("./SatelliteLayer"));

/** The storm, then the network it grounded. Boxes in lon/lat; the view fits them to any screen. */
const STORM_BOX = { desk: [-33, 3, 46.5, 63.5], phone: [-17, 1, 44, 58] } as const;
const ROUTES_BOX = { desk: [-92, 28, 33, 61], phone: [-19, 9, 41, 62] } as const;

const ease = (t: number) => t * t * (3 - 2 * t);
const lerpView = (a: View, b: View, t: number): View => ({ cx: a.cx + (b.cx - a.cx) * t, cy: a.cy + (b.cy - a.cy) * t, w: a.w * Math.pow(b.w / a.w, t) });
const u = (n: number) => `calc(var(--u) * ${n}px)`;

/** Which 15-minute step of the loop is on screen, and the low's pressure then; read by the HUD. */
type Tick = { step: number; low: number };
function createTicker(initial: Tick) {
  let state = initial;
  const subs = new Set<() => void>();
  return {
    get: () => state,
    set(next: Tick) {
      if (next.step === state.step && next.low === state.low) return;
      state = next;
      subs.forEach((f) => f());
    },
    subscribe(f: () => void) {
      subs.add(f);
      return () => void subs.delete(f);
    },
  };
}
type Ticker = ReturnType<typeof createTicker>;

/** What the isobar layer exposes to the render loop: swap in another hour without a React render. */
type IsoHandle = { apply: (c: Chart) => void };

/**
 * The isobars and the two centres. Rendered once by React (the 12:00Z chart); after that the render loop
 * rewrites the paths in place every 15 minutes of storm time.
 */
const IsobarLayer = memo(function IsobarLayer({ chart, ref }: { chart: Chart; ref: Ref<IsoHandle> }) {
  const group = useRef<SVGGElement>(null);
  const low = useRef<SVGGElement>(null);
  const high = useRef<SVGGElement>(null);
  useImperativeHandle(
    ref,
    () => ({
      apply(c) {
        const paths = group.current?.children;
        if (!paths) return;
        for (let i = 0; i < paths.length; i++) {
          const p = paths[i] as SVGPathElement;
          const b = c.isobars[i];
          if (!b) {
            if (p.getAttribute("d")) p.setAttribute("d", "");
            continue;
          }
          const major = b.hpa % 20 === 0;
          p.setAttribute("d", b.d);
          p.setAttribute("stroke-opacity", major ? "0.95" : "0.58");
          p.style.strokeWidth = u(major ? 1.9 : 1.1);
        }
        for (const [ref, centre] of [
          [low, c.low],
          [high, c.high],
        ] as const) {
          ref.current?.setAttribute("transform", `translate(${centre.pt[0]} ${centre.pt[1]})`);
          const label = ref.current?.lastElementChild;
          if (label) label.textContent = String(centre.hpa);
        }
      },
    }),
    [],
  );

  return (
    <g className="hero-wrap">
      <g ref={group} className="hero-lines" fill="none" strokeLinecap="round" strokeLinejoin="round">
        {Array.from({ length: POOL }, (_, i) => {
          const b = chart.isobars[i];
          const major = !!b && b.hpa % 20 === 0;
          return <path key={i} className="hero-iso" d={b?.d ?? ""} stroke="#f4f6f9" strokeOpacity={major ? 0.95 : 0.58} style={{ strokeWidth: u(major ? 1.9 : 1.1) }} {...PLOTTED} />;
        })}
      </g>
      {[
        { c: chart.low, letter: "L", fill: "#f4f6f9", ref: low },
        { c: chart.high, letter: "H", fill: "#a5b0bf", ref: high },
      ].map(({ c, letter, fill, ref }) => (
        <g key={letter} className="hero-centre" ref={ref} transform={`translate(${c.pt[0]} ${c.pt[1]})`}>
          <text textAnchor="middle" dominantBaseline="central" fill={fill} style={{ fontSize: u(44), fontWeight: 700, fontStretch: "118%" }}>
            {letter}
          </text>
          <text textAnchor="middle" fill={fill} className="font-mono" style={{ fontSize: u(13), transform: `translateY(${u(38)})` }}>
            {c.hpa}
          </text>
        </g>
      ))}
    </g>
  );
});

const stamp = (atMs: number) => {
  const d = new Date(atMs);
  return `${d.getUTCDate()} ${MONTHS[d.getUTCMonth()]} ${d.getUTCFullYear()}`;
};

/** The hour on the loop's clock, small, under the storm's name. */
function LiveStamp({ ticker }: { ticker: Ticker }) {
  const { step } = useSyncExternalStore(ticker.subscribe, ticker.get, ticker.get);
  const c = clockAt(step * LOOP.scan);
  return (
    <span className="tabular">
      {stamp(c.ms)}, {c.time}
    </span>
  );
}

/** The clock, the Dublin METAR then, and the 24 hours with the storm window marked (all from the data). */
function Hud({ ticker }: { ticker: Ticker }) {
  const story = useStory();
  const { step, low } = useSyncExternalStore(ticker.subscribe, ticker.get, ticker.get);
  const c = clockAt(step * LOOP.scan);
  // the report a dispatcher had at that minute: the latest one issued at or before it
  const metar = useMemo(() => [...(story.run?.metar ?? [])].sort((a, b) => ms(a.valid) - ms(b.valid)), [story.run]);
  let obs = null;
  for (const o of metar) if (ms(o.valid) <= c.ms) obs = o;
  const span = LOOP.hours * 3600_000;
  const win = story.window;
  const w0 = win ? Math.max(0, (ms(win.start) - LOOP.t0) / span) : null;
  const w1 = win ? Math.min(1, (ms(win.end) - LOOP.t0) / span) : null;
  const at = (c.ms - LOOP.t0) / span;
  const inWindow = w0 !== null && w1 !== null && at >= w0 && at <= w1;
  return (
    <div className="absolute left-5 top-20 max-w-[min(680px,calc(100vw-40px))] md:left-16 md:top-24">
      <p className="micro text-cloud-400">{stamp(c.ms)}</p>
      <p className="figure mt-2 text-[clamp(40px,5.2vw,76px)] font-medium leading-none text-cloud-50">{c.time}</p>
      <p className="mt-3 min-h-[1.6em] font-mono text-[12px] leading-relaxed text-cloud-300 md:text-[13px]">{story.run ? (obs?.raw ?? "") : <Pending ch={40} />}</p>
      <p className="mt-2 text-[14.5px] text-cloud-300">
        Dublin {obs?.gust ? <>gusting <span className="figure text-cloud-50">{obs.gust} kt</span></> : obs ? <><span className="figure text-cloud-50">{obs.sknt ?? 0} kt</span>, no gusts</> : <Pending ch={5} />} · the low at <span className="figure text-cloud-50">{low} hPa</span>
      </p>
      <div className="mt-5 w-[min(320px,70vw)]" aria-hidden="true">
        <div className="relative h-[3px] rounded-full bg-white/12">
          {w0 !== null && w1 !== null ? <span className="absolute inset-y-0 rounded-full bg-metar/70" style={{ left: `${w0 * 100}%`, width: `${(w1 - w0) * 100}%` }} /> : null}
          <span className="absolute -top-[5px] h-[13px] w-[2px] -translate-x-1/2 rounded-full bg-cloud-50" style={{ left: `${at * 100}%` }} />
        </div>
        <p className="mt-2 flex justify-between font-mono text-[10.5px] text-cloud-300">
          <span>23 Jan 18:00Z</span>
          <span className={inWindow ? "text-metar" : undefined}>{win ? "storm window" : ""}</span>
          <span>24 Jan 18:00Z</span>
        </p>
      </div>
    </div>
  );
}

/**
 * Storm Éowyn over 24 hours, 23 Jan 18:00Z to 24 Jan 18:00Z, on one clock: Meteosat infrared every 15
 * minutes, ERA5 isobars and 10 m wind every hour. The chart plots itself, particles ride the wind of the
 * hour on the clock, scrolling washes the satellite in and then pulls back to every Northstar route the
 * storm cancelled (from the API). Reduced motion holds everything at 12:00Z on the 24th.
 */
export function Hero() {
  const story = useStory();
  const root = useRef<HTMLElement>(null);
  const baseRef = useRef<SVGSVGElement>(null);
  const topRef = useRef<SVGSVGElement>(null);
  const glRef = useRef<HTMLCanvasElement>(null);
  const windRef = useRef<HTMLCanvasElement>(null);
  const iso = useRef<IsoHandle | null>(null);
  const state = useRef({ reveal: 0, particles: 0, zoom: 0, arcs: 0 });
  const [noGL, setNoGL] = useState(false);

  const chart = useMemo(() => buildChart(era5), []);
  const ticker = useMemo(() => createTicker({ step: STILL_STEP, low: chart.low.hpa }), [chart]);
  const station = story.run?.station ?? story.stormId.split("@")[0];
  const hub = airport(station);
  const hubPt = hub ? toMap(hub.lon, hub.lat) : null;
  const ends = useMemo(() => routeEnds(story.run), [story.run]);
  const arcs = useMemo(() => (hub ? ends.map((e) => ({ ...e, d: pathOf(greatCircle(hub, e)), pt: toMap(e.lon, e.lat) })) : []), [ends, hub]);
  const counters = story.run?.counters;
  // Client-only route: decide the arcs' first frame here so they never flash in drawn, then vanish.
  const staticArcs = prefersReducedMotion();

  // Render loop: satellite + wind + the SVG view box + the storm clock, all driven by refs (no React render per frame).
  useLayoutEffect(() => {
    const el = root.current;
    const base = baseRef.current;
    const top = topRef.current;
    const windCanvas = windRef.current;
    if (!el || !base || !top || !windCanvas) return;
    const still = prefersReducedMotion();
    const phone = () => window.innerWidth < 768;
    const windU = Float32Array.from(chart.u);
    const windV = Float32Array.from(chart.v);
    const wind = new WindParticles(windCanvas, { ...GRID, u: windU, v: windV }, phone() ? 900 : 1800);
    let sat: SatelliteLayer | null = null;
    let disposed = false;
    let W = el.clientWidth;
    let H = el.clientHeight;
    let lastKey = "";
    let lastArcs = -1;
    let glShown = true;

    // The clock: minutes into the loop. The video is its master once it plays; until then it holds at 12:00Z.
    let minute = STILL_MIN;
    let step = STILL_STEP;
    let series: Series | null = null;
    const charts: (Chart | undefined)[] = new Array(STEPS);
    charts[STILL_STEP] = chart;
    let video: HTMLVideoElement | null = null;
    let videoReady = false;
    let worker: Worker | null = null;
    const wrap = { fade: 1 };
    const wrapGroup = top.querySelector<SVGGElement>(".hero-wrap");

    // Arcs arrive with the API, after the timeline exists: the timeline tweens one number, this staggers it.
    const drawArcs = () => {
      const p = state.current.arcs;
      const paths = top.querySelectorAll<SVGPathElement>(".hero-arc");
      const labels = top.querySelectorAll<SVGGElement>(".hero-arc-label");
      if (p === lastArcs && paths.length === Number(top.dataset.arcs ?? -1)) return;
      lastArcs = p;
      top.dataset.arcs = String(paths.length);
      const n = Math.max(paths.length, 1);
      paths.forEach((path, i) => {
        const t = ease(Math.min(1, Math.max(0, p * 1.6 - (i / n) * 0.6)));
        path.setAttribute("stroke-dashoffset", String(1.01 * (1 - t)));
        const label = labels[i];
        if (label) label.style.opacity = String(Math.min(1, Math.max(0, t * 3 - 2)));
      });
    };

    const frame = (now: number, dt: number) => {
      const aspect = W / Math.max(H, 1);
      const sb = phone() ? STORM_BOX.phone : STORM_BOX.desk;
      const rb = phone() ? ROUTES_BOX.phone : ROUTES_BOX.desk;
      const v = lerpView(viewFor(sb[0], sb[1], sb[2], sb[3], aspect), viewFor(rb[0], rb[1], rb[2], rb[3], aspect), ease(state.current.zoom));
      const box: Box = boxOf(v, W, H);
      const key = box.map((n) => n.toFixed(3)).join(",");
      if (key !== lastKey) {
        const vb = `${box[0]} ${box[1]} ${box[2] - box[0]} ${box[3] - box[1]}`;
        base.setAttribute("viewBox", vb);
        top.setAttribute("viewBox", vb);
        el.style.setProperty("--u", String(v.w / Math.max(W, 1)));
        if (lastKey) wind.clear();
        lastKey = key;
      }
      // the storm clock
      if (video && videoReady && !video.paused) minute = Math.min(LOOP.hours * 60, video.currentTime * LOOP.rate);
      const s = Math.max(0, Math.min(STEPS - 1, Math.round(minute / LOOP.scan)));
      if (s !== step && charts[s]) {
        step = s;
        iso.current?.apply(charts[s]);
        ticker.set({ step: s, low: charts[s].low.hpa });
      }
      if (series && !still) {
        blendInto(windU, series.u, minute);
        blendInto(windV, series.v, minute);
      }
      if (sat) {
        sat.reveal = state.current.reveal;
        sat.fade = wrap.fade;
        // nothing revealed yet: the canvas would be plain night, so it stays hidden and costs nothing
        const shown = sat.render(box, now / 1000);
        if (shown !== glShown && glRef.current) {
          glShown = shown;
          glRef.current.style.visibility = shown ? "visible" : "hidden";
        }
      }
      if (!still) {
        wind.alpha = state.current.particles;
        wind.frame(box, dt);
      }
      drawArcs();
    };

    const resize = () => {
      W = el.clientWidth;
      H = el.clientHeight;
      wind.setSize(W, H);
      sat?.setSize(W, H);
      lastKey = "";
      if (still) frame(performance.now(), 0);
    };
    resize();
    const ro = new ResizeObserver(resize);
    ro.observe(el);

    if (still) {
      state.current = { reveal: 1, particles: 0, zoom: 0, arcs: 1 };
      frame(performance.now(), 0);
    }

    loadSat()
      .then(({ SatelliteLayer }) => {
        if (disposed || !glRef.current) return;
        const b = SAT_BOX;
        sat = new SatelliteLayer({ canvas: glRef.current, image: asset("eowyn-ir-12z.webp"), satBox: [b.lonMin * K, -b.latMax, b.lonMax * K, -b.latMin], origin: chart.low.pt, night: NIGHT });
        sat.setSize(W, H);
        if (video && videoReady) sat.useVideo(video);
        sat.ready.then(() => still && frame(performance.now(), 0)).catch(() => !disposed && setNoGL(true));
      })
      // No WebGL (an old projector, a locked-down browser) or the chunk failed: the chart and the wind carry on.
      .catch(() => !disposed && setNoGL(true));

    let visible = true;
    const playIfVisible = () => {
      if (video && videoReady && visible && video.paused && !video.ended) void video.play().catch(() => {});
    };

    // The 24 hours: the ERA5 series, its isobars (in a worker), then the satellite loop that drives the clock.
    // All of it waits for the page to settle and none of it loads under reduced motion.
    const idle = window.requestIdleCallback ?? ((cb: () => void) => window.setTimeout(cb, 600));
    const startLoop = () => {
      if (disposed) return;
      loadSeries(asset("eowyn-era5.bin"), GRID)
        .then((s) => {
          if (disposed) return;
          series = s;
          if (typeof Worker !== "undefined") {
            worker = new Worker(new URL("./isobars.worker.ts", import.meta.url), { type: "module" });
            worker.onmessage = (e: MessageEvent<IsobarResult[]>) => {
              for (const r of e.data) if (r.step !== STILL_STEP) charts[r.step] = r.chart;
            };
            worker.postMessage({ mslp: s.mslp, grid: GRID, steps: STEPS, from: STILL_STEP } satisfies IsobarJob);
          }
          const v = document.createElement("video");
          // in the DOM (tiny, invisible): some mobile browsers only play inline video that is in the page
          v.className = "pointer-events-none absolute left-0 top-0 h-px w-px opacity-0";
          v.setAttribute("aria-hidden", "true");
          v.muted = true;
          v.defaultMuted = true;
          v.playsInline = true;
          v.preload = "auto";
          v.setAttribute("muted", "");
          v.setAttribute("playsinline", "");
          v.src = asset("eowyn-ir.mp4");
          el.appendChild(v);
          // start on the 12:00Z frame the still shows, so the swap is invisible
          v.addEventListener("loadedmetadata", () => (v.currentTime = STILL_MIN / LOOP.rate), { once: true });
          v.addEventListener(
            "canplay",
            () => {
              if (disposed) return;
              videoReady = true;
              sat?.useVideo(v);
              playIfVisible();
            },
            { once: true },
          );
          // hold the last hour, dip, and start again from the evening before
          v.addEventListener("ended", () => {
            gsap
              .timeline()
              .to(wrap, { fade: 0, duration: 0.35, delay: 0.8, ease: "power1.in", onUpdate: () => wrapGroup?.style.setProperty("opacity", String(wrap.fade)) })
              .add(() => {
                minute = 0;
                v.currentTime = 0;
                playIfVisible();
              })
              .to(wrap, { fade: 1, duration: 0.5, ease: "power1.out", onUpdate: () => wrapGroup?.style.setProperty("opacity", String(wrap.fade)) });
          });
          video = v;
        })
        .catch(() => {
          // no series, no loop: the hero stays on 12:00Z, which is what reduced motion shows anyway
        });
    };
    const idleHandle = still ? 0 : idle(startLoop, { timeout: 1500 });

    const io = new IntersectionObserver(([e]) => {
      visible = e.isIntersecting;
      if (!visible) video?.pause();
      else playIfVisible();
    });
    io.observe(el);
    let last = performance.now();
    const tick = () => {
      const now = performance.now();
      const dt = (now - last) / 1000;
      last = now;
      if (visible) frame(now, dt);
    };
    if (!still) gsap.ticker.add(tick);
    return () => {
      disposed = true;
      (window.cancelIdleCallback ?? window.clearTimeout)(idleHandle);
      gsap.ticker.remove(tick);
      ro.disconnect();
      io.disconnect();
      worker?.terminate();
      if (video) {
        video.pause();
        video.removeAttribute("src");
        video.load();
        video.remove();
      }
      sat?.dispose();
    };
  }, [chart, ticker]);

  // The chart plots itself on arrival, like a pen plotter.
  useGSAP(
    () => {
      if (prefersReducedMotion()) return;
      gsap
        .timeline({ defaults: { ease: "plotter" }, delay: 0.15 })
        .from(".hero-grat", { ...UNPLOTTED, duration: 1.3, ease: "power2.inOut" })
        .from(".hero-land", { ...UNPLOTTED, duration: 2.4 }, 0.15)
        .from(".hero-iso", { ...UNPLOTTED, duration: 1.5, stagger: { each: 0.03, from: "random" } }, 0.55)
        .from(".hero-centre", { opacity: 0, scale: 0.6, transformOrigin: "50% 50%", duration: 0.6, ease: "back.out(2)", stagger: 0.25 }, 1.5)
        .to(state.current, { particles: 1, duration: 1.8, ease: "power1.inOut" }, 1.3)
        .from(".hero-hub", { opacity: 0, scale: 0, transformOrigin: "50% 50%", duration: 0.5, ease: "back.out(3)" }, 2.0)
        .from(".hero-copy > *", { opacity: 0, y: 18, duration: 0.9, stagger: 0.12, ease: "power3.out" }, 0.3);
    },
    { scope: root },
  );

  // Scroll: the copy gives way, the satellite washes in, then the camera pulls back to the routes.
  useGSAP(
    () => {
      const mm = gsap.matchMedia();
      mm.add(MEDIA.motion, () => {
        gsap.set(".hero-hud, .hero-end", { autoAlpha: 0 });
        gsap
          .timeline({ scrollTrigger: { trigger: root.current, start: "top top", end: "+=230%", scrub: 0.9, pin: true, anticipatePin: 1, refreshPriority: PIN_PRIORITY.hero } })
          .to(".hero-copy", { autoAlpha: 0, y: -28, duration: 0.6, ease: "power2.in" }, 0)
          .to(".hero-cue", { autoAlpha: 0, duration: 0.3 }, 0)
          .to(state.current, { reveal: 1, duration: 1.2, ease: "power1.inOut" }, 0.1)
          .to(state.current, { particles: 0.32, duration: 1 }, 0.3)
          .to(".hero-lines", { opacity: 0.4, duration: 0.9 }, 0.35)
          .fromTo(".hero-hud", { autoAlpha: 0, y: 12 }, { autoAlpha: 1, y: 0, duration: 0.5 }, 0.7)
          .to(".hero-hud", { autoAlpha: 0, y: -12, duration: 0.4 }, 1.75)
          .to(state.current, { zoom: 1, duration: 1.4, ease: "power1.inOut" }, 1.6)
          .to(state.current, { particles: 0.16, duration: 0.8 }, 1.8)
          .to(".hero-centre", { autoAlpha: 0, duration: 0.4 }, 1.7)
          .to(state.current, { arcs: 1, duration: 1.1, ease: "none" }, 2.05)
          .fromTo(".hero-end", { autoAlpha: 0, y: 14 }, { autoAlpha: 1, y: 0, duration: 0.5 }, 2.6)
          .to({}, { duration: 0.5 });
      });
    },
    { scope: root },
  );

  return (
    <section ref={root} aria-label={`${story.stormName ?? "The storm"} over Ireland, 23 to 24 January 2025`} data-section="hero" className="relative h-svh w-full overflow-hidden bg-navy-950" style={{ ["--u" as string]: 0.03 } as CSSProperties}>
      <canvas ref={glRef} className={noGL ? "hidden" : "absolute inset-0 h-full w-full"} aria-hidden="true" />
      <svg ref={baseRef} className="absolute inset-0 h-full w-full" preserveAspectRatio="xMidYMid slice" aria-hidden="true">
        <g className="hero-lines" fill="none" strokeLinecap="round" strokeLinejoin="round">
          <path className="hero-grat" d={GRATICULE} stroke="#85919f" strokeOpacity={0.2} style={{ strokeWidth: u(1) }} {...PLOTTED} />
          <path className="hero-land" d={COAST} stroke="#dfe4eb" strokeOpacity={0.85} style={{ strokeWidth: u(1.1) }} {...PLOTTED} />
        </g>
      </svg>
      <svg ref={topRef} className="absolute inset-0 h-full w-full" preserveAspectRatio="xMidYMid slice" aria-hidden="true">
        <IsobarLayer chart={chart} ref={iso} />
        <g fill="none">
          {arcs.map((a) => (
            <path key={a.iata} className="hero-arc" d={a.d} stroke="#f4f6f9" strokeOpacity={0.85} style={{ strokeWidth: u(1.3) }} {...PLOTTED} strokeDashoffset={staticArcs ? 0 : 1.01} />
          ))}
        </g>
        {arcs.map((a) => (
          <g key={a.iata} className="hero-arc-label" transform={`translate(${a.pt[0]} ${a.pt[1]})`} style={{ opacity: staticArcs ? 1 : 0 }}>
            <circle fill="#f4f6f9" style={{ r: u(2.6) } as CSSProperties} />
            <text fill="#dfe4eb" className="font-mono" style={{ fontSize: u(11.5), transform: `translate(${u(7)}, ${u(-7)})`, paintOrder: "stroke", stroke: "rgba(8,13,23,0.85)", strokeWidth: u(3.5), strokeLinejoin: "round" }}>
              {a.iata}
            </text>
          </g>
        ))}
        {hubPt ? (
          <g className="hero-hub" transform={`translate(${hubPt[0]} ${hubPt[1]})`}>
            <circle fill="#4f9fe0" style={{ r: u(4.5) } as CSSProperties} />
            <circle fill="none" stroke="#4f9fe0" strokeOpacity={0.6} style={{ r: u(11), strokeWidth: u(1) } as CSSProperties} />
            <text fill="#f4f6f9" className="font-mono" style={{ fontSize: u(12.5), transform: `translate(${u(15)}, ${u(4)})` }}>
              {station}
            </text>
          </g>
        ) : null}
      </svg>
      <canvas ref={windRef} className="pointer-events-none absolute inset-0 h-full w-full" aria-hidden="true" />

      <div className="pointer-events-none absolute inset-x-0 top-0 h-40 bg-gradient-to-b from-navy-950/80 to-transparent" />
      <div className="pointer-events-none absolute inset-x-0 bottom-0 h-3/5 bg-gradient-to-t from-navy-950/95 via-navy-950/45 to-transparent" />

      {/* opening copy */}
      <div className="hero-copy absolute inset-x-0 bottom-0 px-5 pb-16 md:px-16 md:pb-20">
        <p className="micro text-cloud-400">
          Dublin Airport · <LiveStamp ticker={ticker} />
        </p>
        <h1 className="text-balance display mt-4 max-w-[12ch] text-[clamp(46px,8.4vw,148px)] text-cloud-50">Storm Éowyn</h1>
        <p className="mt-6 max-w-[46ch] text-[16.5px] leading-relaxed text-cloud-300 md:text-[19px]">
          StormCheck finds the real cause of every cancelled flight and drafts what each passenger is owed. It asks a person only when the evidence disagrees.
        </p>
      </div>
      <div className="hero-cue pointer-events-none absolute bottom-10 right-16 hidden items-center gap-3 text-[13px] text-cloud-400 md:flex">
        <span>Scroll</span>
        <span className="relative block h-10 w-px overflow-hidden bg-white/15">
          <span className="story-cue absolute inset-0 bg-cloud-200" />
        </span>
      </div>

      {/* the hour on the clock, as the airport reported it */}
      <div className="hero-hud pointer-events-none absolute inset-0">
        <div className="absolute -left-48 -top-48 h-[760px] w-[min(1240px,150vw)] bg-[radial-gradient(closest-side,rgba(8,13,23,0.9),rgba(8,13,23,0.62)_55%,transparent)]" aria-hidden="true" />
        <Hud ticker={ticker} />
      </div>

      {/* pulled back: the network it grounded */}
      <div className="hero-end pointer-events-none absolute inset-x-0 bottom-0 px-5 pb-16 motion-reduce:hidden md:px-16 md:pb-20">
        <p className="display-tight max-w-[24ch] text-[clamp(28px,3.4vw,52px)] leading-[1.04] text-cloud-50">
          Northstar cancelled {counters?.cancelled !== undefined ? count(counters.cancelled) : <Pending ch={2} />} flights at Dublin,{" "}
          <span className="text-cloud-400">with {counters?.passengers !== undefined ? count(counters.passengers) : <Pending ch={4} />} passengers booked.</span>
        </p>
      </div>

      <p className="pointer-events-none absolute bottom-2 left-5 right-5 text-[10.5px] leading-snug text-cloud-500 md:left-auto md:right-16 md:text-right">
        Isobars every 4 hPa and 10 m wind: ERA5 reanalysis (Copernicus/ECMWF) via Open-Meteo · Satellite: Meteosat infrared 10.8 µm, © EUMETSAT 2025
      </p>
    </section>
  );
}
