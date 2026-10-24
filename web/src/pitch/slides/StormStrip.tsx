import { useEffect, useMemo, useState } from "react";
import { motion, useReducedMotion } from "motion/react";
import { scaleLinear } from "d3-scale";
import { curveMonotoneX, line } from "d3-shape";
import type { StormRun } from "@/api/types";
import { metarSeries, stormFacts } from "@/components/storm/model";
import { VERDICT_COLOR } from "@/components/verdict";
import { zulu } from "@/lib/format";
import { EASE_OUT } from "../stage";
import { Fig } from "../ui";

const H = 152;
const PLOT_TOP = 26;
const PLOT_BOTTOM = 100;
const LANE = 113;
const MARGIN_MIN = 50;

/** The ticks as OCC's 05:12Z list coded them, before the re-check: one light grey. */
const CODED = "var(--color-cloud-300)";

/**
 * When each beat lands, in ms after the strip mounts (the Wow card has risen by the first one):
 * 1 the wind draws and the storm window opens · 2 every cancellation lands coded as OCC typed it, the
 * recoded one inside the storm · 3 the re-check: the tech log shows, the codes settle, and the recoded
 * flight slides out of the window to the time it was due and turns red.
 */
const BEATS = [650, 1900, 3200];

/**
 * The moment in one strip, drawn from the storm run with the app's own timeline model: the tech-log fault the
 * night before, Dublin's gusts, the storm window, and every departure at its scheduled time. It plays the
 * Storm Run's recode in miniature when the slide opens; with reduced motion it shows the settled strip.
 */
