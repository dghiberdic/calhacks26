import { useEffect, useMemo, useState } from "react";
import { motion, useReducedMotion } from "motion/react";
import { scaleLinear, scaleUtc } from "d3-scale";
import { area, curveMonotoneX, line } from "d3-shape";
import type { StormRun } from "@/api/types";
import { zulu, zuluDay } from "@/lib/format";
import { cn } from "@/lib/utils";
import { verdictChip, type VerdictKind } from "../verdict";
import { mainWindowOf, metarSeries, stormFacts, type Tick } from "./model";
import { useWidth } from "./useWidth";

type Props = {
  run: StormRun;
  compact?: boolean;
  /** Play the overnight story on mount: every tick coded 71, then each settles; NS31 slides out of the band. */
  animate?: boolean;
  tone?: "dark" | "light";
  className?: string;
  onSelectFlight?: (flightId: string) => void;
};

const PALETTE = {
  dark: {
    text: "var(--color-cloud-500)",
    strong: "var(--color-cloud-200)",
    grid: "rgba(200,208,219,0.08)",
    axis: "rgba(200,208,219,0.18)",
    gust: "#eef2f7",
    sustained: "var(--color-slate-400)",
    fillTop: "rgba(238,242,247,0.16)",
    coded: "var(--color-cloud-300)",
    operated: "var(--color-slate-400)",
    band: "rgba(79,159,224,0.16)",
    bandEdge: "rgba(79,159,224,0.55)",
  },
  light: {
    text: "var(--color-slate-500)",
    strong: "var(--color-navy-900)",
    grid: "rgba(13,21,36,0.05)",
    axis: "rgba(13,21,36,0.14)",
    gust: "var(--color-navy-800)",
    sustained: "var(--color-slate-400)",
    fillTop: "rgba(22,34,56,0.1)",
    coded: "var(--color-slate-500)",
    operated: "var(--color-slate-500)",
    band: "rgba(79,159,224,0.14)",
    bandEdge: "rgba(37,101,163,0.5)",
  },
};

const VERDICT_FILL: Record<VerdictKind, string> = {
  weather: "var(--color-weather)",
  notweather: "var(--color-notweather)",
  held: "var(--color-held)",
  operated: "var(--color-slate-400)",
  pending: "var(--color-cloud-400)",
};

type Hover = { kind: "metar"; x: number; i: number } | { kind: "tick"; x: number; tick: Tick } | null;

