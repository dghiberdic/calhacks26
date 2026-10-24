import { useLayoutEffect, useMemo, useRef, useState, type CSSProperties } from "react";
import { airport } from "@/lib/airports";
import { count, longDate, zulu } from "@/lib/format";
import { asset } from "../data/assets";
import era5Json from "../data/eowyn-era5-12z.json";
import modis from "../data/eowyn-modis.json";
import { boxOf, greatCircle, K, pathOf, toMap, viewFor, type Box, type View } from "../data/geo";
import { COAST, GRATICULE } from "../data/geo-lines";
import { nearestObs, routeEnds } from "../data/model";
import { useStory } from "../data/context";
import { gsap, MEDIA, PLOTTED, prefersReducedMotion, UNPLOTTED, useGSAP } from "../motion/gsap";
import { PIN_PRIORITY } from "../motion/useAutoRefresh";
import { Pending } from "../ui";
import { buildChart, type Era5 } from "./synoptic";
import { WindParticles } from "./WindParticles";
import type { SatelliteLayer } from "./SatelliteLayer";

const era5 = era5Json as Era5;
const NIGHT = "#080d17"; // --color-navy-950

// three.js arrives alongside the first paint, not before it: the line chart and the wind run without it.
let satModule: Promise<typeof import("./SatelliteLayer")> | null = null;
const loadSat = () => (satModule ??= import("./SatelliteLayer"));

/** The storm, then the network it grounded. Boxes in lon/lat; the view fits them to any screen. */
const STORM_BOX = { desk: [-33, 3, 46.5, 63.5], phone: [-17, 1, 47, 61] } as const;
const ROUTES_BOX = { desk: [-92, 28, 33, 61], phone: [-19, 9, 41, 62] } as const;

const ease = (t: number) => t * t * (3 - 2 * t);
const lerpView = (a: View, b: View, t: number): View => ({ cx: a.cx + (b.cx - a.cx) * t, cy: a.cy + (b.cy - a.cy) * t, w: a.w * Math.pow(b.w / a.w, t) });
const u = (n: number) => `calc(var(--u) * ${n}px)`;

/**
 * Storm Éowyn at 12:00Z on 24 Jan 2025, the hour the Terra satellite passed over: ERA5 isobars plot
 * themselves, particles ride the real 10 m wind, and scrolling washes the satellite in, then pulls
 * back to every Northstar route the storm cancelled (from the API).
 */
