"use client";

import { useEffect, useMemo, useRef, useState } from "react";
import { area, line, curveMonotoneX } from "d3-shape";
import { scaleLinear } from "d3-scale";
import { METAR_HOURLY, STORM } from "@/data/scenario";

const toH = (s: string) => {
  const [h, m] = s.split(":").map(Number);
  return h + (m || 0) / 60;
};

export type TimelineMark = { t: string; kind: "fault" | "departure" | "operated" | "weather"; label?: string };

/**
 * Storm window as a shaded range, a fault as a single tick, departures as dots on a lane.
 * Grafana's convention for ranges vs moments; times in UTC.
 */
export function CauseTimeline({
  marks = [],
  height = 132,
  windowStart = STORM.windowStart,
  windowEnd = STORM.windowEnd,
  limit = STORM.limitKt,
  series = METAR_HOURLY,
  compact = false,
}: {
  marks?: TimelineMark[];
  height?: number;
  windowStart?: string | null;
  windowEnd?: string | null;
  limit?: number;
  series?: { h: number; kt: number; gust: number }[];
  compact?: boolean;
}) {
  // Drawn at its real pixel width, so labels stay their stated size on a phone and on a wide screen.
  const wrap = useRef<HTMLDivElement>(null);
  const [W, setW] = useState(760);
  useEffect(() => {
    const el = wrap.current;
    if (!el) return;
    const ro = new ResizeObserver(([e]) => setW(Math.max(240, Math.round(e.contentRect.width))));
    ro.observe(el);
    return () => ro.disconnect();
  }, []);
  const narrow = W < 440;
  const H = height;
  const M = { l: 8, r: 8, t: 22, b: compact ? 26 : 40 };
  const g = useMemo(() => {
    const x = scaleLinear().domain([0, 24]).range([M.l, W - M.r]);
    const max = Math.max(60, ...series.map((s) => s.gust || s.kt)) + 6;
    const y = scaleLinear().domain([0, max]).range([H - M.b - (compact ? 4 : 18), M.t]);
    const pts = series.map((s) => ({ h: s.h, v: s.gust || s.kt }));
    return {
      x,
      y,
      gust: line<{ h: number; v: number }>().x((d) => x(d.h)).y((d) => y(d.v)).curve(curveMonotoneX)(pts) ?? "",
      fill: area<{ h: number; v: number }>().x((d) => x(d.h)).y0(y(0)).y1((d) => y(d.v)).curve(curveMonotoneX)(pts) ?? "",
    };
  }, [series, W, H, M.b, M.l, M.r, M.t, compact]);
  const laneY = H - M.b + (compact ? 10 : 16);

  return (
    <div ref={wrap}>
      <svg viewBox={`0 0 ${W} ${H}`} className="w-full" role="img" aria-label={`Gusts through the day with the storm window ${windowStart ?? "none"} to ${windowEnd ?? ""}`}>
        {windowStart && windowEnd && (
          <g>
            <rect x={g.x(toH(windowStart))} y={M.t - 14} width={g.x(toH(windowEnd)) - g.x(toH(windowStart))} height={laneY - M.t + 14} rx="3" fill="#e9ebee" />
            <text x={(g.x(toH(windowStart)) + g.x(toH(windowEnd))) / 2} y={M.t - 3} textAnchor="middle" className="fill-[#5a6574] text-[11px]">
              {narrow ? "" : "Storm window "}
              {windowStart}–{windowEnd}Z
            </text>
          </g>
        )}
        <path d={g.fill} fill="#121417" fillOpacity="0.05" />
        <path d={g.gust} fill="none" stroke="#121417" strokeWidth="1.8" />
        <line x1={M.l} x2={W - M.r} y1={g.y(limit)} y2={g.y(limit)} stroke="#e89a00" strokeDasharray="5 4" strokeWidth="1.2" />
        <text x={W - M.r} y={g.y(limit) - 5} textAnchor="end" className="fill-[#8a5a00] font-mono text-[10px]">
          {limit} KT
        </text>
        <line x1={M.l} x2={W - M.r} y1={laneY} y2={laneY} stroke="#deded8" />
        {!compact &&
          [0, 6, 12, 18, 24].map((h) => (
            <text key={h} x={g.x(h)} y={H - 6} textAnchor={h === 0 ? "start" : h === 24 ? "end" : "middle"} className="fill-[#5a6068] font-mono text-[10.5px]">
              {String(h).padStart(2, "0")}:00
            </text>
          ))}
        {marks.map((m, i) => {
          const cx = g.x(toH(m.t));
          if (m.kind === "fault")
            return (
              <g key={i}>
                <line x1={cx} x2={cx} y1={M.t - 14} y2={laneY} stroke="#e04a2f" strokeWidth="1.6" />
                <rect x={cx - 3} y={M.t - 16} width="6" height="6" fill="#e04a2f" />
                {m.label && (
                  <text x={cx + 7} y={M.t - 8} className="fill-[#c2381f] font-mono text-[10.5px]">
                    {narrow ? m.t : m.label}
                  </text>
                )}
              </g>
            );
          const fill = m.kind === "departure" ? "#e04a2f" : m.kind === "operated" ? "#2f7d5b" : "#7c8794";
          return (
            <g key={i}>
              <circle cx={cx} cy={laneY} r={m.kind === "departure" ? 6 : 4} fill={fill} stroke="white" strokeWidth="1.5" />
              {m.label && (
                <text x={cx} y={laneY - 10} textAnchor="middle" className="font-mono text-[10.5px]" fill={m.kind === "departure" ? "#c2381f" : "#5a6068"}>
                  {m.label}
                </text>
              )}
            </g>
          );
        })}
      </svg>
    </div>
  );
}
