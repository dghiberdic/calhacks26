"use client";

import { useMemo } from "react";
import { line as d3line, curveMonotoneX } from "d3-shape";
import { scaleLinear } from "d3-scale";

export type ClaimPoint = { month: number; actual: number };

/** Monthly close-outs for transatlantic storms: what was actually filed, against the curve. */
const DEFAULT_ACTUAL: ClaimPoint[] = [
  { month: 6, actual: 0.19 },
  { month: 12, actual: 0.31 },
  { month: 18, actual: 0.33 },
];

/**
 * Cumulative claims expected over 24 months, asymptotic toward the learned rate (R-6 v4).
 * Dots are what was actually filed at each month-end close.
 */
export function ClaimCurve({
  months = 24,
  rate = 0.35,
  k = 7,
  actual = DEFAULT_ACTUAL,
  height = 200,
}: {
  months?: number;
  rate?: number;
  k?: number;
  actual?: ClaimPoint[];
  height?: number;
}) {
  const W = 640;
  const H = height;
  const M = { l: 6, r: 40, t: 20, b: 26 };
  const expected = (t: number) => rate * (1 - Math.exp(-t / k));

  const g = useMemo(() => {
    const x = scaleLinear().domain([0, months]).range([M.l, W - M.r]);
    const y = scaleLinear().domain([0, rate * 1.2]).range([H - M.b, M.t]);
    const pts = Array.from({ length: months + 1 }, (_, t) => ({ t, v: expected(t) }));
    const path =
      d3line<{ t: number; v: number }>()
        .x((d) => x(d.t))
        .y((d) => y(d.v))
        .curve(curveMonotoneX)(pts) ?? "";
    return { x, y, path };
    // eslint-disable-next-line react-hooks/exhaustive-deps -- `expected` is derived from rate/k, already in deps
  }, [months, rate, k, H, M.b, M.l, M.r, M.t]);

  const ticks = [0, 6, 12, 18, 24].filter((m) => m <= months);

  return (
    <svg
      viewBox={`0 0 ${W} ${H}`}
      className="w-full"
      role="img"
      aria-label={`Cumulative claims modelled to approach ${Math.round(rate * 100)} percent by month ${months}. Actual filed: ${actual
        .map((p) => `${Math.round(p.actual * 100)} percent at month ${p.month}`)
        .join(", ")}.`}
    >
      <line x1={M.l} x2={W - M.r} y1={g.y(rate)} y2={g.y(rate)} stroke="#c9c9c2" strokeDasharray="5 4" strokeWidth="1.2" />
      <text x={W - M.r + 6} y={g.y(rate) + 3} className="fill-[#5a6068] font-mono text-[10.5px]">
        {Math.round(rate * 100)}%
      </text>
      <path d={g.path} fill="none" stroke="#121417" strokeWidth="1.8" />
      <line x1={M.l} x2={W - M.r} y1={H - M.b} y2={H - M.b} stroke="#deded8" />
      {ticks.map((m) => (
        <text key={m} x={g.x(m)} y={H - 7} textAnchor={m === 0 ? "start" : m === months ? "end" : "middle"} className="fill-[#5a6068] font-mono text-[10.5px]">
          {m}mo
        </text>
      ))}
      {actual.map((p) => (
        <g key={p.month}>
          <line x1={g.x(p.month)} x2={g.x(p.month)} y1={g.y(p.actual)} y2={H - M.b} stroke="#e04a2f" strokeWidth="1" strokeOpacity="0.25" />
          <circle cx={g.x(p.month)} cy={g.y(p.actual)} r="4.5" fill="#e04a2f" stroke="white" strokeWidth="1.5" />
          <text x={g.x(p.month)} y={g.y(p.actual) - 9} textAnchor="middle" className="fill-[#c2381f] font-mono text-[10.5px]">
            {Math.round(p.actual * 100)}%
          </text>
        </g>
      ))}
    </svg>
  );
}
