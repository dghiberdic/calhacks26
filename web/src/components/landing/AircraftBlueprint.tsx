"use client";

import { useMemo, useRef } from "react";
import { sideView, topView, hydraulicRoutes, A321NEO } from "@/lib/drawings/aircraft";
import { NS31 } from "@/data/scenario";
import { gsap, useGSAP } from "@/components/motion/gsap";

const LINE = "#e8f0fa";

/**
 * The aircraft as evidence. A cyanotype drawing plots itself, the three hydraulic systems
 * are traced in, and the green system's engine-1 pump lights up with the 07:55 log entry.
 * When the Blender render is available it washes in over the drawing (same camera).
 */
export function AircraftBlueprint({ render }: { render?: { src: string; lines?: string } }) {
  const root = useRef<HTMLDivElement>(null);
  const side = useMemo(() => sideView(), []);
  const plan = useMemo(() => topView(), []);
  const hyd = useMemo(() => hydraulicRoutes(), []);

  useGSAP(
    () => {
      const mm = gsap.matchMedia();
      mm.add("(prefers-reduced-motion: no-preference)", () => {
        const tl = gsap.timeline({
          defaults: { ease: "plotter" },
          scrollTrigger: { trigger: root.current, start: "top top", end: "+=160%", scrub: 0.7, pin: true, anticipatePin: 1, refreshPriority: 1 },
        });
        tl.from(".bp-frame", { drawSVG: 0, duration: 0.5, ease: "power1.inOut" })
          .from(".bp-side-outline", { drawSVG: 0, duration: 1.4, stagger: 0.05 }, 0.2)
          .from(".bp-side-detail", { drawSVG: 0, opacity: 0, duration: 0.8, stagger: 0.04 }, 0.9)
          .from(".bp-dim", { opacity: 0, duration: 0.4, stagger: 0.1 }, 1.4)
          .from(".bp-plan-outline", { drawSVG: 0, duration: 1.2, stagger: 0.05 }, 1.6)
          .from(".bp-plan-detail", { opacity: 0, duration: 0.5 }, 2.3)
          .from(".bp-hyd-blue", { drawSVG: 0, duration: 0.8 }, 2.6)
          .from(".bp-hyd-yellow", { drawSVG: 0, duration: 0.8 }, 2.75)
          .from(".bp-hyd-green", { drawSVG: 0, duration: 0.8 }, 2.9)
          .from(".bp-legend", { opacity: 0, y: 8, duration: 0.4 }, 3.1)
          .to(".bp-hyd-blue, .bp-hyd-yellow", { opacity: 0.25, duration: 0.4 }, 3.6)
          .from(".bp-leak", { scale: 0, opacity: 0, transformOrigin: "50% 50%", duration: 0.4, ease: "back.out(3)" }, 3.7)
          .from(".bp-log", { opacity: 0, x: -16, duration: 0.5, ease: "power3.out" }, 3.9)
          .from(".bp-log-line", { opacity: 0, duration: 0.25, stagger: 0.12 }, 4.0);
        if (render) {
          tl.to(".bp-render", { clipPath: "inset(0% 0% 0% 0%)", duration: 1.2, ease: "power2.inOut" }, 4.6).to(".bp-side", { opacity: 0.0, duration: 0.6 }, 5.2);
        }
        tl.to({}, { duration: 0.4 });
      });
      gsap.to(".bp-leak-pulse", { scale: 2.4, opacity: 0, transformOrigin: "50% 50%", duration: 1.6, repeat: -1, ease: "power2.out" });
    },
    { scope: root },
  );

  const outline = (k: string) => k === "outline";
  return (
    <div ref={root} className="relative flex min-h-svh flex-col justify-center overflow-hidden bg-cyanotype py-12 text-blueprint-line">
      {/* drafting grid + grain */}
      <div
        className="pointer-events-none absolute inset-0 opacity-[0.22]"
        style={{
          backgroundImage:
            "linear-gradient(to right, rgba(232,240,250,0.16) 1px, transparent 1px), linear-gradient(to bottom, rgba(232,240,250,0.16) 1px, transparent 1px), linear-gradient(to right, rgba(232,240,250,0.07) 1px, transparent 1px), linear-gradient(to bottom, rgba(232,240,250,0.07) 1px, transparent 1px)",
          backgroundSize: "120px 120px, 120px 120px, 24px 24px, 24px 24px",
        }}
      />
      <svg className="pointer-events-none absolute inset-0 h-full w-full opacity-[0.18] mix-blend-overlay" aria-hidden="true">
        <filter id="bp-grain">
          <feTurbulence type="fractalNoise" baseFrequency="0.9" numOctaves="2" stitchTiles="stitch" />
          <feColorMatrix values="0 0 0 0 1  0 0 0 0 1  0 0 0 0 1  0 0 0 0.6 0" />
        </filter>
        <rect width="100%" height="100%" filter="url(#bp-grain)" />
      </svg>

      <div className="relative mx-auto grid w-full max-w-[1500px] grid-cols-1 gap-10 px-5 md:px-12 lg:grid-cols-[minmax(0,1fr)_380px]">
        <div className="relative">
          {/* side elevation */}
          <svg viewBox="-3 -13.4 53 15.6" className="bp-side w-full" role="img" aria-label="Side elevation of the Airbus A321neo EI-NSA, 44.51 metres long and 11.76 metres tall.">
            <rect className="bp-frame" x="-2.6" y="-13.1" width="52.2" height="15" fill="none" stroke={LINE} strokeOpacity="0.5" strokeWidth="0.04" />
            {side.map((s, i) => (
              <path
                key={i}
                className={outline(s.kind) ? "bp-side-outline" : "bp-side-detail"}
                d={s.d}
                fill="none"
                stroke={LINE}
                strokeWidth={outline(s.kind) ? 0.075 : 0.045}
                strokeOpacity={outline(s.kind) ? 1 : 0.7}
                strokeLinejoin="round"
                strokeLinecap="round"
              />
            ))}
            <g className="bp-dim" stroke={LINE} strokeWidth="0.03" fill="none" opacity="0.8">
              <path d="M0,0.6 L0,1.7 M44.51,0.6 L44.51,1.7 M0,1.35 L44.51,1.35" />
              <path d="M-0.25,1.6 L0.25,1.1 M44.26,1.6 L44.76,1.1" />
            </g>
            <text className="bp-dim" x="22.25" y="2.05" textAnchor="middle" fill={LINE} style={{ fontSize: 0.62, fontFamily: "var(--font-b612-mono)" }}>
              {A321NEO.length.toFixed(2)} m
            </text>
            <g className="bp-dim" stroke={LINE} strokeWidth="0.03" fill="none" opacity="0.8">
              <path d="M45.4,0 L46.9,0 M43.2,-11.76 L46.9,-11.76 M46.5,0 L46.5,-11.76" />
            </g>
            <text className="bp-dim" x="47.1" y="-5.7" fill={LINE} style={{ fontSize: 0.62, fontFamily: "var(--font-b612-mono)" }}>
              {A321NEO.height.toFixed(2)} m
            </text>
            <path d="M-2.4,0 L49.4,0" stroke={LINE} strokeOpacity="0.4" strokeWidth="0.03" strokeDasharray="0.5 0.3" className="bp-dim" />
          </svg>

          {/* plan view with hydraulic systems */}
          <svg viewBox="-2 -19.4 49 38.8" className="mx-auto mt-4 w-[78%]" role="img" aria-label="Plan view with the three hydraulic systems. The green system's engine-1 pump is marked as the leak.">
            {plan.map((s, i) => (
              <path
                key={i}
                className={outline(s.kind) ? "bp-plan-outline" : "bp-plan-detail"}
                d={s.d}
                fill="none"
                stroke={LINE}
                strokeWidth={outline(s.kind) ? 0.08 : 0.045}
                strokeOpacity={outline(s.kind) ? 0.95 : 0.55}
                strokeLinejoin="round"
              />
            ))}
            <path className="bp-hyd-blue" d={hyd.blue.d} fill="none" stroke="var(--color-hyd-blue)" strokeWidth="0.17" strokeLinecap="round" strokeLinejoin="round" />
            <path className="bp-hyd-yellow" d={hyd.yellow.d} fill="none" stroke="var(--color-hyd-yellow)" strokeWidth="0.17" strokeLinecap="round" strokeLinejoin="round" />
            <path className="bp-hyd-green" d={hyd.green.d} fill="none" stroke="var(--color-hyd-green)" strokeWidth="0.2" strokeLinecap="round" strokeLinejoin="round" />
            <g className="bp-leak">
              <circle className="bp-leak-pulse" cx={hyd.leak.x} cy={hyd.leak.y} r="0.9" fill="none" stroke="#ff7a5c" strokeWidth="0.12" />
              <circle cx={hyd.leak.x} cy={hyd.leak.y} r="0.55" fill="#ff7a5c" />
            </g>
          </svg>

          {render && (
            <div className="bp-render absolute inset-x-0 top-0" style={{ clipPath: "inset(0% 100% 0% 0%)" }}>
              {/* eslint-disable-next-line @next/next/no-img-element */}
              <img src={render.src} alt="Photoreal render of EI-NSA on the wet apron at Dublin at night." className="w-full" />
            </div>
          )}
        </div>

        <aside className="flex flex-col justify-center gap-8">
          <div>
            <h2 className="display text-[clamp(40px,4.4vw,72px)] text-white">Grounded at 07:55.</h2>
            <p className="mt-5 max-w-[34ch] text-[17px] leading-relaxed text-[#bfd3ea]">
              NS31&rsquo;s aircraft lost green-system hydraulic fluid at the engine&nbsp;1 pump, three hours before the wind reached Dublin. A technical fault isn&rsquo;t weather.
            </p>
          </div>
          <div className="bp-legend flex gap-5 text-[13px] text-[#bfd3ea]">
            <span className="flex items-center gap-2">
              <span className="h-[3px] w-5 rounded-full bg-hyd-green" />
              Green
            </span>
            <span className="flex items-center gap-2">
              <span className="h-[3px] w-5 rounded-full bg-hyd-blue" />
              Blue
            </span>
            <span className="flex items-center gap-2">
              <span className="h-[3px] w-5 rounded-full bg-hyd-yellow" />
              Yellow
            </span>
          </div>
          <figure className="bp-log rounded-md border border-[#e8f0fa]/25 bg-[#0e2d4d]/80 p-5 backdrop-blur-sm">
            <figcaption className="mb-3 flex justify-between text-[13px] text-[#bfd3ea]">
              <span>Technical log, {NS31.flight.reg}</span>
              <span className="font-mono">ATA {NS31.techLog.ata}</span>
            </figcaption>
            <div className="font-mono text-[14px] leading-[1.7] text-white">
              <p className="bp-log-line text-[#ff9a80]">{NS31.techLog.time}Z</p>
              <p className="bp-log-line">HYD G RSVR LO LVL.</p>
              <p className="bp-log-line">LEAK FOUND AT ENG 1 EDP</p>
              <p className="bp-log-line">CASE DRAIN LINE.</p>
              <p className="bp-log-line">A/C U/S PENDING PART.</p>
            </div>
          </figure>
        </aside>
      </div>
    </div>
  );
}
