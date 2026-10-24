import { useState } from "react";
import { scaleLinear } from "d3-scale";
import type { CalibrationBin } from "@/api/types";
import { useWidth } from "@/components/storm/useWidth";
import { count, pct } from "@/lib/format";
import { cn } from "@/lib/utils";
import { KIND_LABEL } from "./model";

const ML = 34;
const MR = 10;
const MT = 10;
const HIST = 30;

/**
 * One reliability diagram per decision kind: observed accuracy against stated confidence, a dot per bin
 * with its Wilson 95% interval, the diagonal as perfect calibration, and n per bin as a histogram below.
 */
export function ReliabilityCard({ kind, bins, coverage }: { kind: string; bins: CalibrationBin[]; coverage: number | undefined }) {
  const total = bins.reduce((s, b) => s + b.n, 0);
  const label = KIND_LABEL[kind] ?? kind.replace(/_/g, " ");
  return (
    <section aria-label={`${label} reliability`} className="flex flex-col rounded-xl bg-card px-4 pb-3 pt-4 shadow-[0_0_0_1px_var(--color-cloud-200),0_1px_2px_rgba(13,21,36,0.04)]" data-testid={`reliability-${kind}`}>
      <div className="flex items-baseline justify-between gap-2">
        <h3 className="text-[14px] font-semibold text-navy-900">{label}</h3>
        {bins.length ? <span className="figure text-[12px] text-slate-400">n {count(total)}</span> : null}
      </div>
      <p className="mt-0.5 text-[12.5px] text-slate-500">
        coverage@0.9 <span className="figure font-semibold text-navy-900">{coverage === undefined ? "—" : pct(coverage)}</span>
      </p>
      {bins.length ? <Diagram bins={bins} label={label} /> : <Uncalibrated />}
      {bins.length ? <BinTable bins={bins} label={label} /> : null}
    </section>
  );
}

function Uncalibrated() {
  return (
    <div className="mt-3 flex aspect-[1/0.92] flex-col items-center justify-center rounded-lg bg-[repeating-linear-gradient(45deg,transparent,transparent_5px,var(--color-cloud-100)_5px,var(--color-cloud-100)_7px)] px-6 text-center shadow-[inset_0_0_0_1px_var(--color-cloud-200)]">
      <span className="rounded-md bg-white px-2 py-1 font-mono text-[11.5px] text-slate-600 shadow-[inset_0_0_0_1px_var(--color-cloud-300)]">uncalibrated</span>
      <span className="mt-2 max-w-[24ch] text-[12px] leading-snug text-slate-500">No model for this decision kind yet. Its decisions route to a person.</span>
    </div>
  );
}

