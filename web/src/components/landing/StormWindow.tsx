"use client";

import { useMemo, useRef } from "react";
import { line, curveMonotoneX, area } from "d3-shape";
import { scaleLinear } from "d3-scale";
import { FLIGHTS, METAR_HOURLY, NS31, STORM, fmtDuration } from "@/data/scenario";
import { windBarb } from "@/lib/drawings/meteo";
import { gsap, useGSAP } from "@/components/motion/gsap";

const W = 1200;
const H = 460;
const M = { l: 64, r: 40, t: 86, b: 120 };
const toH = (s: string) => {
  const [h, m] = s.split(":").map(Number);
  return h + m / 60;
};

/** 24 hours at EIDW: the storm window is a fact computed from METAR, not a cause code. */
export function StormWindow({ pinned = true }: { pinned?: boolean }) {
  const root = useRef<HTMLDivElement>(null);

  const g = useMemo(() => {
    const x = scaleLinear().domain([0, 24]).range([M.l, W - M.r]);
    const y = scaleLinear().domain([0, 75]).range([H - M.b, M.t]);
    const pts = METAR_HOURLY.map((m) => ({ h: m.h, gust: m.gust || m.kt, kt: m.kt }));
    pts.push({ h: 24, gust: 22, kt: 13 });
    const gust = line<{ h: number; gust: number }>().x((d) => x(d.h)).y((d) => y(d.gust)).curve(curveMonotoneX)(pts) ?? "";
    const mean = line<{ h: number; kt: number }>().x((d) => x(d.h)).y((d) => y(d.kt)).curve(curveMonotoneX)(pts) ?? "";
    const fill = area<{ h: number; gust: number }>().x((d) => x(d.h)).y0(y(0)).y1((d) => y(d.gust)).curve(curveMonotoneX)(pts) ?? "";
    const barbs = METAR_HOURLY.filter((m) => m.h % 2 === 0).map((m) => ({ h: m.h, ...windBarb(x(m.h), 6, m.dir, m.kt, 22) }));
    return { x, y, gust, mean, fill, barbs };
  }, []);

  const ws = toH(STORM.windowStart);
  const we = toH(STORM.windowEnd);
  const laneY = H - M.b + 46;

  useGSAP(
    () => {
      const mm = gsap.matchMedia();
      mm.add({ phone: "(max-width: 767px)", wide: "(min-width: 768px)" }, (ctx) => {
        const phone = !!ctx.conditions?.phone;
        const tl = gsap.timeline({
          defaults: { ease: "none" },
          scrollTrigger: pinned
            ? { trigger: root.current, start: "top top", end: phone ? "+=160%" : "+=110%", scrub: 0.6, pin: true, anticipatePin: 1, refreshPriority: 2, invalidateOnRefresh: true }
            : { trigger: root.current, start: "top 65%", toggleActions: "play none none reverse" },
        });
        // The limit is set first; then the day's gusts are drawn against it.
        tl.from(".sw-axis", { opacity: 0, duration: 0.3 })
          .from(".sw-barb", { opacity: 0, y: -6, stagger: 0.04, duration: 0.3 }, "<")
          .from(".sw-limit", { scaleX: 0, transformOrigin: "left center", duration: 0.7 }, "-=0.2")
          .from(".sw-limit-label", { opacity: 0, duration: 0.3 }, "<0.1")
          .addLabel("gust")
          .from(".sw-gust", { drawSVG: "0%", duration: 1.6, ease: "power1.inOut" })
          .from(".sw-mean", { drawSVG: "0%", duration: 1.6, ease: "power1.inOut" }, "<0.1")
          .from(".sw-fill", { opacity: 0, duration: 0.8 }, "<0.6")
          .from(".sw-window", { scaleX: 0, transformOrigin: "left center", duration: 0.8, ease: "power2.inOut" })
          .from(".sw-window-label", { opacity: 0, y: 6, duration: 0.4 }, "-=0.2")
          .from(".sw-lane", { opacity: 0, duration: 0.3 })
          .from(".sw-flight", { opacity: 0, y: -18, stagger: 0.05, duration: 0.35, ease: "back.out(2)" })
          .to(".sw-flight-wx", { fill: "#7c8794", stroke: "#7c8794", duration: 0.4, stagger: 0.02 })
          .addLabel("ns31")
          .from(".sw-ns31", { opacity: 0, scale: 0.4, transformOrigin: "center", duration: 0.4, ease: "back.out(3)" })
          .addLabel("fault")
          .from(".sw-fault", { scaleY: 0, transformOrigin: "50% 100%", duration: 0.7, ease: "power2.inOut" })
          .from(".sw-fault-label", { opacity: 0, x: -8, duration: 0.4 })
          .from(".sw-margin", { scaleX: 0, transformOrigin: "left center", duration: 0.7, ease: "power2.inOut" })
          .from(".sw-margin-label", { opacity: 0, duration: 0.4 })
          .to({}, { duration: 0.6 });

        if (phone) {
          // On a phone the chart stays readable at 1000 px and the scroll pans across it like a camera:
          // along the gust line into the storm window, out to NS31, then back to the fault and its margin.
          const track = root.current?.querySelector<HTMLElement>(".sw-track");
          const pan = (hour: number) => () => {
            const view = root.current?.clientWidth ?? 0;
            const wide = track?.scrollWidth ?? W;
            return gsap.utils.clamp(view - wide, 0, view / 2 - (wide / W) * g.x(hour));
          };
          tl.shiftChildren(0.8, true, tl.labels.fault); // hold on NS31 before swinging back to the fault
          tl.fromTo(".sw-track", { x: 0 }, { x: pan((ws + we) / 2), duration: 2.6, ease: "power1.inOut" }, "gust+=0.3")
            .to(".sw-track", { x: pan(18.4), duration: 0.6, ease: "power2.inOut" }, "ns31-=0.4")
            .to(".sw-track", { x: pan(10.6), duration: 0.9, ease: "power2.inOut" }, "fault");
        }
      });
    },
    { scope: root },
  );

  const { x, y } = g;
  const faultX = x(toH(NS31.techLog.time));
  const ns31X = x(toH(NS31.flight.sched));

  return (
    <div ref={root} className="relative -mx-5 flex min-h-svh flex-col justify-center overflow-hidden py-16 md:mx-0 md:overflow-visible">
      <div className="sw-track w-max md:w-full">
        <svg viewBox={`0 0 ${W} ${H}`} className="w-[1000px] max-w-none overflow-visible md:w-full" role="img" aria-label={`Gusts at Dublin through the day: at or above ${STORM.limitKt} knots from ${STORM.windowStart} to ${STORM.windowEnd}. NS31 was due at 21:30, after the window; its aircraft was grounded at 07:55.`}>
          <defs>
            <pattern id="sw-hatch" width="8" height="8" patternUnits="userSpaceOnUse" patternTransform="rotate(45)">
              <line x1="0" y1="0" x2="0" y2="8" stroke="#8e9aa8" strokeWidth="1" strokeOpacity="0.35" />
            </pattern>
            <linearGradient id="sw-gfill" x1="0" x2="0" y1="0" y2="1">
              <stop offset="0" stopColor="#eef1f4" stopOpacity="0.16" />
              <stop offset="1" stopColor="#eef1f4" stopOpacity="0" />
            </linearGradient>
          </defs>

          {/* storm window band */}
          <g className="sw-window" style={{ transformBox: "fill-box" }}>
            <rect x={x(ws)} y={M.t - 18} width={x(we) - x(ws)} height={H - M.b - M.t + 18} fill="url(#sw-hatch)" />
            <rect x={x(ws)} y={M.t - 18} width={x(we) - x(ws)} height={H - M.b - M.t + 18} fill="#8e9aa8" fillOpacity="0.06" />
          </g>
          <g className="sw-window-label">
            <text x={x(ws) + 10} y={M.t + 2} className="fill-[#cfd8e2] text-[14px]">
              Storm window {STORM.windowStart}–{STORM.windowEnd}Z, from METAR
            </text>
          </g>

          {/* axes */}
          <g className="sw-axis">
            <line x1={M.l} x2={W - M.r} y1={y(0)} y2={y(0)} stroke="#3a4350" />
            {Array.from({ length: 13 }, (_, i) => i * 2).map((h) => (
              <g key={h}>
                <line x1={x(h)} x2={x(h)} y1={y(0)} y2={y(0) + 6} stroke="#3a4350" />
                <text x={x(h)} y={y(0) + 22} textAnchor="middle" className="fill-[#8e9aa8] font-mono text-[12px]">
                  {String(h).padStart(2, "0")}:00
                </text>
              </g>
            ))}
            {[20, 40, 60].map((v) => (
              <text key={v} x={M.l - 12} y={y(v) + 4} textAnchor="end" className="fill-[#8e9aa8] font-mono text-[11px]">
                {v}
              </text>
            ))}
            <text x={M.l - 12} y={M.t - 4} textAnchor="end" className="fill-[#8e9aa8] text-[11px]">
              kt
            </text>
          </g>

          {/* barbs */}
          {g.barbs.map((b) => (
            <g key={b.h} className="sw-barb" transform={`translate(0 ${-6})`}>
              <path d={`${b.staff} ${b.feathers}`} stroke="#a9b4c0" strokeWidth="1.4" strokeLinecap="round" fill="none" />
              <path d={b.pennants} fill="#a9b4c0" />
            </g>
          ))}

          <path className="sw-fill" d={g.fill} fill="url(#sw-gfill)" />
          <path className="sw-mean" d={g.mean} fill="none" stroke="#8e9aa8" strokeWidth="1.5" strokeDasharray="1 0" />
          <path className="sw-gust" d={g.gust} fill="none" stroke="#eef1f4" strokeWidth="2.4" strokeLinecap="round" />

          <line className="sw-limit" style={{ transformBox: "fill-box" }} x1={M.l} x2={W - M.r} y1={y(STORM.limitKt)} y2={y(STORM.limitKt)} stroke="#e89a00" strokeWidth="1.4" strokeDasharray="6 5" />
          {/* labelled at the start of the line, where the night's gusts are far below it */}
        <text x={M.l + 6} y={y(STORM.limitKt) - 8} className="sw-limit-label fill-[#e89a00] text-[13px]">
            Gust limit {STORM.limitKt} kt
          </text>

          {/* departures lane */}
          <g className="sw-lane">
            <line x1={M.l} x2={W - M.r} y1={laneY} y2={laneY} stroke="#2a313c" />
            <text x={M.l} y={laneY + 32} className="fill-[#8e9aa8] text-[13px]">
              Cancelled departures
            </text>
          </g>
          {FLIGHTS.filter((f) => f.verdict !== "technical").map((f) => (
            <g key={f.id} className="sw-flight">
              <circle className="sw-flight-wx" cx={x(toH(f.sched))} cy={laneY} r="6" fill="#eef1f4" stroke="#eef1f4" />
            </g>
          ))}

          {/* NS31 and its fault */}
          <g className="sw-ns31">
            <circle cx={ns31X} cy={laneY} r="9" fill="#e04a2f" />
            <circle cx={ns31X} cy={laneY} r="16" fill="none" stroke="#e04a2f" strokeOpacity="0.5" />
            <text x={ns31X} y={laneY + 36} textAnchor="middle" className="fill-[#ff7a5c] font-mono text-[13px]">
              NS31 · {NS31.flight.sched}
            </text>
          </g>
          <path className="sw-fault" style={{ transformBox: "fill-box" }} d={`M${faultX},${laneY} L${faultX},${M.t - 10}`} stroke="#e04a2f" strokeWidth="1.6" strokeDasharray="3 4" />
          <g className="sw-fault-label">
            <rect x={faultX + 10} y={M.t - 4} width="244" height="48" rx="3" fill="#1d1210" stroke="#e04a2f" strokeOpacity="0.6" />
            <text x={faultX + 22} y={M.t + 15} className="fill-[#ff7a5c] font-mono text-[12px] tracking-[0.04em]">
              {NS31.techLog.time} TECH LOG · ATA {NS31.techLog.ata}
            </text>
            <text x={faultX + 22} y={M.t + 33} className="fill-[#eef1f4] font-mono text-[12px]">
              HYD G LEAK · {NS31.flight.reg} U/S
            </text>
          </g>
          <g className="sw-margin" style={{ transformBox: "fill-box" }}>
            <line x1={faultX} x2={x(ws)} y1={laneY + 13} y2={laneY + 13} stroke="#ff7a5c" strokeWidth="1.2" />
            <line x1={faultX} x2={faultX} y1={laneY + 9} y2={laneY + 17} stroke="#ff7a5c" />
            <line x1={x(ws)} x2={x(ws)} y1={laneY + 9} y2={laneY + 17} stroke="#ff7a5c" />
          </g>
          <text className="sw-margin-label fill-[#ff7a5c] text-[13px]" x={(faultX + x(ws)) / 2} y={laneY + 32} textAnchor="middle">
            {fmtDuration(NS31.marginMin)} before the storm
          </text>
        </svg>
      </div>
    </div>
  );
}