export function Hero() {
  const story = useStory();
  const root = useRef<HTMLDivElement>(null);
  const svgRef = useRef<SVGSVGElement>(null);
  const glRef = useRef<HTMLCanvasElement>(null);
  const windRef = useRef<HTMLCanvasElement>(null);
  const state = useRef({ reveal: 0, particles: 0, zoom: 0, arcs: 0 });
  const [noGL, setNoGL] = useState(false);

  const chart = useMemo(() => buildChart(era5), []);
  const station = story.run?.station ?? story.stormId.split("@")[0];
  const hub = airport(station);
  const hubPt = hub ? toMap(hub.lon, hub.lat) : toMap(-6.27, 53.42);
  const ends = useMemo(() => routeEnds(story.run), [story.run]);
  const arcs = useMemo(() => (hub ? ends.map((e) => ({ ...e, d: pathOf(greatCircle(hub, e)), pt: toMap(e.lon, e.lat) })) : []), [ends, hub]);
  const frameAt = `${era5.date}T${String(era5.frame.h).padStart(2, "0")}:00:00Z`;
  const obs = nearestObs(story.run?.metar, frameAt);
  const counters = story.run?.counters;
  // Client-only route: decide the arcs' first frame here so they never flash in drawn, then vanish.
  const still = prefersReducedMotion();

  // Render loop: satellite + wind + the SVG view box, all driven by refs (no React render per frame).
  useLayoutEffect(() => {
    const el = root.current;
    const svg = svgRef.current;
    const windCanvas = windRef.current;
    if (!el || !svg || !windCanvas) return;
    const still = prefersReducedMotion();
    const phone = () => window.innerWidth < 768;
    const wind = new WindParticles(windCanvas, { nx: era5.nx, ny: era5.ny, lonMin: era5.bbox.lonMin, latMax: era5.bbox.latMax, step: era5.step, u: chart.u, v: chart.v }, phone() ? 900 : 1800);
    let sat: SatelliteLayer | null = null;
    let disposed = false;
    let W = el.clientWidth;
    let H = el.clientHeight;
    let lastKey = "";
    let lastArcs = -1;

    // Arcs arrive with the API, after the timeline exists: the timeline tweens one number, this staggers it.
    const drawArcs = () => {
      const p = state.current.arcs;
      const paths = svg.querySelectorAll<SVGPathElement>(".hero-arc");
      const labels = svg.querySelectorAll<SVGGElement>(".hero-arc-label");
      if (p === lastArcs && paths.length === Number(svg.dataset.arcs ?? -1)) return;
      lastArcs = p;
      svg.dataset.arcs = String(paths.length);
      const n = Math.max(paths.length, 1);
      paths.forEach((el, i) => {
        const t = ease(Math.min(1, Math.max(0, p * 1.6 - (i / n) * 0.6)));
        el.setAttribute("stroke-dashoffset", String(1.01 * (1 - t)));
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
        svg.setAttribute("viewBox", `${box[0]} ${box[1]} ${box[2] - box[0]} ${box[3] - box[1]}`);
        svg.style.setProperty("--u", String(v.w / Math.max(W, 1)));
        if (lastKey) wind.clear();
        lastKey = key;
      }
      if (sat) {
        sat.reveal = state.current.reveal;
        sat.render(box, now / 1000);
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
        const b = modis.bbox;
        sat = new SatelliteLayer({ canvas: glRef.current, image: asset("eowyn-modis.webp"), satBox: [b.lonMin * K, -b.latMax, b.lonMax * K, -b.latMin], origin: chart.low.pt, night: NIGHT });
        sat.setSize(W, H);
        sat.ready.then(() => still && frame(performance.now(), 0)).catch(() => !disposed && setNoGL(true));
      })
      // No WebGL (an old projector, a locked-down browser) or the chunk failed: the chart and the wind carry on.
      .catch(() => !disposed && setNoGL(true));

    let visible = true;
    const io = new IntersectionObserver(([e]) => (visible = e.isIntersecting));
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
      gsap.ticker.remove(tick);
      ro.disconnect();
      io.disconnect();
      sat?.dispose();
    };
  }, [chart]);

  // The chart plots itself on arrival, like a pen plotter.
  useGSAP(
    () => {
      if (prefersReducedMotion()) return;
      gsap
        .timeline({ defaults: { ease: "plotter" }, delay: 0.15 })
        .from(".hero-grat", { ...UNPLOTTED, duration: 1.3, ease: "power2.inOut" })
        .from(".hero-land", { ...UNPLOTTED, duration: 2.4 }, 0.15)
        .from(".hero-iso", { ...UNPLOTTED, duration: 1.5, stagger: { each: 0.035, from: "random" } }, 0.55)
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
    <section ref={root} aria-label={`${story.stormName ?? "The storm"} over Ireland`} className="relative h-svh w-full overflow-hidden bg-navy-950">
      <canvas ref={glRef} className={noGL ? "hidden" : "absolute inset-0 h-full w-full"} aria-hidden="true" />
      <svg ref={svgRef} className="absolute inset-0 h-full w-full" preserveAspectRatio="xMidYMid slice" aria-hidden="true" style={{ ["--u" as string]: 0.03 } as CSSProperties}>
        <g className="hero-lines" fill="none" strokeLinecap="round" strokeLinejoin="round">
          <path className="hero-grat" d={GRATICULE} stroke="#85919f" strokeOpacity={0.2} style={{ strokeWidth: u(1) }} {...PLOTTED} />
          <path className="hero-land" d={COAST} stroke="#dfe4eb" strokeOpacity={0.85} style={{ strokeWidth: u(1.1) }} {...PLOTTED} />
          {chart.isobars.map((b, i) => (
            <path key={i} className="hero-iso" d={b.d} stroke="#f4f6f9" strokeOpacity={b.hpa % 20 === 0 ? 0.95 : 0.58} style={{ strokeWidth: u(b.hpa % 20 === 0 ? 1.9 : 1.1) }} {...PLOTTED} />
          ))}
        </g>
        {[
          { c: chart.low, letter: "L", fill: "#f4f6f9" },
          { c: chart.high, letter: "H", fill: "#a5b0bf" },
        ].map(({ c, letter, fill }) => (
          <g key={letter} className="hero-centre" transform={`translate(${c.pt[0]} ${c.pt[1]})`}>
            <text textAnchor="middle" dominantBaseline="central" fill={fill} style={{ fontSize: u(44), fontWeight: 700, fontStretch: "118%" }}>
              {letter}
            </text>
            <text textAnchor="middle" fill={fill} className="font-mono" style={{ fontSize: u(13), transform: `translateY(${u(38)})` }}>
              {c.hpa}
            </text>
          </g>
        ))}
        <g fill="none">
          {arcs.map((a) => (
            <path key={a.iata} className="hero-arc" d={a.d} stroke="#f4f6f9" strokeOpacity={0.85} style={{ strokeWidth: u(1.3) }} {...PLOTTED} strokeDashoffset={still ? 0 : 1.01} />
          ))}
        </g>
        {arcs.map((a) => (
          <g key={a.iata} className="hero-arc-label" transform={`translate(${a.pt[0]} ${a.pt[1]})`} style={{ opacity: still ? 1 : 0 }}>
            <circle fill="#f4f6f9" style={{ r: u(2.6) } as CSSProperties} />
            <text fill="#c8d0db" className="font-mono" style={{ fontSize: u(11.5), transform: `translate(${u(7)}, ${u(-7)})` }}>
              {a.iata}
            </text>
          </g>
        ))}
        <g className="hero-hub" transform={`translate(${hubPt[0]} ${hubPt[1]})`}>
          <circle fill="#4f9fe0" style={{ r: u(4.5) } as CSSProperties} />
          <circle fill="none" stroke="#4f9fe0" strokeOpacity={0.6} style={{ r: u(11), strokeWidth: u(1) } as CSSProperties} />
          <text fill="#f4f6f9" className="font-mono" style={{ fontSize: u(12.5), transform: `translate(${u(15)}, ${u(4)})` }}>
            {station}
          </text>
        </g>
      </svg>
      <canvas ref={windRef} className="pointer-events-none absolute inset-0 h-full w-full" aria-hidden="true" />

      <div className="pointer-events-none absolute inset-x-0 top-0 h-40 bg-gradient-to-b from-navy-950/80 to-transparent" />
      <div className="pointer-events-none absolute inset-x-0 bottom-0 h-3/5 bg-gradient-to-t from-navy-950/95 via-navy-950/45 to-transparent" />

      {/* opening copy */}
      <div className="hero-copy absolute inset-x-0 bottom-0 px-5 pb-16 md:px-16 md:pb-20">
        <p className="micro text-cloud-400">
          {story.stormName ?? "Storm"} · Dublin · {longDate(era5.date)}
        </p>
        <h1 className="display mt-4 max-w-[12ch] text-[clamp(46px,8.4vw,148px)] text-cloud-50">Every storm leaves a bill.</h1>
        <p className="mt-6 max-w-[44ch] text-[16.5px] leading-relaxed text-cloud-300 md:text-[19px]">
          StormCheck works out what really caused each cancellation, drafts what every passenger is owed, and asks a person only about the 1%.
        </p>
      </div>
      <div className="hero-cue pointer-events-none absolute bottom-10 right-16 hidden items-center gap-3 text-[13px] text-cloud-400 md:flex">
        <span>Scroll</span>
        <span className="relative block h-10 w-px overflow-hidden bg-white/15">
          <span className="story-cue absolute inset-0 bg-cloud-200" />
        </span>
      </div>

      {/* the hour, as the airport reported it */}
      <div className="hero-hud pointer-events-none absolute inset-0">
        <div className="absolute -left-40 -top-40 h-[560px] w-[min(1100px,140vw)] bg-[radial-gradient(closest-side,rgba(8,13,23,0.82),rgba(8,13,23,0.5)_55%,transparent)]" aria-hidden="true" />
        <div className="absolute left-5 top-20 max-w-[min(680px,calc(100vw-40px))] md:left-16 md:top-24">
        <p className="figure text-[clamp(40px,5.2vw,76px)] font-medium leading-none text-cloud-50">{zulu(frameAt)}</p>
        <p className="mt-3 font-mono text-[12px] leading-relaxed text-cloud-300 md:text-[13px]">{obs ? obs.raw : <Pending ch={40} />}</p>
        <p className="mt-2 text-[14.5px] text-cloud-300">
          Dublin gusting{" "}
          {obs?.gust ? (
            <span className="figure text-cloud-50">{obs.gust} kt</span>
          ) : (
            <Pending ch={5} />
          )}{" "}
          · the low at <span className="figure text-cloud-50">{chart.low.hpa} hPa</span>
        </p>
        </div>
      </div>

      {/* pulled back: the network it grounded */}
      <div className="hero-end pointer-events-none absolute inset-x-0 bottom-0 px-5 pb-16 motion-reduce:hidden md:px-16 md:pb-20">
        <p className="display-tight max-w-[22ch] text-[clamp(28px,3.4vw,52px)] leading-[1.04] text-cloud-50">
          {counters?.cancelled !== undefined ? count(counters.cancelled) : <Pending ch={2} />} Northstar flights cancelled.{" "}
          <span className="text-cloud-400">{counters?.passengers !== undefined ? count(counters.passengers) : <Pending ch={4} />} passengers.</span>
        </p>
      </div>

      <p className="pointer-events-none absolute bottom-2 left-5 right-5 text-[10.5px] leading-snug text-cloud-500 md:left-auto md:right-16 md:text-right">
        {longDate(era5.date)} {zulu(frameAt)} · isobars every 4 hPa · ERA5 reanalysis (Copernicus/ECMWF) via Open-Meteo · NASA GIBS, MODIS Terra true colour
      </p>
    </section>
  );
}
