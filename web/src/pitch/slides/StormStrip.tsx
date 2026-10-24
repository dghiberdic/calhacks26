import { useMemo } from "react";
import { scaleLinear } from "d3-scale";
import { curveMonotoneX, line } from "d3-shape";
import type { StormRun } from "@/api/types";
import { metarSeries, stormFacts } from "@/components/storm/model";
import { VERDICT_COLOR } from "@/components/verdict";
import { zulu } from "@/lib/format";
import { Fig } from "../ui";

const H = 152;
const PLOT_TOP = 26;
const PLOT_BOTTOM = 100;
const LANE = 113;
const MARGIN_MIN = 50;

/**
 * The moment in one strip, drawn from the storm run with the app's own timeline model: the tech-log fault the
 * night before, Dublin's gusts, the storm window, and every departure at its scheduled time. The cancellations
 * sit inside the window; the recoded one sits among the flights that flew.
 */
export function StormStrip({ run, width = 350 }: { run: StormRun | undefined; width?: number }) {
  const model = useMemo(() => {
    if (!run) return null;
    const facts = stormFacts(run);
    const deps = facts.ticks.filter((t) => t.lane === "dep");
    const win = facts.windows.reduce<(typeof facts.windows)[number] | null>((best, w) => (!best || w.end.getTime() - w.start.getTime() > best.end.getTime() - best.start.getTime() ? w : best), null);
    if (!win || !deps.length) return null;
    const focus = deps.find((t) => t.recoded) ?? null;
    const fault = facts.techLog.find((t) => !focus || t.flightId === focus.row.flight.id) ?? null;
    const times = deps.map((t) => t.at.getTime());
    const t0 = Math.min(win.start.getTime(), fault?.at.getTime() ?? Infinity, ...times) - MARGIN_MIN * 60_000;
    const t1 = Math.max(win.end.getTime(), ...times) + MARGIN_MIN * 60_000;
    const wind = metarSeries(run.metar)
      .map((o) => ({ at: o.at.getTime(), kt: o.gust ?? o.sknt }))
      .filter((o): o is { at: number; kt: number } => o.kt !== null && o.at >= t0 && o.at <= t1);
    return { win, deps, focus, fault, t0, t1, wind };
  }, [run]);

  if (!model) return <Fig value={null} width="100%" className="block h-[152px] rounded-[14px]" />;

  const { win, deps, focus, fault, t0, t1, wind } = model;
  const x = scaleLinear().domain([t0, t1]).range([0, width]);
  const peak = Math.max(40, ...wind.map((o) => o.kt));
  const y = scaleLinear().domain([0, peak + 6]).range([PLOT_BOTTOM, PLOT_TOP]);
  const gust = line<{ at: number; kt: number }>().x((o) => x(o.at)).y((o) => y(o.kt)).curve(curveMonotoneX)(wind) ?? "";
  const wx0 = x(win.start.getTime());
  const wx1 = x(win.end.getTime());
  const ordered = [...deps].sort((a, b) => Number(a.recoded) - Number(b.recoded));
  const label = { fontSize: 15, className: "font-sans tabular-nums" };

  return (
    <svg
      width={width}
      height={H}
      viewBox={`0 0 ${width} ${H}`}
      role="img"
      aria-label={`Storm window ${zulu(win.raw.start)} to ${zulu(win.raw.end)} at ${run?.station}${fault ? `; tech log fault at ${zulu(fault.at.toISOString())} the night before` : ""}${focus ? `; ${focus.number} was due at ${zulu(focus.at.toISOString())}, after the storm` : ""}`}
      className="block overflow-visible"
    >
      <rect x={wx0} y={PLOT_TOP - 6} width={Math.max(0, wx1 - wx0)} height={LANE + 10 - PLOT_TOP + 6} rx={6} fill="rgba(79,159,224,0.16)" />
      <path d={gust} fill="none" stroke="rgba(238,242,247,0.8)" strokeWidth={2} strokeLinejoin="round" />
      <line x1={0} x2={width} y1={LANE + 10} y2={LANE + 10} stroke="rgba(200,208,219,0.18)" />

      {fault ? (
        <g>
          <line x1={x(fault.at.getTime())} x2={x(fault.at.getTime())} y1={18} y2={LANE + 10} stroke="var(--color-notweather)" strokeDasharray="3 4" strokeWidth={1.5} />
          <circle cx={x(fault.at.getTime())} cy={18} r={3.5} fill="var(--color-notweather)" />
          <text x={x(fault.at.getTime()) + 9} y={22} fill="var(--color-notweather)" {...label}>
            tech log {zulu(fault.at.toISOString())}
          </text>
        </g>
      ) : null}

      {ordered.map((t) => (
        <rect key={t.id} x={x(t.at.getTime()) - (t.recoded ? 2.5 : 1.5)} y={LANE - (t.recoded ? 13 : 8)} width={t.recoded ? 5 : 3} height={t.recoded ? 26 : 16} rx={1.5} fill={VERDICT_COLOR[t.verdict]} />
      ))}

      <text x={(wx0 + wx1) / 2} y={H - 4} textAnchor="middle" fill="var(--color-metar)" {...label}>
        storm {zulu(win.raw.start).replace("Z", "")}–{zulu(win.raw.end)}
      </text>
      {focus ? (
        <text x={x(focus.at.getTime())} y={H - 4} textAnchor="middle" fill="var(--color-notweather)" fontWeight={700} {...label}>
          {focus.number}
        </text>
      ) : null}
    </svg>
  );
}