function Diagram({ bins, label }: { bins: CalibrationBin[]; label: string }) {
  const [ref, width] = useWidth<HTMLDivElement>(260);
  const [hover, setHover] = useState<number | null>(null);
  const P = Math.max(140, width - ML - MR);
  const PH = Math.round(P * 0.8);
  const x = scaleLinear().domain([0, 1]).range([0, P]);
  const y = scaleLinear().domain([0, 1]).range([PH, 0]);
  const maxN = Math.max(1, ...bins.map((b) => b.n));
  const h = scaleLinear().domain([0, maxN]).range([0, HIST - 10]);
  const histTop = PH + 12;
  const H = MT + histTop + HIST + 22;
  const b = hover === null || !bins[hover]?.n ? null : bins[hover];

  return (
    <div ref={ref} className="relative mt-3">
      <svg width={width} height={H} className="block overflow-visible" role="img" aria-label={`${label}: ${bins.map((bn) => `confidence ${pct(bn.lo)}–${pct(bn.hi)}, n ${bn.n}, ${pct(bn.accuracy)} right`).join("; ")}`}>
        <g transform={`translate(${ML},${MT})`}>
          {[0, 0.5, 1].map((t) => (
            <g key={t}>
              <line x1={0} x2={P} y1={y(t)} y2={y(t)} stroke={t === 0 ? "var(--color-cloud-300)" : "var(--color-cloud-100)"} />
              <line x1={x(t)} x2={x(t)} y1={0} y2={PH} stroke="var(--color-cloud-100)" />
              <text x={-7} y={y(t)} dy="0.32em" textAnchor="end" className="fill-slate-400 text-[10px] tabular-nums">
                {pct(t)}
              </text>
            </g>
          ))}
          <text x={2} y={-2} className="fill-slate-400 text-[10px]">
            right
          </text>
          {/* perfect calibration */}
          <line x1={x(0)} y1={y(0)} x2={x(1)} y2={y(1)} stroke="var(--color-cloud-400)" strokeWidth={1} />

          {bins.map((bn, i) => {
            if (!bn.n) return null;
            const cx = x((bn.lo + bn.hi) / 2);
            const on = hover === i;
            return (
              <g key={i}>
                <line x1={cx} x2={cx} y1={y(bn.wilson_lo)} y2={y(bn.wilson_hi)} stroke="var(--color-navy-900)" strokeWidth={1.5} />
                <line x1={cx - 3.5} x2={cx + 3.5} y1={y(bn.wilson_lo)} y2={y(bn.wilson_lo)} stroke="var(--color-navy-900)" strokeWidth={1.5} />
                <line x1={cx - 3.5} x2={cx + 3.5} y1={y(bn.wilson_hi)} y2={y(bn.wilson_hi)} stroke="var(--color-navy-900)" strokeWidth={1.5} />
                <circle cx={cx} cy={y(bn.accuracy)} r={on ? 5 : 4} fill="var(--color-navy-900)" stroke="white" strokeWidth={2} />
                {/* n per bin */}
                <rect x={x(bn.lo) + 1} y={histTop + (HIST - 10) - h(bn.n)} width={Math.max(1, x(bn.hi) - x(bn.lo) - 2)} height={Math.max(1, h(bn.n))} rx={1.5} fill={on ? "var(--color-slate-400)" : "var(--color-cloud-300)"} />
                {x(bn.hi) - x(bn.lo) >= 20 ? (
                  <text x={cx} y={histTop + (HIST - 10) - h(bn.n) - 3} textAnchor="middle" className="fill-slate-400 text-[9.5px] tabular-nums">
                    {count(bn.n)}
                  </text>
                ) : null}
                <rect
                  x={x(bn.lo)}
                  y={-MT}
                  width={Math.max(8, x(bn.hi) - x(bn.lo))}
                  height={histTop + HIST + MT}
                  fill="transparent"
                  onPointerEnter={() => setHover(i)}
                  onPointerLeave={() => setHover(null)}
                />
              </g>
            );
          })}
          <line x1={0} x2={P} y1={histTop + HIST - 10} y2={histTop + HIST - 10} stroke="var(--color-cloud-300)" />
          <text x={-7} y={histTop + HIST - 14} textAnchor="end" className="fill-slate-400 text-[10px] italic">
            n
          </text>
          {[0, 0.5, 1].map((t) => (
            <text key={t} x={x(t)} y={histTop + HIST + 6} textAnchor={t === 0 ? "start" : t === 1 ? "end" : "middle"} className="fill-slate-400 text-[10px] tabular-nums">
              {pct(t)}
            </text>
          ))}
          <text x={P} y={histTop + HIST + 19} textAnchor="end" className="fill-slate-400 text-[10px]">
            stated confidence
          </text>
        </g>
      </svg>
      {b ? (
        <div className="pointer-events-none absolute z-10 w-[196px] rounded-lg bg-navy-900 px-3 py-2 text-cloud-50 shadow-lg" style={{ left: Math.min(width - 196, Math.max(0, ML + x((b.lo + b.hi) / 2) - 98)), top: MT + Math.max(0, y(b.wilson_hi) - 74) }}>
          <p className="figure text-[11px] text-cloud-400">
            {pct(b.lo)}–{pct(b.hi)} confidence · n {count(b.n)}
          </p>
          <p className="mt-1 text-[13px]">
            <span className="figure font-semibold">{pct(b.accuracy)}</span> right
          </p>
          <p className="figure text-[11px] text-cloud-400">
            Wilson 95% {pct(b.wilson_lo)}–{pct(b.wilson_hi)}
          </p>
        </div>
      ) : null}
    </div>
  );
}

function BinTable({ bins, label }: { bins: CalibrationBin[]; label: string }) {
  return (
    <details className="mt-1 text-[12px] text-slate-500">
      <summary className="cursor-pointer select-none text-[12px] text-slate-500 hover:text-navy-900">Table view</summary>
      <table className="mt-2 w-full text-[12px]">
        <caption className="sr-only">{label} reliability bins</caption>
        <thead>
          <tr className="text-slate-400">
            <th scope="col" className="py-1 text-left font-normal">Confidence</th>
            <th scope="col" className="py-1 text-right font-normal">n</th>
            <th scope="col" className="py-1 text-right font-normal">Right</th>
            <th scope="col" className="py-1 text-right font-normal">Wilson 95%</th>
          </tr>
        </thead>
        <tbody className="tabular-nums">
          {bins.map((bn, i) => (
            <tr key={i} className="border-t border-cloud-100">
              <th scope="row" className="py-1 text-left font-normal text-slate-600">
                {pct(bn.lo)}–{pct(bn.hi)}
              </th>
              <td className="py-1 text-right">{count(bn.n)}</td>
              <td className={cn("py-1 text-right text-navy-900")}>{bn.n ? pct(bn.accuracy) : "—"}</td>
              <td className="py-1 text-right">{bn.n ? `${pct(bn.wilson_lo)}–${pct(bn.wilson_hi)}` : "—"}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </details>
  );
}