export function StormStrip({ run, width = 350 }: { run: StormRun | undefined; width?: number }) {
  const reduce = useReducedMotion();
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
    // "71 → 41": the code OCC typed and the one the engine recoded it to, as the decision reports them.
    const [codedAs, recodedTo] = (focus?.recodeLabel ?? "").split("→").map((s) => s.trim());
    return { win, deps, focus, fault, t0, t1, wind, codedAs: codedAs || focus?.row.flight.ops_cause_code || null, recodedTo: recodedTo || null };
  }, [run]);

  const play = !reduce && !!model;
  const [phase, setPhase] = useState(0);
  useEffect(() => {
    if (!play) return;
    const timers = BEATS.map((ms, i) => window.setTimeout(() => setPhase(i + 1), ms));
    return () => timers.forEach((t) => window.clearTimeout(t));
  }, [play]);
  const at = play ? phase : 3;

  if (!model) return <Fig value={null} width="100%" className="block h-[152px] rounded-[14px]" />;

  const { win, deps, focus, fault, t0, t1, wind, codedAs, recodedTo } = model;
  const x = scaleLinear().domain([t0, t1]).range([0, width]);
  const peak = Math.max(40, ...wind.map((o) => o.kt));
  const y = scaleLinear().domain([0, peak + 6]).range([PLOT_BOTTOM, PLOT_TOP]);
  const gust = line<{ at: number; kt: number }>().x((o) => x(o.at)).y((o) => y(o.kt)).curve(curveMonotoneX)(wind) ?? "";
  const wx0 = x(win.start.getTime());
  const wx1 = x(win.end.getTime());
  const cancelled = deps.filter((t) => t.verdict !== "operated");
  const operated = deps.filter((t) => t.verdict === "operated");
  // The recoded flight is drawn last so it sits on top, and starts where OCC's batch code put it: in the storm.
  const ordered = [...cancelled].sort((a, b) => Number(a.recoded) - Number(b.recoded) || a.at.getTime() - b.at.getTime());
  const startX = (t: (typeof deps)[number]) => (t.recoded && t.at > win.end ? wx1 - 6 : x(t.at.getTime()));
  const label = { fontSize: 15, className: "font-sans tabular-nums" };
  const instant = { duration: 0 };
  const focusX = focus ? x(focus.at.getTime()) : 0;

  return (
    <svg
      width={width}
      height={H}
      viewBox={`0 0 ${width} ${H}`}
      role="img"
      aria-label={`Storm window ${zulu(win.raw.start)} to ${zulu(win.raw.end)} at ${run?.station}${fault ? `; tech log fault at ${zulu(fault.at.toISOString())} the night before` : ""}${focus ? `; ${focus.number} was due at ${zulu(focus.at.toISOString())}, after the storm${focus.recodeLabel ? `, recoded ${focus.recodeLabel}` : ""}` : ""}`}
      className="block overflow-visible"
      data-testid="storm-strip"
      data-phase={at}
    >
      {/* 1 · the storm window opens left to right, the wind draws over it */}
      <motion.rect
        x={wx0}
        y={PLOT_TOP - 6}
        width={Math.max(0, wx1 - wx0)}
        height={LANE + 10 - PLOT_TOP + 6}
        rx={6}
        fill="rgba(79,159,224,0.16)"
        initial={false}
        animate={{ scaleX: at >= 1 ? 1 : 0, opacity: at >= 1 ? 1 : 0 }}
        transition={play ? { duration: 0.9, ease: EASE_OUT, delay: 0.25 } : instant}
        style={{ originX: 0 }}
      />
      <motion.path
        d={gust}
        fill="none"
        stroke="rgba(238,242,247,0.8)"
        strokeWidth={2}
        strokeLinejoin="round"
        strokeLinecap="round"
        initial={false}
        animate={{ pathLength: at >= 1 ? 1 : 0, opacity: at >= 1 ? 1 : 0 }}
        transition={play ? { pathLength: { duration: 1.4, ease: "easeInOut" }, opacity: { duration: 0.2 } } : instant}
      />
      <line x1={0} x2={width} y1={LANE + 10} y2={LANE + 10} stroke="rgba(200,208,219,0.18)" />

      {/* 3 · the re-check finds the tech-log fault, logged the night before */}
      {fault ? (
        <motion.g initial={false} animate={{ opacity: at >= 3 ? 1 : 0 }} transition={play ? { duration: 0.35 } : instant}>
          <motion.line
            x1={x(fault.at.getTime())}
            x2={x(fault.at.getTime())}
            y1={18}
            y2={LANE + 10}
            stroke="var(--color-notweather)"
            strokeDasharray="3 4"
            strokeWidth={1.5}
            initial={false}
            animate={{ scaleY: at >= 3 ? 1 : 0 }}
            transition={play ? { duration: 0.5, ease: EASE_OUT } : instant}
            style={{ originY: 0 }}
          />
          <circle cx={x(fault.at.getTime())} cy={18} r={3.5} fill="var(--color-notweather)" />
          <text x={x(fault.at.getTime()) + 9} y={22} fill="var(--color-notweather)" {...label}>
            tech log {zulu(fault.at.toISOString())}
          </text>
        </motion.g>
      ) : null}

      {/* operated: they flew, once the re-check has run */}
      {operated.map((t, i) => (
        <motion.rect
          key={t.id}
          x={x(t.at.getTime()) - 1.5}
          y={LANE - 8}
          width={3}
          height={16}
          rx={1.5}
          fill={VERDICT_COLOR.operated}
          initial={false}
          animate={{ opacity: at >= 3 ? 1 : 0 }}
          transition={play ? { duration: 0.4, delay: 0.25 + i * 0.03 } : instant}
        />
      ))}

      {/* 2 · every cancellation as OCC coded it; 3 · settled by the re-check */}
      {ordered.map((t, i) => {
        const focused = t.recoded;
        return (
          <motion.g
            key={t.id}
            initial={false}
            animate={{ x: at >= 3 ? x(t.at.getTime()) : startX(t), opacity: at >= 2 ? 1 : 0 }}
            transition={
              play
                ? { x: { delay: focused ? 0.55 : 0, duration: focused ? 1.15 : 0.3, ease: EASE_OUT }, opacity: { delay: at === 2 ? i * 0.035 : 0, duration: 0.25 } }
                : instant
            }
            data-flight={t.number}
            data-verdict={at >= 3 ? t.verdict : "coded"}
          >
            {/* attrY is the rect's y attribute (a bare `y` would be a transform on a motion element) */}
            <motion.rect
              x={focused ? -2.5 : -1.5}
              width={focused ? 5 : 3}
              rx={1.5}
              initial={false}
              animate={{ fill: at >= 3 ? VERDICT_COLOR[t.verdict] : CODED, height: at >= 3 && focused ? 26 : 16, attrY: at >= 3 && focused ? LANE - 13 : LANE - 8 }}
              transition={play ? { delay: at >= 3 ? (focused ? 1.1 : 0.1 + (i % 9) * 0.04) : 0, duration: 0.45 } : instant}
            />
          </motion.g>
        );
      })}

      {/* captions: what OCC typed, then what the window was and which flight it really was */}
      {codedAs ? (
        <motion.text x={(wx0 + wx1) / 2} y={H - 4} textAnchor="middle" fill="var(--color-cloud-300)" {...label} initial={false} animate={{ opacity: at === 2 ? 1 : 0 }} transition={play ? { duration: 0.3 } : instant}>
          all coded {codedAs} by OCC
        </motion.text>
      ) : null}
      <motion.text x={(wx0 + wx1) / 2} y={H - 4} textAnchor="middle" fill="var(--color-metar)" {...label} initial={false} animate={{ opacity: at >= 3 ? 1 : 0 }} transition={play ? { duration: 0.4, delay: 0.3 } : instant}>
        storm {zulu(win.raw.start).replace("Z", "")}–{zulu(win.raw.end)}
      </motion.text>
      {focus ? (
        <motion.g initial={false} animate={{ opacity: at >= 3 ? 1 : 0 }} transition={play ? { duration: 0.4, delay: 1.35 } : instant}>
          <text x={focusX} y={H - 4} textAnchor="middle" fill="var(--color-notweather)" fontWeight={700} {...label}>
            {focus.number}
          </text>
          {codedAs && recodedTo ? (
            <text x={Math.min(width, focusX + 6)} y={13} textAnchor="end" fill="var(--color-notweather)" {...label}>
              {codedAs} → {recodedTo}
            </text>
          ) : null}
        </motion.g>
      ) : null}
    </svg>
  );
}
