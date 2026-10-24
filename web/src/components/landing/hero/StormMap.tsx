"use client";

import { useEffect, useMemo, useRef, useState } from "react";
import { LAND_ATLANTIC } from "@/data/geo/land";
import { GRATICULE } from "@/data/geo/coast";
import { AIRPORTS, K, greatCircle, pathOf, toMap, type View } from "@/lib/geo";
import { gsap, ScrollTrigger, useGSAP } from "@/components/motion/gsap";
import { SatelliteLayer } from "./SatelliteLayer";
import { WindParticles, type WindGrid } from "./WindParticles";
import { buildIsobars, type StormJSON } from "./synoptic";

type SatJSON = { bbox: { lonMin: number; lonMax: number; latMin: number; latMax: number } };

const ROUTES = ["BOS", "JFK", "EWR", "ORD", "IAD", "PHL", "YYZ", "MCO", "SEA"] as const;

const DUB = toMap(AIRPORTS.DUB.lon, AIRPORTS.DUB.lat);

export function StormMap({ date = "2025-01-24", frameH = 12 }: { date?: string; frameH?: number }) {
  const root = useRef<HTMLDivElement>(null);
  const svgRef = useRef<SVGSVGElement>(null);
  const glRef = useRef<HTMLCanvasElement>(null);
  const pRef = useRef<HTMLCanvasElement>(null);
  const [storm, setStorm] = useState<StormJSON | null>(null);
  const [sat, setSat] = useState<SatJSON | null>(null);
  const view = useRef<View>({ cx: -16 * K, cy: -56.5, w: 52 * K });
  const layers = useRef<{ sat?: SatelliteLayer; wind?: WindParticles }>({});
  const state = useRef({ reveal: 0, particles: 0, lines: 1 });

  useEffect(() => {
    let alive = true;
    Promise.all([fetch(`/data/storm-${date}.json`).then((r) => r.json()), fetch(`/data/sat-${date}.json`).then((r) => r.json())]).then(([s, m]) => {
      if (!alive) return;
      setStorm(s);
      setSat(m);
    });
    return () => {
      alive = false;
    };
  }, [date]);

  const chart = useMemo(() => (storm ? buildIsobars(storm, frameH) : null), [storm, frameH]);
  const arcs = useMemo(() => ROUTES.map((c) => ({ code: c, d: pathOf(greatCircle(AIRPORTS.DUB, AIRPORTS[c])) })), []);

  // Layers + render loop
  useEffect(() => {
    if (!storm || !sat || !chart || !glRef.current || !pRef.current || !root.current) return;
    const satBox: [number, number, number, number] = [sat.bbox.lonMin * K, -sat.bbox.latMax, sat.bbox.lonMax * K, -sat.bbox.latMin];
    const satLayer = new SatelliteLayer({ canvas: glRef.current, image: `/data/sat-${date}.jpg`, satBox, origin: chart.lo.pt });
    const grid: WindGrid = { nx: storm.nx, ny: storm.ny, lonMin: storm.bbox.lonMin, latMax: storm.bbox.latMax, step: storm.step, u: chart.wind.u, v: chart.wind.v };
    const wind = new WindParticles(pRef.current, grid);
    layers.current = { sat: satLayer, wind };

    const el = root.current;
    let W = 0;
    let H = 0;
    const resize = () => {
      W = el.clientWidth;
      H = el.clientHeight;
      satLayer.setSize(W, H);
      wind.setSize(W, H);
    };
    resize();
    const ro = new ResizeObserver(resize);
    ro.observe(el);

    let visible = true;
    const io = new IntersectionObserver(([e]) => (visible = e.isIntersecting));
    io.observe(el);

    let last = performance.now();
    let lastKey = "";
    const tick = () => {
      if (!visible) return;
      const now = performance.now();
      const dt = (now - last) / 1000;
      last = now;
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
      satLayer.reveal = state.current.reveal;
      satLayer.render(box, now / 1000);
      wind.alpha = state.current.particles;
      wind.frame(box, dt);
    };
    gsap.ticker.add(tick);
    satLayer.ready.then(() => ScrollTrigger.refresh());
    return () => {
      gsap.ticker.remove(tick);
      ro.disconnect();
      io.disconnect();
      satLayer.dispose();
      layers.current = {};
    };
  }, [storm, sat, chart, date]);

  // Scroll choreography exists from first paint so pin spacing is stable before data lands.
  useGSAP(
    () => {
      const s = gsap.timeline({
        scrollTrigger: { trigger: root.current, start: "top top", end: "+=140%", scrub: 0.8, pin: true, anticipatePin: 1, refreshPriority: 3 },
      });
      s.to(state.current, { reveal: 1, duration: 1, ease: "none" }, 0)
        .to(state.current, { particles: 0.3, duration: 0.5 }, 0.1)
        .to(".hm-lines", { opacity: 0.35, duration: 0.6 }, 0.2)
        .to(".hm-copy", { opacity: 0, y: -30, duration: 0.4 }, 0)
        .from(".hm-credit", { opacity: 0, y: 10, duration: 0.3 }, 0.55)
        .to(view.current, { cx: -38 * K, cy: -47, w: 96 * K, duration: 1, ease: "power2.inOut" }, 0.9)
        .from(".hm-arc", { drawSVG: 0, duration: 0.8, stagger: 0.05, ease: "power2.inOut" }, 1.1)
        .from(".hm-arc-label", { opacity: 0, duration: 0.3, stagger: 0.05 }, 1.5)
        .to(state.current, { particles: 0.18, duration: 0.6 }, 1.2)
        .to({}, { duration: 0.3 });
    },
    { scope: root },
  );

  // Intro plot once the chart exists.
  useGSAP(
    () => {
      if (!chart) return;
      const intro = gsap.timeline({ defaults: { ease: "plotter" } });
      intro
        .from(".hm-grat", { drawSVG: 0, duration: 1.4, ease: "power2.inOut" })
        .from(".hm-land", { drawSVG: 0, duration: 2.6 }, 0.2)
        .from(".hm-iso", { drawSVG: 0, duration: 1.5, stagger: { each: 0.06, from: "start" } }, 0.7)
        .from(".hm-low", { opacity: 0, scale: 0.6, transformOrigin: "center", duration: 0.6, ease: "back.out(2)" }, 1.4)
        .from(".hm-high", { opacity: 0, duration: 0.6 }, 1.8)
        .to(state.current, { particles: 1, duration: 1.6, ease: "power1.inOut" }, 1.6)
        .from(".hm-dub", { opacity: 0, scale: 0, transformOrigin: "center", duration: 0.5, ease: "back.out(3)" }, 2.2);
    },
    { scope: root, dependencies: [chart] },
  );

  const iso = chart?.isobars ?? [];
  return (
    <div ref={root} className="relative h-svh w-full overflow-hidden bg-night">
      <canvas ref={glRef} className="absolute inset-0 h-full w-full" aria-hidden="true" />
      <svg
        ref={svgRef}
        className="absolute inset-0 h-full w-full"
        viewBox="-30 -70 60 30"
        preserveAspectRatio="xMidYMid slice"
        aria-hidden="true"
        style={{ ["--u" as string]: 0.05 }}
      >
        <g className="hm-lines" fill="none" strokeLinecap="round" strokeLinejoin="round">
          <path className="hm-grat" d={GRATICULE} stroke="#8e9aa8" strokeOpacity="0.18" style={{ strokeWidth: "calc(var(--u) * 1)" }} />
          <path className="hm-land" d={LAND_ATLANTIC} stroke="#cfd8e2" strokeOpacity="0.8" style={{ strokeWidth: "calc(var(--u) * 1.1)" }} />
          {iso.map((b, i) => (
            <path
              key={i}
              className="hm-iso"
              d={b.d}
              stroke="#eef1f4"
              strokeOpacity={b.hpa % 20 === 0 ? 0.95 : 0.62}
              style={{ strokeWidth: `calc(var(--u) * ${b.hpa % 20 === 0 ? 1.9 : 1.1})` }}
            />
          ))}
        </g>
        {chart && (
          <>
            <g className="hm-low" transform={`translate(${chart.lo.pt[0]} ${chart.lo.pt[1]})`}>
              <text textAnchor="middle" dominantBaseline="central" fill="#ff7a5c" style={{ fontSize: "calc(var(--u) * 46px)", fontWeight: 700, fontFamily: "var(--font-archivo)" }}>
                L
              </text>
              <text textAnchor="middle" fill="#eef1f4" style={{ fontSize: "calc(var(--u) * 15px)", fontFamily: "var(--font-b612-mono)", transform: "translateY(calc(var(--u) * 40px))" }}>
                {chart.lo.v}
              </text>
            </g>
            <g className="hm-high" transform={`translate(${chart.hi.pt[0]} ${chart.hi.pt[1]})`}>
              <text textAnchor="middle" dominantBaseline="central" fill="#a9b4c0" style={{ fontSize: "calc(var(--u) * 40px)", fontWeight: 700, fontFamily: "var(--font-archivo)" }}>
                H
              </text>
              <text textAnchor="middle" fill="#a9b4c0" style={{ fontSize: "calc(var(--u) * 14px)", fontFamily: "var(--font-b612-mono)", transform: "translateY(calc(var(--u) * 36px))" }}>
                {chart.hi.v}
              </text>
            </g>
          </>
        )}
        <g fill="none">
          {arcs.map((a) => (
            <path key={a.code} className="hm-arc" d={a.d} stroke="#eef1f4" strokeOpacity="0.85" style={{ strokeWidth: "calc(var(--u) * 1.3)" }} />
          ))}
        </g>
        {arcs.map((a) => {
          const ap = AIRPORTS[a.code];
          const [x, y] = toMap(ap.lon, ap.lat);
          return (
            <g key={a.code} className="hm-arc-label" transform={`translate(${x} ${y})`}>
              <circle r="0.25" fill="#eef1f4" style={{ r: "calc(var(--u) * 3px)" } as React.CSSProperties} />
              <text fill="#cfd8e2" style={{ fontSize: "calc(var(--u) * 12px)", fontFamily: "var(--font-b612-mono)", transform: "translate(calc(var(--u) * 8px), calc(var(--u) * -8px))" }}>
                {a.code}
              </text>
            </g>
          );
        })}
        <g className="hm-dub" transform={`translate(${DUB[0]} ${DUB[1]})`}>
          <circle fill="#ff7a5c" style={{ r: "calc(var(--u) * 5px)" } as React.CSSProperties} />
          <circle fill="none" stroke="#ff7a5c" strokeOpacity="0.6" style={{ r: "calc(var(--u) * 12px)", strokeWidth: "calc(var(--u) * 1)" } as React.CSSProperties} />
          <text fill="#eef1f4" style={{ fontSize: "calc(var(--u) * 13px)", fontFamily: "var(--font-b612-mono)", transform: "translate(calc(var(--u) * 16px), calc(var(--u) * 4px))" }}>
            EIDW
          </text>
        </g>
      </svg>
      <canvas ref={pRef} className="pointer-events-none absolute inset-0 h-full w-full" aria-hidden="true" />

      {/* gradient behind the headline for contrast on the brightest frame */}
      <div className="pointer-events-none absolute inset-x-0 bottom-0 h-2/3 bg-gradient-to-t from-night/90 via-night/40 to-transparent" />

      <div className="hm-copy absolute inset-x-0 bottom-0 px-5 pb-14 md:px-16 md:pb-20">
        <h1 className="display max-w-[13ch] text-[clamp(52px,8.6vw,150px)] text-[#f4f6f8]">Every storm leaves a bill.</h1>
        <p className="mt-6 max-w-[46ch] text-[17px] leading-relaxed text-haze md:text-[19px]">
          StormCheck works out the real cause of every cancelled flight from the weather and the aircraft&rsquo;s own logs, then drafts what each passenger is owed by 9&nbsp;AM.
        </p>
      </div>

      <div className="hm-credit pointer-events-none absolute bottom-8 right-5 text-right text-[13px] leading-relaxed text-haze md:right-16">
        <p className="font-mono text-[#eef1f4]">24 Jan 2025 · 12:00Z</p>
        <p>Storm Éowyn. Pressure from ERA5 reanalysis,</p>
        <p>imagery from NASA MODIS Terra.</p>
      </div>
    </div>
  );
}
