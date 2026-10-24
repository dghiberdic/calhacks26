import { useState } from "react";
import { motion, useReducedMotion } from "motion/react";
import { scaleLinear } from "d3-scale";
import { useCfo } from "@/api/queries";
import type { EvalReport } from "@/api/types";
import { useWidth } from "@/components/storm/useWidth";
import { pct } from "@/lib/format";
import { cn } from "@/lib/utils";
import { axisMax, euros, headline, placeLabels, readRuns, runLabel, type Runs } from "./model";

const EASE = [0.16, 1, 0.3, 1] as const;

/**
 * "Plain Claude, 3 runs: €a / €b / €c. StormCheck: €34,650 ×3, same hash." The sentence, then the same
 * runs on one € axis: the baseline's land in three places, StormCheck's in one.
 */
export function RunsHero({ report }: { report: EvalReport }) {
  const base = readRuns(report.baseline);
  const sc = readRuns(report.stormcheck_runs);
  const h = headline(base, sc);
  // The bridge's two ends, to name a run that landed exactly on one of them.
  const cfo = useCfo();
  const anchors = cfo.data ? { cashCents: cfo.data.cash_basis_cents, fullCents: cfo.data.full_entitlement_cents } : null;
  return (
    <section aria-labelledby="proof-headline" className="relative overflow-hidden rounded-2xl bg-navy-900 text-cloud-50 shadow-[0_20px_60px_-20px_rgba(8,13,23,0.55)]">
      <div aria-hidden="true" className="pointer-events-none absolute -left-40 -top-48 size-[560px] rounded-full bg-[radial-gradient(closest-side,rgba(200,208,219,0.08),transparent)]" />
      <div className="relative px-5 pt-6 md:px-9 md:pt-8">
        <p className="micro text-cloud-500">{base.runs ? `Same raw documents · ${base.runs} runs each` : "Same raw documents"}</p>
        <h2 id="proof-headline" className="display mt-4 text-[27px] leading-[1.08] text-pretty sm:text-[32px] md:text-[36px] xl:text-[40px]" data-testid="proof-headline">
          <span className="block text-balance text-cloud-500">{h.baseline}</span> <span className="mt-1 block text-cloud-50">{h.stormcheck}</span>
        </h2>
      </div>
      {base.values.length || sc.values.length ? <RunsPlot base={base} sc={sc} anchors={anchors} /> : <div className="h-6" />}
      <div className="relative grid grid-cols-[minmax(0,1fr)] gap-px border-t border-white/[0.07] bg-white/[0.07] sm:grid-cols-2">
        <RunFacts title="Plain Claude" runs={base} note={base.model ? `${base.model} on the raw documents` : "the model on the raw documents"} />
        <RunFacts title="StormCheck" runs={sc} note="Reader facts, then the deterministic engine" strong />
      </div>
    </section>
  );
}

function RunFacts({ title, runs, note, strong }: { title: string; runs: Runs; note: string; strong?: boolean }) {
  return (
    <div className="bg-navy-900 px-5 py-4 md:px-9">
      <p className={cn("text-[13.5px] font-semibold", strong ? "text-cloud-50" : "text-cloud-300")}>{title}</p>
      <p className="mt-0.5 text-[12.5px] text-cloud-500">{note}</p>
      <ul className="mt-2 flex flex-col gap-1 text-[12.5px] text-cloud-400">
        <li>
          {runs.hashIdentical === true ? (
            <>
              same hash on all {runs.runs} runs{runs.hash ? <span className="ml-1.5 font-mono text-[11.5px] text-cloud-300">{runs.hash.slice(0, 12)}</span> : null}
            </>
          ) : runs.hashIdentical === false ? (
            <>a different hash on each run</>
          ) : (
            <>hash not reported</>
          )}
        </li>
        {runs.accuracy.length ? <li>cause accuracy {runs.accuracy.map((a) => pct(a)).join(" / ")}</li> : null}
      </ul>
    </div>
  );
}