export function StormTimeline({ run, compact, animate = true, tone = "dark", className, onSelectFlight }: Props) {
  const [ref, width] = useWidth<HTMLDivElement>();
  const reduce = useReducedMotion();
  const play = animate && !reduce;
  const [phase, setPhase] = useState(play ? 0 : 3);
  const [hover, setHover] = useState<Hover>(null);
  const c = PALETTE[tone];

  // 0 draw curves · 1 band · 2 every cancellation coded as OCC typed it · 3 the re-check settles them
  useEffect(() => {
    if (!play) return;
    const timers = [window.setTimeout(() => setPhase(1), 900), window.setTimeout(() => setPhase(2), 1700), window.setTimeout(() => setPhase(3), 3300)];
    return () => timers.forEach((t) => window.clearTimeout(t));
  }, [play, run.id]);

  const facts = useMemo(() => stormFacts(run), [run]);
  const series = useMemo(() => metarSeries(run.metar), [run.metar]);

  const H = compact ? 230 : 340;
  const M = { l: 44, r: 16, t: compact ? 30 : 42, b: compact ? 58 : 76 };
  const W = Math.max(width, 320);
  const plotBottom = H - M.b;
  const depY = plotBottom + (compact ? 22 : 28);
  const arrY = plotBottom + (compact ? 42 : 54);

  const x = useMemo(() => scaleUtc().domain(facts.domain).range([M.l, W - M.r]), [facts.domain, W, M.l, M.r]);
  const peak = Math.max(40, ...series.map((o) => o.gust ?? o.sknt ?? 0));
  const y = useMemo(() => scaleLinear().domain([0, Math.ceil((peak + 6) / 10) * 10]).range([plotBottom, M.t]), [peak, plotBottom, M.t]);

  const inDomain = series.filter((o) => o.at >= facts.domain[0] && o.at <= facts.domain[1]);
  const gustOf = (o: (typeof series)[number]) => o.gust ?? o.sknt ?? 0;
  const gustPath = line<(typeof series)[number]>().x((o) => x(o.at)).y((o) => y(gustOf(o))).curve(curveMonotoneX)(inDomain) ?? "";
  const gustArea = area<(typeof series)[number]>().x((o) => x(o.at)).y0(plotBottom).y1((o) => y(gustOf(o))).curve(curveMonotoneX)(inDomain) ?? "";
  const sustainedPath = line<(typeof series)[number]>().x((o) => x(o.at)).y((o) => y(o.sknt ?? 0)).curve(curveMonotoneX)(inDomain.filter((o) => o.sknt !== null)) ?? "";

  const hours: Date[] = [];
  for (let t = facts.domain[0].getTime(); t <= facts.domain[1].getTime(); t += 3 * 3600_000) hours.push(new Date(t));
  const midnight = new Date(facts.domain[0].getTime() + 6 * 3600_000);

  const ticks = facts.ticks.filter((t) => t.at >= facts.domain[0] && t.at <= facts.domain[1]);
  const cancelled = ticks.filter((t) => t.verdict !== "operated");
  const operated = ticks.filter((t) => t.verdict === "operated");
  const mainWindow = facts.windows.find((w) => w.raw === mainWindowOf(run.windows)) ?? null;

  const tickColor = (t: Tick) => (phase < 2 ? "transparent" : phase < 3 ? c.coded : VERDICT_FILL[t.verdict]);
  const startX = (t: Tick) => {
    // The recoded flight starts where OCC's batch code put it, inside the storm, then slides to its own time.
    if (phase < 3 && t.recoded && mainWindow && t.at > mainWindow.end) return x(mainWindow.end) - 5;
    return x(t.at);
  };

  const onPlotMove = (e: React.PointerEvent<SVGRectElement>) => {
    const bounds = (e.currentTarget.ownerSVGElement ?? e.currentTarget).getBoundingClientRect();
    const px = e.clientX - bounds.left;
    const at = x.invert(px).getTime();
    let best = 0;
    inDomain.forEach((o, i) => {
      if (Math.abs(o.at.getTime() - at) < Math.abs(inDomain[best].at.getTime() - at)) best = i;
    });
    if (inDomain.length) setHover({ kind: "metar", x: x(inDomain[best].at), i: best });
  };

  const hoveredObs = hover?.kind === "metar" ? inDomain[hover.i] : null;

  return (
    <div ref={ref} className={cn("relative w-full select-none", className)}>
      <svg width={W} height={H} viewBox={`0 0 ${W} ${H}`} role="img" aria-label={`Wind at ${run.station} from METAR, with the storm window and every flight at its scheduled time`} className="block overflow-visible">
        <defs>
          <linearGradient id={`gust-fill-${tone}`} x1="0" x2="0" y1="0" y2="1">
            <stop offset="0" stopColor={c.fillTop} />
            <stop offset="1" stopColor="transparent" />
          </linearGradient>
        </defs>

        {/* grid + y axis (knots) */}
        <motion.g initial={{ opacity: play ? 0 : 1 }} animate={{ opacity: 1 }} transition={{ duration: 0.5 }}>
          {y.ticks(4).map((v) => (
            <g key={v}>
              <line x1={M.l} x2={W - M.r} y1={y(v)} y2={y(v)} stroke={c.grid} />
              <text x={M.l - 8} y={y(v) + 3.5} textAnchor="end" fontSize={10} fill={c.text} className="font-mono">
                {v}
              </text>
            </g>
          ))}
          <text x={M.l - 8} y={M.t - 12} textAnchor="end" fontSize={10} fill={c.text} className="font-mono">
            kt
          </text>
          <line x1={M.l} x2={W - M.r} y1={plotBottom} y2={plotBottom} stroke={c.axis} />
          {hours.map((h) => (
            <g key={h.getTime()}>
              <line x1={x(h)} x2={x(h)} y1={plotBottom} y2={plotBottom + 4} stroke={c.axis} />
              <text x={x(h)} y={H - 6} textAnchor="middle" fontSize={10} fill={c.text} className="font-mono">
                {zulu(h.toISOString()).replace("Z", "")}
              </text>
            </g>
          ))}
          <line x1={x(midnight)} x2={x(midnight)} y1={M.t - 6} y2={arrY + 8} stroke={c.axis} strokeDasharray="2 3" />
          <text x={x(midnight) + 5} y={M.t - 8} fontSize={10} fill={c.text} className="font-mono">
            {zuluDay(midnight.toISOString()).split(" ").slice(0, 2).join(" ")}
          </text>
        </motion.g>

        {/* storm window(s), computed from data by the engine */}
        {facts.windows.map((w, i) => {
          const x0 = Math.max(M.l, x(w.start));
          const x1 = Math.min(W - M.r, x(w.end));
          if (x1 <= x0) return null;
          const isMain = w === mainWindow;
          return (
            <motion.g key={i} initial={{ opacity: play ? 0 : 1 }} animate={{ opacity: phase >= 1 ? 1 : 0 }} transition={{ duration: 0.6 }}>
              <motion.rect
                x={x0}
                y={M.t - 4}
                width={x1 - x0}
                height={plotBottom - M.t + 4}
                fill={c.band}
                initial={{ scaleX: play ? 0 : 1 }}
                animate={{ scaleX: phase >= 1 ? 1 : 0 }}
                transition={{ duration: 0.9, ease: [0.16, 1, 0.3, 1] }}
                style={{ originX: 0 }}
              />
              <line x1={x0} x2={x0} y1={M.t - 4} y2={plotBottom} stroke={c.bandEdge} strokeWidth={1} />
              <line x1={x1} x2={x1} y1={M.t - 4} y2={plotBottom} stroke={c.bandEdge} strokeWidth={1} />
              {isMain && !compact ? (
                <text x={x0 + 8} y={M.t + 10} fontSize={10.5} fill="var(--color-metar)" className="font-mono">
                  storm window {zulu(w.raw.start)}–{zulu(w.raw.end)}
                  <title>{w.raw.definition}</title>
                </text>
              ) : null}
            </motion.g>
          );
        })}

        {/* gust and sustained wind */}
        <motion.path d={gustArea} fill={`url(#gust-fill-${tone})`} initial={{ opacity: play ? 0 : 1 }} animate={{ opacity: 1 }} transition={{ delay: play ? 0.7 : 0, duration: 0.8 }} />
        <motion.path d={sustainedPath} fill="none" stroke={c.sustained} strokeWidth={1.3} strokeDasharray="1 0" initial={{ pathLength: play ? 0 : 1 }} animate={{ pathLength: 1 }} transition={{ duration: 1.3, ease: "easeInOut" }} />
        <motion.path d={gustPath} fill="none" stroke={c.gust} strokeWidth={compact ? 1.6 : 2} strokeLinejoin="round" initial={{ pathLength: play ? 0 : 1 }} animate={{ pathLength: 1 }} transition={{ duration: 1.4, ease: "easeInOut" }} />
        {facts.gustLimitKt ? (
          <g opacity={0.8}>
            <line x1={M.l} x2={W - M.r} y1={y(facts.gustLimitKt)} y2={y(facts.gustLimitKt)} stroke="var(--color-metar)" strokeOpacity={0.45} strokeDasharray="4 4" />
            {!compact ? (
              <text x={W - M.r} y={y(facts.gustLimitKt) - 5} textAnchor="end" fontSize={10} fill="var(--color-metar)" className="font-mono">
                gust {facts.gustLimitKt} kt
              </text>
            ) : null}
          </g>
        ) : null}

        {/* tech log: the fault, logged before any storm window */}
        {facts.techLog.map((t) => (
          <motion.g key={t.at.getTime()} initial={{ opacity: play ? 0 : 1 }} animate={{ opacity: phase >= 2 ? 1 : 0 }} transition={{ duration: 0.5 }}>
            <line x1={x(t.at)} x2={x(t.at)} y1={M.t - 4} y2={arrY + 8} stroke="var(--color-notweather)" strokeOpacity={0.75} strokeDasharray="3 3" />
            <circle cx={x(t.at)} cy={M.t - 4} r={3} fill="var(--color-notweather)" />
            {!compact ? (
              <text x={x(t.at) + 7} y={M.t + 10} fontSize={10.5} fill="var(--color-notweather)" className="font-mono">
                {t.label} · {zulu(t.at.toISOString())}
              </text>
            ) : null}
          </motion.g>
        ))}

        {/* lanes */}
        <text x={M.l - 8} y={depY + 4} textAnchor="end" fontSize={9.5} fill={c.text} className="font-mono">
          dep
        </text>
        <text x={M.l - 8} y={arrY + 4} textAnchor="end" fontSize={9.5} fill={c.text} className="font-mono">
          arr
        </text>
        <line x1={M.l} x2={W - M.r} y1={depY} y2={depY} stroke={c.grid} />
        <line x1={M.l} x2={W - M.r} y1={arrY} y2={arrY} stroke={c.grid} />

        {/* operated: solid, they flew */}
        {operated.map((t) => (
          <motion.rect
            key={t.id}
            x={x(t.at) - 1.5}
            y={(t.lane === "dep" ? depY : arrY) - 7}
            width={3}
            height={14}
            rx={1}
            fill={c.operated}
            initial={{ opacity: play ? 0 : 1 }}
            animate={{ opacity: phase >= 3 ? 1 : 0 }}
            transition={{ delay: play ? 0.9 : 0, duration: 0.5 }}
            onPointerEnter={() => setHover({ kind: "tick", x: x(t.at), tick: t })}
            onPointerLeave={() => setHover(null)}
            onClick={() => onSelectFlight?.(t.id)}
            className={onSelectFlight ? "cursor-pointer" : undefined}
          />
        ))}

        {/* cancelled: coded as OCC typed it, then settled by the re-check */}
        {cancelled.map((t, i) => {
          const laneY = t.lane === "dep" ? depY : arrY;
          const focus = t.recoded;
          return (
            <motion.g
              key={t.id}
              initial={{ x: startX(t), opacity: play ? 0 : 1 }}
              animate={{ x: phase >= 3 ? x(t.at) : startX(t), opacity: phase >= 2 ? 1 : 0 }}
              transition={{ x: { delay: focus ? 0.5 : 0, duration: focus ? 1.1 : 0.4, ease: [0.16, 1, 0.3, 1] }, opacity: { delay: play && phase === 2 ? i * 0.035 : 0, duration: 0.3 } }}
              onPointerEnter={() => setHover({ kind: "tick", x: x(t.at), tick: t })}
              onPointerLeave={() => setHover(null)}
              onClick={() => onSelectFlight?.(t.id)}
              className={onSelectFlight ? "cursor-pointer" : undefined}
              data-flight={t.number}
              data-verdict={phase >= 3 ? t.verdict : "coded"}
            >
              <motion.rect x={-1.75} y={laneY - 8} width={focus ? 4 : 3.5} height={16} rx={1} animate={{ fill: tickColor(t) }} transition={{ delay: phase >= 3 ? (focus ? 0.9 : 0.15 + (i % 9) * 0.04) : 0, duration: 0.45 }} />
              {!compact ? (
                <motion.text
                  y={laneY - 12}
                  textAnchor="middle"
                  fontSize={9}
                  className="font-mono"
                  animate={{ opacity: phase === 2 || (phase >= 3 && focus) ? 1 : 0, fill: phase >= 3 && focus ? "var(--color-notweather)" : c.text }}
                  transition={{ delay: phase >= 3 && focus ? 1.2 : 0, duration: 0.4 }}
                >
                  {phase >= 3 && focus ? (t.recodeLabel?.split("→").pop()?.trim() ?? t.code) : t.code}
                </motion.text>
              ) : null}
            </motion.g>
          );
        })}

        {/* hover layer for METAR */}
        <rect x={M.l} y={M.t - 4} width={W - M.l - M.r} height={plotBottom - M.t + 4} fill="transparent" onPointerMove={onPlotMove} onPointerLeave={() => setHover(null)} />
        {hoveredObs ? (
          <g pointerEvents="none">
            <line x1={x(hoveredObs.at)} x2={x(hoveredObs.at)} y1={M.t - 4} y2={plotBottom} stroke={c.strong} strokeOpacity={0.35} />
            <circle cx={x(hoveredObs.at)} cy={y(gustOf(hoveredObs))} r={3.5} fill={c.gust} />
          </g>
        ) : null}
      </svg>

      {/* tooltips */}
      {hover ? (
        <div
          className={cn(
            "pointer-events-none absolute z-10 max-w-[320px] rounded-lg px-3 py-2 text-[12px] shadow-lg",
            tone === "dark" ? "bg-navy-950/95 text-cloud-100 ring-1 ring-white/10" : "bg-white text-navy-900 ring-1 ring-cloud-200",
          )}
          style={{ left: Math.min(Math.max(hover.x - 160, 4), W - 324), top: hover.kind === "tick" ? (compact ? 120 : 190) : 8 }}
          role="tooltip"
        >
          {hover.kind === "metar" && hoveredObs ? (
            <>
              <div className="font-mono text-[11px] opacity-70">{zuluDay(hoveredObs.at.toISOString())}</div>
              <div className="mt-0.5">
                {hoveredObs.sknt ?? "—"} kt{hoveredObs.gust ? `, gusts ${hoveredObs.gust} kt` : ""}
              </div>
              <div className="mt-1 break-words font-mono text-[11px] leading-snug opacity-80">{hoveredObs.raw}</div>
            </>
          ) : hover.kind === "tick" ? (
            <TickTip tick={hover.tick} settled={phase >= 3} />
          ) : null}
        </div>
      ) : null}
    </div>
  );
}

function TickTip({ tick, settled }: { tick: Tick; settled: boolean }) {
  const f = tick.row.flight;
  const chip = verdictChip(tick.row.decision);
  return (
    <>
      <div className="flex items-center justify-between gap-3">
        <span className="font-mono text-[12px] font-bold">{f.number}</span>
        <span className="font-mono text-[11px] opacity-70">
          {f.origin}–{f.dest} · {tick.lane === "dep" ? "STD" : "STA"} {zulu(tick.at.toISOString())}
        </span>
      </div>
      <div className="mt-1 opacity-80">
        {f.status === "operated" ? "Operated" : settled ? chip.text : `Coded ${tick.code ?? "—"} by OCC`}
        {tick.recoded && settled ? ` · ${tick.recodeLabel}` : ""}
      </div>
      {f.pax ? <div className="mt-0.5 text-[11px] opacity-60">{f.pax} passengers</div> : null}
    </>
  );
}
