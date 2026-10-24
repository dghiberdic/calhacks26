"use client";

import { useEffect, useMemo, useRef, useState } from "react";
import { line, curveMonotoneX, area } from "d3-shape";
import { scaleLinear } from "d3-scale";
import { LAND_ATLANTIC } from "@/data/geo/land";
import { AIRPORTS, K, toMap } from "@/lib/geo";
import { FLIGHTS, METAR_HOURLY, NS31, OPERATED, STORM, fmtDuration, metarAt } from "@/data/scenario";
import { gsap } from "@/components/motion/gsap";
import { SatelliteLayer } from "@/components/landing/hero/SatelliteLayer";
import { Logo } from "@/components/ui/Logo";

const toH = (s: string) => Number(s.slice(0, 2)) + Number(s.slice(3, 5)) / 60;
const DUB = toMap(AIRPORTS.DUB.lon, AIRPORTS.DUB.lat);

/**
 * The 20-second moment from FINAL_IDEA.md, as a self-playing film for the Devpost video.
 * Space pauses, R restarts. Record at 1920×1080.
 */
export function MomentFilm() {
  const root = useRef<HTMLDivElement>(null);
  const glRef = useRef<HTMLCanvasElement>(null);
  const tl = useRef<gsap.core.Timeline | null>(null);
  const [ready, setReady] = useState(false);
  const owed = useRef<HTMLSpanElement>(null);
  const prov = useRef<HTMLSpanElement>(null);

  // timeline chart geometry
  const chart = useMemo(() => {
    const W = 1600;
    const H = 300;
    const x = scaleLinear().domain([0, 24]).range([40, W - 40]);
    const y = scaleLinear().domain([0, 60]).range([H - 70, 20]);
    const pts = METAR_HOURLY.map((m) => ({ h: m.h, g: m.gust || m.kt }));
    pts.push({ h: 24, g: pts[pts.length - 1].g });
    return {
      W,
      H,
      x,
      y,
      gust: line<{ h: number; g: number }>().x((d) => x(d.h)).y((d) => y(d.g)).curve(curveMonotoneX)(pts) ?? "",
      fill: area<{ h: number; g: number }>().x((d) => x(d.h)).y0(y(0)).y1((d) => y(d.g)).curve(curveMonotoneX)(pts) ?? "",
      lane: H - 38,
    };
  }, []);

  useEffect(() => {
    if (!glRef.current || !root.current) return;
    let alive = true;
    let sat: SatelliteLayer | null = null;
    let tick: (() => void) | null = null;
    let size: (() => void) | null = null;
    const view = { cx: -8.2 * K, cy: -53.4, w: 22 * K };
    fetch("/data/bram/frames.json")
      .then((r) => r.json())
      .then((fr) => {
        if (!alive || !glRef.current || !root.current) return;
        const b = fr.bbox;
        const layer = new SatelliteLayer({ canvas: glRef.current, image: "/data/bram/true-1200.webp", satBox: [b.lonMin * K, -b.latMax, b.lonMax * K, -b.latMin], origin: DUB });
        sat = layer;
        layer.reveal = 1;
        layer.dim = 0.15;
        const el = root.current;
        size = () => layer.setSize(el.clientWidth, el.clientHeight);
        size();
        window.addEventListener("resize", size);
        tick = () => {
          const W = el.clientWidth;
          const H = el.clientHeight;
          const h = view.w * (H / W);
          layer.render([view.cx - view.w / 2, view.cy - h / 2, view.cx + view.w / 2, view.cy + h / 2], performance.now() / 1000);
          const svg = el.querySelector<SVGSVGElement>(".mf-map");
          svg?.setAttribute("viewBox", `${view.cx - view.w / 2} ${view.cy - h / 2} ${view.w} ${h}`);
          svg?.style.setProperty("--u", String(view.w / W));
        };
        gsap.ticker.add(tick);
        // slow push-in on Dublin over the whole film
        gsap.to(view, { w: 15 * K, cx: -7 * K, cy: -53.5, duration: 20, ease: "none" });
        layer.ready.then(() => alive && setReady(true));
      });
    return () => {
      alive = false;
      if (tick) gsap.ticker.remove(tick);
      if (size) window.removeEventListener("resize", size);
      gsap.killTweensOf(view);
      sat?.dispose();
    };
  }, []);

  useEffect(() => {
    if (!ready || !root.current) return;
    const q = gsap.utils.selector(root);
    const t = gsap.timeline({ paused: true, defaults: { ease: "power3.out" } });
    const counter = { owed: 0, prov: 0 };
    const paint = () => {
      if (owed.current) owed.current.textContent = `€${Math.round(counter.owed).toLocaleString("en-IE")}`;
      if (prov.current) prov.current.textContent = `€${Math.round(counter.prov).toLocaleString("en-IE")}`;
    };
    paint();
    t.set(q(".mf-scene"), { autoAlpha: 0 })
      // 0–4s: the storm, the codes
      .to(q(".mf-s1"), { autoAlpha: 1, duration: 0.6 }, 0.2)
      .from(q(".mf-s1 .mf-line"), { yPercent: 110, duration: 0.9, stagger: 0.5 }, 0.3)
      .to(q(".mf-owed"), { autoAlpha: 1, duration: 0.5 }, 1.2)
      // 4–9s: METAR window, 13 flights go grey
      .to(q(".mf-s1"), { autoAlpha: 0, duration: 0.4 }, 4.0)
      .to(q(".mf-chart"), { autoAlpha: 1, duration: 0.5 }, 4.0)
      .fromTo(q(".mf-gust"), { drawSVG: 0 }, { drawSVG: "100%", duration: 1.6, ease: "power1.inOut" }, 4.1)
      .fromTo(q(".mf-window"), { scaleX: 0 }, { scaleX: 1, transformOrigin: "left center", duration: 0.9, ease: "power2.inOut" }, 5.2)
      .to(q(".mf-s2"), { autoAlpha: 1, duration: 0.5 }, 5.3)
      .from(q(".mf-dot"), { y: -40, autoAlpha: 0, stagger: 0.07, duration: 0.45, ease: "back.out(2)" }, 6.0)
      .to(q(".mf-dot-wx"), { fill: "#7c8794", duration: 0.5, stagger: 0.03 }, 7.4)
      // 9–14s: NS31 after the storm; the tech log
      .to(q(".mf-s2"), { autoAlpha: 0, duration: 0.4 }, 9.0)
      .from(q(".mf-op"), { autoAlpha: 0, y: -20, stagger: 0.12, duration: 0.4 }, 9.0)
      .from(q(".mf-ns31"), { autoAlpha: 0, scale: 0.3, transformOrigin: "center", duration: 0.5, ease: "back.out(3)" }, 9.2)
      .to(q(".mf-s3"), { autoAlpha: 1, duration: 0.5 }, 9.3)
      .to(q(".mf-s3"), { autoAlpha: 0, duration: 0.3 }, 10.6)
      .fromTo(q(".mf-fault"), { drawSVG: "100% 100%" }, { drawSVG: "0% 100%", duration: 0.6, ease: "power2.inOut" }, 10.8)
      .to(q(".mf-log"), { autoAlpha: 1, x: 0, duration: 0.6 }, 10.9)
      .to(q(".mf-plane, .mf-plane-shade"), { autoAlpha: 1, duration: 0.6 }, 12.0)
      .fromTo(q(".mf-plane"), { scale: 1.08 }, { scale: 1, duration: 2.4, ease: "power2.out" }, 12.0)
      .to(q(".mf-chart"), { autoAlpha: 0, duration: 0.4 }, 12.0)
      .to(q(".mf-verdict"), { autoAlpha: 1, duration: 0.4 }, 12.2)
      .to(q(".mf-owed-a"), { opacity: 0, duration: 0.3 }, 12.6)
      .to(q(".mf-owed-b"), { opacity: 1, duration: 0.3 }, 12.7)
      .from(q(".mf-verdict .mf-line"), { yPercent: 110, duration: 0.7, stagger: 0.25 }, 12.2)
      // 14–17s: the money
      .to(q(".mf-log, .mf-verdict, .mf-plane, .mf-plane-shade"), { autoAlpha: 0, duration: 0.5 }, 14.0)
      .to(q(".mf-s4"), { autoAlpha: 1, duration: 0.4 }, 14.1)
      .to(counter, { owed: NS31.exposure, duration: 1.1, ease: "power2.out", onUpdate: paint }, 14.2)
      .to(q(".mf-prov"), { autoAlpha: 1, y: 0, duration: 0.5 }, 15.3)
      .to(counter, { prov: NS31.provision, duration: 1.0, ease: "power2.out", onUpdate: paint }, 15.4)
      // 17–20s: held, and traced
      .to(q(".mf-s4"), { autoAlpha: 0, duration: 0.4 }, 17.0)
      .to(q(".mf-s5"), { autoAlpha: 1, duration: 0.4 }, 17.1)
      .fromTo(q(".mf-trace-line"), { scaleX: 0 }, { scaleX: 1, transformOrigin: "left center", duration: 1.6, ease: "power2.inOut" }, 17.5)
      .from(q(".mf-node"), { autoAlpha: 0, y: 10, stagger: 0.3, duration: 0.4 }, 17.6)
      .to(q(".mf-end"), { autoAlpha: 1, duration: 0.6 }, 19.6)
      .to({}, { duration: 1.2 });
    tl.current = t;
    if (process.env.NODE_ENV !== "production") Object.assign(window, { __film: t });
    const start = window.setTimeout(() => t.play(0), 600);
    const keys = (e: KeyboardEvent) => {
      if (e.code === "Space") (e.preventDefault(), t.paused() ? t.play() : t.pause());
      if (e.key.toLowerCase() === "r") {
        counter.owed = 0;
        counter.prov = 0;
        paint();
        t.restart();
      }
    };
    window.addEventListener("keydown", keys);
    return () => {
      window.clearTimeout(start);
      window.removeEventListener("keydown", keys);
      t.kill();
    };
  }, [ready]);

  const weather = FLIGHTS.filter((f) => f.verdict === "weather");
  const { x, y } = chart;
  const scene = "mf-scene pointer-events-none absolute invisible opacity-0";

  return (
    <div ref={root} className="relative h-svh w-full cursor-none overflow-hidden bg-night text-[#f4f6f8]">
      <canvas ref={glRef} className="absolute inset-0 h-full w-full" aria-hidden="true" />
      <svg className="mf-map absolute inset-0 h-full w-full" viewBox="-14 -60 14 10" preserveAspectRatio="xMidYMid slice" aria-hidden="true" style={{ ["--u" as string]: 0.01 }}>
        <path d={LAND_ATLANTIC} fill="none" stroke="#e8eef4" strokeOpacity="0.35" style={{ strokeWidth: "calc(var(--u) * 1.2)" }} />
        <g transform={`translate(${DUB[0]} ${DUB[1]})`}>
          <circle fill="#ff7a5c" style={{ r: "calc(var(--u) * 7px)" } as React.CSSProperties} />
          <circle fill="none" stroke="#ff7a5c" strokeOpacity="0.5" style={{ r: "calc(var(--u) * 18px)", strokeWidth: "calc(var(--u) * 1.2)" } as React.CSSProperties} />
        </g>
      </svg>
      <div className="absolute inset-0 bg-gradient-to-r from-night/85 via-night/40 to-night/10" />
      {/* eslint-disable-next-line @next/next/no-img-element */}
      <img src="/renders/ns31-side-render.webp" alt="" aria-hidden="true" className="mf-plane invisible absolute inset-0 h-full w-full object-cover opacity-0" />
      <div className="mf-plane-shade invisible absolute inset-0 bg-gradient-to-b from-night/70 via-transparent to-night/80 opacity-0" />

      <header className="absolute left-[5vw] top-[5vh] flex items-center gap-3 text-[clamp(14px,1.1vw,20px)]">
        <Logo className="h-[1.1em] w-auto" />
        <span className="font-semibold [font-stretch:112%]">StormCheck</span>
        <span className="ml-4 text-haze">Storm Bram · Dublin · 9 Dec 2025</span>
      </header>

      <div className="mf-owed invisible absolute right-[5vw] top-[5vh] text-right opacity-0">
        <p className="relative text-[clamp(13px,1vw,18px)] text-haze">
          <span className="mf-owed-a">Owed, per the cause codes</span>
          <span className="mf-owed-b absolute right-0 top-0 whitespace-nowrap text-[#ff9a80] opacity-0">Owed, per StormCheck</span>
        </p>
        <span ref={owed} className="display-tight block font-mono text-[clamp(40px,4.6vw,88px)] font-normal tracking-normal">
          €0
        </span>
      </div>

      {/* 1 */}
      <div className={`${scene} mf-s1 bottom-[22vh] left-[5vw]`}>
        <p className="overflow-hidden">
          <span className="mf-line display block text-[clamp(48px,6.4vw,124px)]">14 flights cancelled.</span>
        </p>
        <p className="overflow-hidden">
          <span className="mf-line display block text-[clamp(48px,6.4vw,124px)] text-haze">All coded weather.</span>
        </p>
      </div>

      {/* chart: 4–14s */}
      <div className={`${scene} mf-chart inset-x-[5vw] bottom-[6vh]`}>
        <svg viewBox={`0 0 ${chart.W} ${chart.H}`} className="w-full overflow-visible">
          <rect className="mf-window" style={{ transformBox: "fill-box" }} x={x(toH(STORM.windowStart))} y={8} width={x(toH(STORM.windowEnd)) - x(toH(STORM.windowStart))} height={chart.lane - 8} fill="#8e9aa8" fillOpacity="0.22" />
          <path d={chart.fill} fill="#ffffff" fillOpacity="0.05" />
          <path className="mf-gust" d={chart.gust} fill="none" stroke="#f4f6f8" strokeWidth="3" />
          <line x1={x(0)} x2={x(24)} y1={y(STORM.limitKt)} y2={y(STORM.limitKt)} stroke="#e89a00" strokeWidth="2" strokeDasharray="8 7" />
          <text x={x(24)} y={y(STORM.limitKt) - 10} textAnchor="end" className="fill-[#e89a00] text-[22px]">
            Gust limit {STORM.limitKt} kt
          </text>
          <line x1={x(0)} x2={x(24)} y1={chart.lane} y2={chart.lane} stroke="#3a4350" strokeWidth="2" />
          {[0, 6, 12, 18, 24].map((h) => (
            <text key={h} x={x(h)} y={chart.H} textAnchor="middle" className="fill-[#8e9aa8] font-mono text-[20px]">
              {String(h).padStart(2, "0")}:00
            </text>
          ))}
          {weather.map((f) => (
            <circle key={f.id} className="mf-dot mf-dot-wx" cx={x(toH(f.sched))} cy={chart.lane} r="11" fill="#f4f6f8" />
          ))}
          {OPERATED.map((o) => (
            <circle key={o.id} className="mf-op" cx={x(toH(o.sched))} cy={chart.lane} r="9" fill="#5fd08a" />
          ))}
          <g className="mf-ns31">
            <circle cx={x(21.5)} cy={chart.lane} r="15" fill="#e04a2f" />
            <text x={x(21.5)} y={chart.lane - 26} textAnchor="middle" className="fill-[#ff9a80] font-mono text-[22px]">
              NS31 21:30
            </text>
          </g>
          <path className="mf-fault" d={`M${x(toH("07:55"))},8 L${x(toH("07:55"))},${chart.lane}`} stroke="#ff7a5c" strokeWidth="3" />
        </svg>
      </div>

      <div className={`${scene} mf-s2 left-[5vw] top-[24vh] max-w-[34ch]`}>
        <p className="display-tight text-[clamp(30px,3vw,56px)] leading-tight">Real airport weather says the storm had a window.</p>
        <p className="mt-4 font-mono text-[clamp(14px,1vw,20px)] text-haze">{metarAt(STORM.peak.t).raw}</p>
      </div>

      <div className={`${scene} mf-s3 left-[5vw] top-[24vh] max-w-[30ch]`}>
        <p className="display-tight text-[clamp(30px,3vw,56px)] leading-tight">NS31 was due at 21:30, after it cleared. Every other evening flight left.</p>
      </div>

      <div className="mf-log invisible absolute left-[5vw] top-[22vh] max-w-[620px] -translate-x-4 rounded-xl border border-[#ff7a5c]/50 bg-[#1d1210]/85 p-[1.6vw] opacity-0 backdrop-blur">
        <p className="text-[clamp(13px,1vw,18px)] text-[#ff9a80]">Technical log, EI-NSA · ATA 29-11</p>
        <p className="mt-2 font-mono text-[clamp(16px,1.35vw,26px)] leading-snug">07:55Z {NS31.techLog.entry}</p>
      </div>

      <div className={`${scene} mf-verdict right-[5vw] top-[22vh] text-right`}>
        <p className="overflow-hidden">
          <span className="mf-line display block text-[clamp(48px,6vw,116px)]">Not weather.</span>
        </p>
        <p className="overflow-hidden">
          <span className="mf-line display block text-[clamp(48px,6vw,116px)] text-[#ff7a5c]">Broken plane.</span>
        </p>
      </div>

      {/* 4: the money */}
      <div className={`${scene} mf-s4 left-[5vw] top-[22vh]`}>
        <p className="font-mono text-[clamp(28px,2.6vw,52px)] text-haze">212 × €600 =</p>
        <span className="display-tight mt-2 block font-mono text-[clamp(56px,6.4vw,124px)] font-normal tracking-normal text-[#f4f6f8]">€127,200</span>
        <p className="mt-2 text-[clamp(15px,1.2vw,22px)] text-haze">if every passenger claims</p>
        <div className="mf-prov mt-[5vh] translate-y-4 opacity-0">
          <p className="text-[clamp(15px,1.2vw,22px)] text-haze">Provision at the learned 35% claim rate</p>
          <span ref={prov} className="display-tight block font-mono text-[clamp(64px,7.4vw,148px)] font-normal tracking-normal text-[#ff7a5c]">
            €0
          </span>
          <p className="mt-2 inline-flex rounded-full bg-white/10 px-4 py-2 text-[clamp(13px,1vw,18px)]">
            Confidence 91% · fault logged {fmtDuration(NS31.marginMin)} before the storm
          </p>
        </div>
      </div>

      {/* 5: held + traced */}
      <div className={`${scene} mf-s5 inset-x-[5vw] top-[24vh]`}>
        <p className="display-tight max-w-[22ch] text-[clamp(34px,3.6vw,68px)] leading-tight">212 payouts drafted, held for the Claims Lead.</p>
        <div className="relative mt-[8vh]">
          <span className="mf-trace-line absolute left-0 right-0 top-[18px] h-[2px] bg-[#f4f6f8]" />
          <ol className="relative grid grid-cols-5 gap-4">
            {[
              ["€44,520", "Provision"],
              ["07:55Z", "Tech log line"],
              ["21:30Z", "METAR at departure"],
              ["C-549/07", "Wallentin-Hermann"],
              ["Legal", "Ruled once"],
            ].map(([v, l], i) => (
              <li key={v} className="mf-node">
                <span className={`block h-[38px] w-[38px] rounded-full border-[3px] ${i === 0 ? "border-[#ff7a5c] bg-[#ff7a5c]" : "border-[#f4f6f8] bg-night"}`} />
                <p className={`mt-4 font-mono text-[clamp(18px,1.6vw,30px)] ${i === 0 ? "text-[#ff9a80]" : ""}`}>{v}</p>
                <p className="text-[clamp(13px,1vw,18px)] text-haze">{l}</p>
              </li>
            ))}
          </ol>
        </div>
      </div>

      <div className="mf-end invisible absolute bottom-[6vh] right-[5vw] text-right opacity-0">
        <p className="text-[clamp(14px,1.1vw,20px)] text-haze">The disruption-liability seat.</p>
        <p className="display-tight text-[clamp(26px,2.2vw,42px)]">It drafts. It never pays.</p>
      </div>
    </div>
  );
}