/** Both sets of runs on one € axis, from €0. */
function RunsPlot({ base, sc, anchors }: { base: Runs; sc: Runs; anchors: { cashCents: number; fullCents: number } | null }) {
  const [ref, width] = useWidth<HTMLDivElement>(900);
  const reduce = useReducedMotion();
  const [hover, setHover] = useState<string | null>(null);
  const narrow = width < 560;
  const ML = narrow ? 4 : 132;
  const MR = narrow ? 12 : 40;
  const iw = Math.max(200, width - ML - MR);
  const max = axisMax([...base.values, ...sc.values]);
  const x = scaleLinear().domain([0, max]).range([0, iw]);
  const laneA = narrow ? 64 : 46;
  const laneB = narrow ? 166 : 128;
  const axisY = narrow ? 222 : 184;
  const H = axisY + 34;
  const scX = sc.values.length ? x(sc.values[0]) : null;

  // Baseline value labels, named when they land on the bridge's ends; above the dot unless that collides.
  const labels = base.values.map((v) => runLabel(v, anchors));
  const order = base.values.map((v, i) => ({ i, x: x(v), w: labels[i].length * 6.6 })).sort((a, b) => a.x - b.x);
  const rows = placeLabels(order, iw);
  const below = new Set(order.filter((_, k) => rows[k] === "below").map((o) => o.i));
  const ticks = [0, 0.25, 0.5, 0.75, 1].map((t) => t * max);

  return (
    <div className="relative mt-6 px-5 md:px-9">
      <div ref={ref}>
        <svg width={iw + ML + MR} height={H} className="block overflow-visible" role="img" aria-label={`Plain Claude's ${base.runs} runs: ${labels.join(", ")}. StormCheck's ${sc.runs} runs: ${sc.values.map(euros).join(", ")}.`}>
        <g transform={`translate(${ML},0)`}>
          {/* lanes */}
          {[laneA, laneB].map((y) => (
            <line key={y} x1={0} x2={iw} y1={y} y2={y} stroke="rgba(255,255,255,0.08)" />
          ))}
          <text x={narrow ? 0 : -24} y={narrow ? laneA - 44 : laneA} dy="0.32em" textAnchor={narrow ? "start" : "end"} className="fill-cloud-300 text-[13px] font-semibold">
            Plain Claude
          </text>
          <text x={narrow ? 0 : -24} y={narrow ? laneB - 40 : laneB} dy="0.32em" textAnchor={narrow ? "start" : "end"} className="fill-cloud-50 text-[13px] font-semibold">
            StormCheck
          </text>

          {/* where StormCheck lands, through both lanes */}
          {scX !== null ? <line x1={scX} x2={scX} y1={laneA - 26} y2={axisY} stroke="rgba(255,255,255,0.14)" /> : null}

          {/* baseline runs: three answers */}
          {base.values.map((v, i) => {
            const cx = x(v);
            const key = `b${i}`;
            return (
              <g key={key} onPointerEnter={() => setHover(key)} onPointerLeave={() => setHover(null)}>
                <motion.circle
                  cy={laneA}
                  r={hover === key ? 8 : 7}
                  fill="var(--color-navy-900)"
                  stroke="var(--color-cloud-300)"
                  strokeWidth={2}
                  initial={reduce || scX === null ? false : { cx: scX, opacity: 0.4 }}
                  animate={{ cx, opacity: 1 }}
                  transition={{ duration: 1.1, delay: 0.35 + i * 0.12, ease: EASE }}
                />
                <motion.text
                  x={cx < 24 ? cx - 7 : cx > iw - 24 ? cx + 7 : cx}
                  y={below.has(i) ? laneA + 26 : laneA - 16}
                  textAnchor={cx < 24 ? "start" : cx > iw - 24 ? "end" : "middle"}
                  className="fill-cloud-300 text-[12px] tabular-nums"
                  initial={reduce ? false : { opacity: 0 }}
                  animate={{ opacity: 1 }}
                  transition={{ duration: 0.4, delay: 1.2 + i * 0.12 }}
                >
                  {labels[i]}
                </motion.text>
                <circle cx={cx} cy={laneA} r={14} fill="transparent" />
                {hover === key ? (
                  <text x={cx < 24 ? cx - 7 : cx > iw - 24 ? cx + 7 : cx} y={below.has(i) ? laneA - 16 : laneA + 26} textAnchor={cx < 24 ? "start" : cx > iw - 24 ? "end" : "middle"} className="fill-cloud-500 text-[11px]">
                    run {i + 1}
                    {base.accuracy[i] !== undefined ? ` · cause accuracy ${pct(base.accuracy[i])}` : ""}
                  </text>
                ) : null}
              </g>
            );
          })}

          {/* StormCheck runs: one answer, stacked */}
          {sc.allSame && scX !== null ? (
            <g>
              {sc.values.map((_, i) => {
                const dy = (i - (sc.values.length - 1) / 2) * 15;
                return (
                  <motion.circle
                    key={i}
                    cx={scX}
                    cy={laneB + dy}
                    r={6}
                    fill="var(--color-cloud-50)"
                    stroke="var(--color-navy-900)"
                    strokeWidth={2}
                    initial={reduce ? false : { opacity: 0, scale: 0.4 }}
                    animate={{ opacity: 1, scale: 1 }}
                    transition={{ duration: 0.45, delay: 0.25 + i * 0.12, ease: EASE }}
                    style={{ transformOrigin: `${scX}px ${laneB + dy}px` }}
                  />
                );
              })}
              <motion.g initial={reduce ? false : { opacity: 0 }} animate={{ opacity: 1 }} transition={{ duration: 0.4, delay: 0.8 }}>
                <text x={scX > iw * 0.7 ? scX - 18 : scX + 18} y={laneB - 4} textAnchor={scX > iw * 0.7 ? "end" : "start"} className="fill-cloud-50 text-[15px] font-semibold tabular-nums">
                  {euros(sc.values[0])} ×{sc.runs}
                </text>
                <text x={scX > iw * 0.7 ? scX - 18 : scX + 18} y={laneB + 15} textAnchor={scX > iw * 0.7 ? "end" : "start"} className="fill-cloud-400 text-[12px]">
                  {sc.hashIdentical ? "same hash" : sc.hashIdentical === false ? "hashes differ" : ""}
                </text>
              </motion.g>
            </g>
          ) : (
            sc.values.map((v, i) => <circle key={i} cx={x(v)} cy={laneB} r={6} fill="var(--color-cloud-50)" stroke="var(--color-navy-900)" strokeWidth={2} />)
          )}

          {/* € axis from zero */}
          <line x1={0} x2={iw} y1={axisY} y2={axisY} stroke="rgba(255,255,255,0.16)" />
          {ticks.map((t, i) => (
            <g key={t}>
              <line x1={x(t)} x2={x(t)} y1={axisY} y2={axisY + 5} stroke="rgba(255,255,255,0.16)" />
              <text x={x(t)} y={axisY + 20} textAnchor={i === 0 ? "start" : i === ticks.length - 1 ? "end" : "middle"} className="fill-cloud-500 text-[11px] tabular-nums">
                {euros(t)}
              </text>
            </g>
          ))}
        </g>
      </svg>
      </div>
    </div>
  );
}
