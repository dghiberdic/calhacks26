import { useMemo, useState, type KeyboardEvent, type PointerEvent } from "react";
import { scaleLinear } from "d3-scale";
import { curveMonotoneX, line } from "d3-shape";
import type { ClaimCurve, CurveSegment } from "@/api/types";
import { useWidth } from "@/components/storm/useWidth";
import { count, pct } from "@/lib/format";
import { cn } from "@/lib/utils";
import { SEGMENTS, segmentName } from "./model";

export type CohortActual = { segment: string; month: number; rate: number; expected: number; ae: number; label: string };

const PLOT_H = 206;
const MT = 22;
const MB = 54;
const ML = 40;
/** Share of the plot width given to observed history; the rest is the tail to the ultimate. */
const HISTORY = 0.74;

const rateAt = (c: ClaimCurve | undefined, m: number) => c?.points.find(([month]) => month === m)?.[1] ?? null;

/**
 * Cumulative valid-claim rate (€ basis) by months since the event: observed history on a √-time axis so
 * the early months read, then the tail to the ultimate (documented judgment, dashed). The focus segment is
 * ink and the others stay grey context. The cohort's actual, when there is one, sits off its curve.
 */
export function ClaimCurveChart({ curves, focus, actual }: { curves: Partial<Record<CurveSegment, ClaimCurve>>; focus: CurveSegment; actual?: CohortActual | null }) {
  const [ref, width] = useWidth<HTMLDivElement>(520);
  const [hover, setHover] = useState<number | null>(null);
  const f = curves[focus];
  const narrow = width < 440;
  const MR = narrow ? 46 : 92;
  const iw = Math.max(160, width - ML - MR);
  const ih = PLOT_H;

  const geo = useMemo(() => {
    if (!f) return null;
    const obs = f.observed_through_month || Math.max(...f.points.map(([m]) => m), 1);
    const tailX = iw * HISTORY;
    const xm = (m: number) => tailX * Math.sqrt(Math.max(0, Math.min(m, obs)) / obs);
    const all = Object.values(curves).filter(Boolean) as ClaimCurve[];
    const top = Math.max(...all.map((c) => Math.max(c.ultimate, ...c.points.map(([, r]) => r))), actual?.rate ?? 0);
    const yMax = Math.max(0.1, Math.ceil((top + 0.03) * 10) / 10);
    const y = scaleLinear().domain([0, yMax]).range([ih, 0]);
    const ticks = Array.from({ length: Math.round(yMax * 10) + 1 }, (_, i) => i / 10);
    const history = line<[number, number]>()
      .x(([m]) => xm(m))
      .y(([, r]) => y(r))
      .curve(curveMonotoneX);
    const paths = (c: ClaimCurve) => {
      const pts: [number, number][] = [[0, 0], ...c.points.filter(([m]) => m <= obs)];
      const [lm, lr] = pts[pts.length - 1];
      const x0 = xm(lm);
      return { history: history(pts) ?? "", tail: `M${x0},${y(lr)} Q${x0 + (iw - x0) * 0.42},${y(c.ultimate)} ${iw},${y(c.ultimate)}` };
    };
    const xs = f.points.map(([m]) => xm(m));
    const minGap = xs.slice(1).reduce((g, x, i) => Math.min(g, x - xs[i]), Infinity);
    return { obs, tailX, xm, y, ticks, paths, xs, showN: minGap >= 42 && f.n_by_point.length === f.points.length };
  }, [f, curves, iw, ih, actual?.rate]);

  if (!f || !geo) return null;
  const { obs, tailX, xm, y, ticks, paths, xs, showN } = geo;
  const stops = [...f.points.map(([m]) => m), "ult" as const];
  const others = SEGMENTS.filter((s) => s.id !== focus && curves[s.id]);
  const showActual = actual && actual.segment === focus;

  const pick = (e: PointerEvent<SVGRectElement>) => {
    const box = e.currentTarget.getBoundingClientRect();
    const px = e.clientX - box.left;
    const targets = [...xs, iw];
    let best = 0;
    for (let i = 1; i < targets.length; i++) if (Math.abs(targets[i] - px) < Math.abs(targets[best] - px)) best = i;
    setHover(best);
  };
  const onKey = (e: KeyboardEvent<HTMLDivElement>) => {
    const last = stops.length - 1;
    if (e.key === "ArrowRight") setHover((h) => Math.min(last, (h ?? -1) + 1));
    else if (e.key === "ArrowLeft") setHover((h) => Math.max(0, (h ?? stops.length) - 1));
    else if (e.key === "Home") setHover(0);
    else if (e.key === "End") setHover(last);
    else if (e.key === "Escape") setHover(null);
    else return;
    e.preventDefault();
  };

  const hx = hover === null ? null : hover < xs.length ? xs[hover] : iw;
  const stop = hover === null ? null : stops[hover];
  const fy = stop === null ? null : y(stop === "ult" ? f.ultimate : (rateAt(f, stop) ?? 0));
  const summary = `${segmentName(focus)} claim curve ${f.version}: ${f.points.map(([m, r]) => `M${m} ${pct(r)}`).join(", ")}, ultimate ${pct(f.ultimate)}.`;

  return (
    <div>
      <div className="flex flex-wrap items-center gap-x-4 gap-y-1.5 text-[11.5px] text-slate-500">
        <span className="inline-flex items-center gap-1.5">
          <svg width="18" height="6" aria-hidden="true">
            <line x1="0" y1="3" x2="18" y2="3" stroke="var(--color-navy-900)" strokeWidth="2" strokeLinecap="round" />
          </svg>
          history to M{obs}
        </span>
        <span className="inline-flex items-center gap-1.5">
          <svg width="18" height="6" aria-hidden="true">
            <line x1="1" y1="3" x2="17" y2="3" stroke="var(--color-navy-900)" strokeWidth="1.5" strokeDasharray="3 3" strokeLinecap="round" />
          </svg>
          tail · documented judgment
        </span>
        {showActual ? (
          <span className="inline-flex items-center gap-1.5">
            <svg width="10" height="10" aria-hidden="true">
              <rect x="2" y="2" width="6" height="6" transform="rotate(45 5 5)" fill="var(--color-navy-900)" />
            </svg>
            {actual.label} actual
          </span>
        ) : null}
        {others.length ? (
          <span className="inline-flex items-center gap-1.5">
            <svg width="18" height="6" aria-hidden="true">
              <line x1="0" y1="3" x2="18" y2="3" stroke="var(--color-cloud-400)" strokeWidth="1.5" strokeLinecap="round" />
            </svg>
            other segments
          </span>
        ) : null}
      </div>

      <div
        ref={ref}
        className="relative mt-3 outline-none focus-visible:ring-2 focus-visible:ring-ring/40 focus-visible:ring-offset-4 rounded-sm"
        tabIndex={0}
        role="img"
        aria-label={summary}
        onKeyDown={onKey}
        onBlur={() => setHover(null)}
      >
        <svg width={width} height={MT + ih + MB} className="block overflow-visible" aria-hidden="true">
          <g transform={`translate(${ML},${MT})`}>
            {/* tail region */}
            <rect x={tailX} y={0} width={iw - tailX} height={ih} fill="var(--color-cloud-25)" />
            <text x={tailX + 8} y={-8} className="fill-slate-400 font-mono text-[10px] uppercase tracking-[0.08em]">
              tail
            </text>
            {/* grid */}
            {ticks.map((t) => (
              <g key={t}>
                <line x1={0} x2={iw} y1={y(t)} y2={y(t)} stroke={t === 0 ? "var(--color-cloud-300)" : "var(--color-cloud-100)"} />
                <text x={-8} y={y(t)} dy="0.32em" textAnchor="end" className="fill-slate-400 text-[10.5px] tabular-nums">
                  {pct(t)}
                </text>
              </g>
            ))}
            <line x1={tailX} x2={tailX} y1={0} y2={ih} stroke="var(--color-cloud-200)" />

            {/* context segments */}
            {others.map((s) => {
              const c = curves[s.id]!;
              const p = paths(c);
              return (
                <g key={s.id}>
                  <path d={p.history} fill="none" stroke="var(--color-cloud-400)" strokeWidth={1.5} strokeLinecap="round" />
                  <path d={p.tail} fill="none" stroke="var(--color-cloud-400)" strokeWidth={1.25} strokeDasharray="3 3" />
                  <text x={iw + 8} y={y(c.ultimate)} dy="0.32em" className="fill-slate-400 text-[11px] tabular-nums">
                    {pct(c.ultimate)}
                    {narrow ? "" : ` ${s.name.split(" ")[0].toLowerCase()}`}
                  </text>
                </g>
              );
            })}

            {/* focus segment */}
            {(() => {
              const p = paths(f);
              return (
                <g>
                  <path d={p.tail} fill="none" stroke="var(--color-navy-900)" strokeWidth={1.5} strokeDasharray="3 3" />
                  <path d={p.history} fill="none" stroke="var(--color-navy-900)" strokeWidth={2} strokeLinecap="round" strokeLinejoin="round" />
                  {f.points.map(([m, r], i) => (
                    <circle key={m} cx={xm(m)} cy={y(r)} r={hover === i ? 5 : 4} fill="var(--color-navy-900)" stroke="white" strokeWidth={2} />
                  ))}
                  <circle cx={iw} cy={y(f.ultimate)} r={hover === stops.length - 1 ? 5 : 4} fill="white" stroke="var(--color-navy-900)" strokeWidth={2} />
                  <text x={iw + 8} y={y(f.ultimate)} dy="0.32em" className="fill-navy-900 text-[11.5px] font-semibold tabular-nums">
                    {pct(f.ultimate)}
                    {narrow ? "" : <tspan className="fill-slate-500 font-normal"> ultimate</tspan>}
                  </text>
                </g>
              );
            })()}

            {/* the cohort's actual, off its curve; its label sits in the empty top-left with a leader */}
            {showActual ? (
              <g>
                <line x1={xm(actual.month)} x2={xm(actual.month)} y1={y(actual.expected)} y2={y(actual.rate)} stroke="var(--color-slate-400)" />
                <polyline points={`${xm(actual.month)},${y(actual.rate) - 7} ${xm(actual.month)},${30} ${xm(actual.month) + 8},${22}`} fill="none" stroke="var(--color-slate-400)" />
                <rect x={xm(actual.month) - 4.5} y={y(actual.rate) - 4.5} width={9} height={9} transform={`rotate(45 ${xm(actual.month)} ${y(actual.rate)})`} fill="var(--color-navy-900)" stroke="white" strokeWidth={2} />
                {tailX - xm(actual.month) - 20 >= 190 ? (
                  <>
                    <text x={xm(actual.month) + 12} y={12} className="fill-navy-900 text-[11.5px] font-semibold">
                      {actual.label} · M{actual.month} actual {pct(actual.rate, 1)}
                    </text>
                    <text x={xm(actual.month) + 12} y={27} className="fill-slate-500 text-[11px] tabular-nums">
                      vs {pct(actual.expected, 1)} on the curve · A/E {actual.ae.toFixed(2)}
                    </text>
                  </>
                ) : (
                  <text x={xm(actual.month) + 12} y={25} className="fill-navy-900 text-[11.5px] font-semibold">
                    {actual.label} · A/E {actual.ae.toFixed(2)}
                  </text>
                )}
              </g>
            ) : null}

            {/* x axis: months, then n per point */}
            {f.points.map(([m], i) => (
              <text key={m} x={xs[i]} y={ih + 18} textAnchor="middle" className={cn("text-[10.5px] tabular-nums", hover === i ? "fill-navy-900 font-semibold" : "fill-slate-500")}>
                M{m}
              </text>
            ))}
            <text x={iw} y={ih + 18} textAnchor="end" className="fill-slate-400 text-[10.5px]">
              ultimate
            </text>
            {showN ? (
              <>
                <text x={-8} y={ih + 36} textAnchor="end" className="fill-slate-400 text-[10.5px] italic">
                  n
                </text>
                {f.n_by_point.map((n, i) => (
                  <text key={i} x={xs[i]} y={ih + 36} textAnchor="middle" className="fill-slate-400 text-[10.5px] tabular-nums">
                    {count(n)}
                  </text>
                ))}
              </>
            ) : null}

            {/* crosshair */}
            {hx !== null && fy !== null ? <line x1={hx} x2={hx} y1={0} y2={ih} stroke="var(--color-slate-400)" strokeWidth={1} /> : null}
            <rect x={-12} y={-MT} width={iw + 24} height={ih + MT + 24} fill="transparent" onPointerMove={pick} onPointerLeave={() => setHover(null)} />
          </g>
        </svg>

        {hx !== null && stop !== null && fy !== null ? (
          <div
            className="pointer-events-none absolute z-10 w-[188px] rounded-lg bg-navy-900 px-3 py-2.5 text-cloud-50 shadow-lg"
            style={{ left: ML + hx + (hx > iw * 0.55 ? -200 : 12), top: Math.max(0, MT + fy - 30) }}
          >
            <p className="text-[11.5px] text-cloud-400">
              {stop === "ult" ? (
                <>
                  <span className="font-semibold text-cloud-50">Ultimate</span> · to limitation
                </>
              ) : (
                <>
                  <span className="font-semibold text-cloud-50">M{stop}</span> · months since the event
                </>
              )}
            </p>
            <ul className="mt-1.5 flex flex-col gap-1">
              {SEGMENTS.filter((s) => curves[s.id]).map((s) => {
                const c = curves[s.id]!;
                const v = stop === "ult" ? c.ultimate : rateAt(c, stop);
                return (
                  <li key={s.id} className="flex items-baseline justify-between gap-3 text-[12px]">
                    <span className={s.id === focus ? "text-cloud-50" : "text-cloud-400"}>{s.name}</span>
                    <span className={cn("tabular-nums", s.id === focus ? "font-semibold text-cloud-50" : "text-cloud-300")}>{v === null ? "—" : pct(v, 1)}</span>
                  </li>
                );
              })}
            </ul>
            {stop !== "ult" && f.n_by_point[hover!] !== undefined ? (
              <p className="figure mt-1.5 text-[11px] text-cloud-400">
                n {count(f.n_by_point[hover!])} · {segmentName(focus).toLowerCase()}
              </p>
            ) : null}
          </div>
        ) : null}
      </div>

      <details className="mt-2 text-[12.5px] text-slate-500">
        <summary className="cursor-pointer select-none text-[12px] text-slate-500 hover:text-navy-900">Table view</summary>
        <div className="mt-2 overflow-x-auto">
          <table className="w-full min-w-[380px] text-[12.5px]">
            <caption className="sr-only">Cumulative valid-claim rate by months since the event, per segment</caption>
            <thead>
              <tr className="text-left text-slate-400">
                <th scope="col" className="py-1 pr-3 font-normal">Month</th>
                {SEGMENTS.filter((s) => curves[s.id]).map((s) => (
                  <th key={s.id} scope="col" className="py-1 pr-3 text-right font-normal">
                    {s.name}
                  </th>
                ))}
                <th scope="col" className="py-1 text-right font-normal">
                  n · {segmentName(focus).toLowerCase()}
                </th>
              </tr>
            </thead>
            <tbody className="tabular-nums">
              {f.points.map(([m], i) => (
                <tr key={m} className="border-t border-cloud-100">
                  <th scope="row" className="py-1 pr-3 text-left font-normal text-slate-600">
                    M{m}
                  </th>
                  {SEGMENTS.filter((s) => curves[s.id]).map((s) => {
                    const v = rateAt(curves[s.id], m);
                    return (
                      <td key={s.id} className={cn("py-1 pr-3 text-right", s.id === focus ? "text-navy-900" : "text-slate-500")}>
                        {v === null ? "—" : pct(v, 1)}
                      </td>
                    );
                  })}
                  <td className="py-1 text-right text-slate-500">{f.n_by_point[i] === undefined ? "—" : count(f.n_by_point[i])}</td>
                </tr>
              ))}
              <tr className="border-t border-cloud-200">
                <th scope="row" className="py-1 pr-3 text-left font-normal text-slate-600">
                  Ultimate
                </th>
                {SEGMENTS.filter((s) => curves[s.id]).map((s) => (
                  <td key={s.id} className={cn("py-1 pr-3 text-right", s.id === focus ? "font-semibold text-navy-900" : "text-slate-500")}>
                    {pct(curves[s.id]!.ultimate)}
                  </td>
                ))}
                <td />
              </tr>
            </tbody>
          </table>
        </div>
      </details>
    </div>
  );
}
