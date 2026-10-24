import { useEffect, useMemo, useRef } from "react";
import { scaleLinear, scaleUtc } from "d3-scale";
import { area, curveMonotoneX, line } from "d3-shape";
import { metarSeries, stormFacts } from "@/components/storm/model";
import { iataOf } from "@/lib/airports";
import { count, duration, zulu } from "@/lib/format";
import { cn } from "@/lib/utils";
import { focusRow, hhmm, mainWindow, ms, nearestObs } from "../data/model";
import { useStory } from "../data/context";
import { gsap, MEDIA, PLOTTED, prefersReducedMotion, UNPLOTTED, useGSAP } from "../motion/gsap";
import { PIN_PRIORITY } from "../motion/useAutoRefresh";
import { Pending } from "../ui";
import { windBarb } from "./barbs";

const W = 1200;
const H = 560;
const M = { l: 70, r: 36, t: 96, b: 176 };
const PLOT_BOTTOM = H - M.b;
const DEP_Y = PLOT_BOTTOM + 66;
const ARR_Y = PLOT_BOTTOM + 112;
const DAYS = ["SUN", "MON", "TUE", "WED", "THU", "FRI", "SAT"];
const MONTHS = ["JAN", "FEB", "MAR", "APR", "MAY", "JUN", "JUL", "AUG", "SEP", "OCT", "NOV", "DEC"];
const dayLabel = (d: Date) => `${DAYS[d.getUTCDay()]} ${d.getUTCDate()} ${MONTHS[d.getUTCMonth()]}`;
const TONE = { weather: "#8a96a5", held: "#e2a12a", notweather: "#e2452c", operated: "#73839a", pending: "#c8d0db" } as const;
/** Every cancellation as OCC coded it, before the re-check settles it. */
const CODED = "#dfe4eb";

/** ECAM line from the tech log ("HYD Y ENG 2 PUMP LO PR"), else its first sentence. */
const ecamOf = (quote: string | null | undefined) => quote?.match(/ECAM\s+([^.]+)\./)?.[1]?.trim() ?? quote?.split(".")[1]?.trim() ?? null;

/**
 * Weather has a window. The airport's own METAR, from the evening before to midnight: the engine's
 * storm window, every cancelled flight at its time (departures at STD, arrivals at STA), the
 * departures that flew after it, NS31 outside it, and the tech-log entry from the night before.
 */
export function StormWindow() {
  const story = useStory();
  const root = useRef<HTMLElement>(null);
  const gustRef = useRef<SVGPathElement>(null);
  const headRef = useRef<SVGGElement>(null);
  /** The chart is drawn far enough for the reading to ride the gust line (set by the scroll timeline). */
  const drawn = useRef(false);
  const run = story.run;

  const g = useMemo(() => {
    if (!run) return null;
    const facts = stormFacts(run);
    const series = metarSeries(run.metar).filter((o) => o.at >= facts.domain[0] && o.at <= facts.domain[1]);
    const x = scaleUtc().domain(facts.domain).range([M.l, W - M.r]);
    const y = scaleLinear().domain([0, 70]).range([PLOT_BOTTOM, M.t]);
    type O = (typeof series)[number];
    const gustOf = (o: O) => o.gust ?? o.sknt ?? 0;
    const gust = line<O>().x((o) => x(o.at)).y((o) => y(gustOf(o))).curve(curveMonotoneX)(series) ?? "";
    const mean = line<O>().x((o) => x(o.at)).y((o) => y(o.sknt ?? 0)).curve(curveMonotoneX)(series.filter((o) => o.sknt !== null)) ?? "";
    const fill = area<O>().x((o) => x(o.at)).y0(PLOT_BOTTOM).y1((o) => y(gustOf(o))).curve(curveMonotoneX)(series) ?? "";
    const hours: Date[] = [];
    for (let t = facts.domain[0].getTime(); t <= facts.domain[1].getTime(); t += 3 * 3600_000) hours.push(new Date(t));
    const barbs = hours.slice(0, -1).flatMap((h) => {
      const o = nearestObs(run.metar, h.toISOString());
      return o && o.drct !== null && o.drct !== undefined && o.sknt !== null && o.sknt !== undefined ? [{ at: h, ...windBarb(x(h), M.t - 46, o.drct, o.sknt, 20) }] : [];
    });
    const midnight = new Date(facts.domain[0].getTime() + 6 * 3600_000);
    return { facts, series, x, y, gust, mean, fill, hours, barbs, midnight };
  }, [run]);

  const focus = focusRow(run);
  const win = mainWindow(run?.windows);
  const log = story.log;
  const logObs = log?.at ? nearestObs(run?.metar, log.at.toISOString()) : null;
  const hub = run?.station;
  const hubIata = run ? iataOf(run.station) : null;
  const inside = run?.flights.filter((r) => r.flight.status === "cancelled" && r.flight.origin === hubIata && r.decision?.in_window_dep === "in").length;
  const operated = run?.flights.filter((r) => r.flight.status === "operated" && r.flight.origin === hubIata) ?? [];
  const opFirst = operated.length ? operated.reduce((a, b) => (ms(b.flight.sched_dep) < ms(a.flight.sched_dep) ? b : a)) : null;
  const opLast = operated.length ? operated.reduce((a, b) => (ms(b.flight.sched_dep) > ms(a.flight.sched_dep) ? b : a)) : null;
  const margin = focus?.decision?.window_margin_min ?? (win && focus ? Math.round((ms(focus.flight.sched_dep) - ms(win.end)) / 60_000) : null);
  const limit = g?.facts.gustLimitKt ?? null;
  // a shorter window the engine also found, before the main one (the burst around midnight on Éowyn)
  const earlier = win ? (run?.windows ?? []).filter((w) => ms(w.end) <= ms(win.start)).sort((a, b) => ms(b.start) - ms(a.start))[0] ?? null : null;

  useGSAP(
    () => {
      if (!g) return;
      const mm = gsap.matchMedia();
      mm.add({ motion: MEDIA.motion, phone: MEDIA.phone }, (ctx) => {
        if (!ctx.conditions?.motion) return;
        const phone = !!ctx.conditions.phone;
        const tl = gsap.timeline({
          defaults: { ease: "none" },
          scrollTrigger: { trigger: ".sw-stage", start: "top top", end: phone ? "+=190%" : "+=140%", scrub: 0.6, pin: true, anticipatePin: 1, invalidateOnRefresh: true, refreshPriority: PIN_PRIORITY.window },
          onUpdate: () => void (drawn.current = tl.progress() > 0.42),
        });
        // Every step targets elements that exist (the tech log and NS31 arrive with the Flight File).
        const has = (sel: string) => !!root.current?.querySelector(sel);
        const step = (sel: string, vars: gsap.TweenVars, at?: gsap.Position) => (has(sel) ? tl.from(sel, vars, at) : tl);
        step(".sw-axis", { opacity: 0, duration: 0.3 });
        step(".sw-barb", { opacity: 0, y: -6, stagger: 0.03, duration: 0.3 }, "<");
        step(".sw-limit", { scaleX: 0, transformOrigin: "left center", duration: 0.6 }, "-=0.1");
        step(".sw-limit-label", { opacity: 0, duration: 0.3 }, "<0.1");
        tl.addLabel("gust");
        step(".sw-gust, .sw-mean", { ...UNPLOTTED, duration: 1.6, ease: "power1.inOut" });
        step(".sw-fill", { opacity: 0, duration: 0.8 }, "<0.6");
        step(".sw-window", { scaleX: 0, transformOrigin: "left center", duration: 0.8, ease: "power2.inOut", stagger: 0.1 });
        step(".sw-window-label", { opacity: 0, y: 6, duration: 0.4 }, "-=0.2");
        step(".sw-lane", { opacity: 0, duration: 0.3 });
        step(".sw-tick", { opacity: 0, y: -16, stagger: 0.025, duration: 0.35, ease: "back.out(2)" });
        tl.addLabel("check");
        step(".sw-tick-dot", { fill: CODED, duration: 0.5, stagger: 0.015 });
        step(".sw-legend", { opacity: 0, y: 6, duration: 0.4 }, "<");
        step(".sw-op", { opacity: 0, scaleY: 0, transformOrigin: "50% 100%", stagger: 0.03, duration: 0.3 }, "<0.2");
        step(".sw-op-label", { opacity: 0, duration: 0.3 });
        tl.addLabel("ns31");
        step(".sw-ns31", { opacity: 0, scale: 0.4, transformOrigin: "50% 50%", duration: 0.4, ease: "back.out(3)" });
        step(".sw-margin", { scaleX: 0, transformOrigin: "left center", duration: 0.6, ease: "power2.inOut" });
        step(".sw-margin-label", { opacity: 0, duration: 0.3 });
        tl.addLabel("fault");
        step(".sw-fault", { scaleY: 0, transformOrigin: "50% 100%", duration: 0.7, ease: "power2.inOut" });
        step(".sw-fault-label", { opacity: 0, x: -8, duration: 0.4 });
        tl.to({}, { duration: 0.6 });

        if (phone) {
          // On a phone the chart stays readable at 1000 px and the scroll pans across it like a camera:
          // into the storm window, out to NS31, then back to the evening before for the tech log.
          const track = root.current?.querySelector<HTMLElement>(".sw-track");
          const pan = (at: Date) => () => {
            const view = root.current?.clientWidth ?? 0;
            const wide = track?.scrollWidth ?? W;
            return gsap.utils.clamp(view - wide, 0, view / 2 - (wide / W) * g.x(at));
          };
          const winMid = win ? new Date((ms(win.start) + ms(win.end)) / 2) : g.facts.domain[0];
          const ns31At = focus ? new Date(focus.flight.sched_dep) : g.facts.domain[1];
          const faultAt = log?.at ?? g.facts.domain[0];
          tl.shiftChildren(0.8, true, tl.labels.fault);
          tl.fromTo(".sw-track", { x: pan(winMid) }, { x: pan(winMid), duration: 0.01 }, 0)
            .to(".sw-track", { x: pan(ns31At), duration: 0.7, ease: "power2.inOut" }, "ns31-=0.5")
            .to(".sw-track", { x: pan(new Date(faultAt.getTime() + 2.5 * 3600_000)), duration: 0.9, ease: "power2.inOut" }, "fault");
        }
      });
    },
    // Rebuilt as each part of the chart arrives (the run, then the Flight File's tech log and NS31).
    { scope: root, dependencies: [!!g, !!focus, !!win, !!log?.at, operated.length], revertOnUpdate: true },
  );

  // A reading that rides the gust line from the evening before to midnight, again and again: the time and
  // the gust in the latest METAR at that minute. Only while the chart is on screen, never with reduced motion.
  useEffect(() => {
    const path = gustRef.current;
    const head = headRef.current;
    const el = root.current;
    if (!g || !path || !head || !el || prefersReducedMotion()) return;
    const total = path.getTotalLength();
    const lut = Array.from({ length: 700 }, (_, i) => path.getPointAtLength((i / 699) * total));
    const yAt = (x: number) => {
      let lo = 0;
      let hi = lut.length - 1;
      while (hi - lo > 1) {
        const mid = (lo + hi) >> 1;
        if (lut[mid].x < x) lo = mid;
        else hi = mid;
      }
      const a = lut[lo];
      const b = lut[hi];
      return b.x === a.x ? a.y : a.y + ((x - a.x) / (b.x - a.x)) * (b.y - a.y);
    };
    const [d0, d1] = g.facts.domain.map((d) => d.getTime());
    const dot = head.querySelector<SVGCircleElement>("circle");
    const stem = head.querySelector<SVGLineElement>("line");
    const label = head.querySelector<SVGTextElement>("text");
    const PERIOD = 15000;
    let shownAt = "";
    let raf = 0;
    let t0 = performance.now();
    const loop = (now: number) => {
      raf = requestAnimationFrame(loop);
      head.style.opacity = drawn.current ? "1" : "0";
      if (!drawn.current) {
        t0 = now;
        return;
      }
      const t = d0 + (((now - t0) % PERIOD) / PERIOD) * (d1 - d0);
      const x = g.x(new Date(t));
      const y = yAt(x);
      head.setAttribute("transform", `translate(${x.toFixed(2)} 0)`);
      dot?.setAttribute("cy", y.toFixed(2));
      stem?.setAttribute("y1", (y + 6).toFixed(2));
      // the report nearest the reading, so the number matches where the dot sits on the line
      let obs = null;
      for (const o of g.series) if (!obs || Math.abs(o.at.getTime() - t) < Math.abs(obs.at.getTime() - t)) obs = o;
      const text = obs ? `${hhmm(obs.at.toISOString())}Z · ${obs.gust ? `gust ${obs.gust}` : `${obs.sknt ?? 0}`} kt` : "";
      if (label && text !== shownAt) {
        label.textContent = text;
        shownAt = text;
      }
      label?.setAttribute("y", (y - 14).toFixed(2));
    };
    const io = new IntersectionObserver(([e]) => {
      cancelAnimationFrame(raf);
      if (e.isIntersecting) raf = requestAnimationFrame(loop);
    });
    io.observe(el);
    return () => {
      cancelAnimationFrame(raf);
      io.disconnect();
    };
  }, [g]);

  const winLabel = win ? `${zulu(win.start)}–${zulu(win.end)}` : null;
  const aria = g && win ? `Gusts at Dublin from METAR, ${zulu(g.facts.domain[0].toISOString())} the evening before to midnight. The storm window ran ${winLabel}. ${focus ? `${focus.flight.number} was due out at ${zulu(focus.flight.sched_dep)}, after it.` : ""}` : "Gusts at Dublin from METAR, with the storm window.";

  return (
    <section ref={root} aria-label="The storm window at Dublin" data-section="window" className="relative bg-navy-950">
      <div className="mx-auto max-w-[1180px] px-5 pt-28 md:px-0 md:pt-36">
        <h2 className="text-balance display max-w-[16ch] text-[clamp(38px,5.4vw,88px)] text-cloud-50">
          The storm window closed at {win ? zulu(win.end) : <Pending ch={5} />}.
        </h2>
        <p className="mt-6 max-w-[50ch] text-[16.5px] leading-relaxed text-cloud-400 md:text-[19px]">
          Dublin&rsquo;s METAR puts the gusts above {limit ? <span className="figure text-cloud-100">{limit} kt</span> : "limits"}{win ? <> from <span className="figure text-cloud-100">{zulu(win.start)}</span> to <span className="figure text-cloud-100">{zulu(win.end)}</span></> : null}
          {earlier ? <>, after a shorter burst from <span className="figure text-cloud-100">{zulu(earlier.start)}</span></> : null}. {inside !== undefined ? count(inside) : <Pending ch={2} />} of the cancelled departures were inside that window.{" "}
          {focus ? (
            <>
              {focus.flight.number} was due out at <span className="figure text-cloud-100">{zulu(focus.flight.sched_dep)}</span>
              {margin !== null && margin > 0 ? <>, {duration(margin)} after it closed</> : null}.
            </>
          ) : null}
        </p>
      </div>

      <div className="sw-stage relative flex min-h-svh flex-col justify-center overflow-hidden py-10 md:overflow-visible">
        <div className="mx-auto w-full max-w-[1280px] overflow-x-auto px-0 md:overflow-visible md:px-12 motion-safe:overflow-visible" data-lenis-prevent-horizontal>
          <div className="sw-track w-max md:w-full">
            {g ? (
              <svg viewBox={`0 0 ${W} ${H}`} className="w-[1000px] max-w-none overflow-visible md:w-full" role="img" aria-label={aria}>
                <defs>
                  <pattern id="sw-hatch" width="8" height="8" patternUnits="userSpaceOnUse" patternTransform="rotate(45)">
                    <line x1="0" y1="0" x2="0" y2="8" stroke="#4f9fe0" strokeWidth="1" strokeOpacity="0.32" />
                  </pattern>
                  {/* rain inside the storm window: short streaks falling along their own slant (motion only) */}
                  <pattern id="sw-rain" width="16" height="30" patternUnits="userSpaceOnUse" patternTransform="rotate(14)">
                    <line x1="3" y1="0" x2="3" y2="9" stroke="#9cc8f0" strokeOpacity="0.5" strokeWidth="1" />
                    <line x1="11" y1="15" x2="11" y2="21" stroke="#9cc8f0" strokeOpacity="0.32" strokeWidth="1" />
                    {prefersReducedMotion() ? null : <animateTransform attributeName="patternTransform" type="translate" from="0 0" to="0 30" dur="0.75s" repeatCount="indefinite" additive="sum" />}
                  </pattern>
                  <linearGradient id="sw-gfill" x1="0" x2="0" y1="0" y2="1">
                    <stop offset="0" stopColor="#f4f6f9" stopOpacity="0.16" />
                    <stop offset="1" stopColor="#f4f6f9" stopOpacity="0" />
                  </linearGradient>
                </defs>

                {/* storm windows, computed by the engine from METAR */}
                {g.facts.windows.map((w, i) => {
                  const x0 = Math.max(M.l, g.x(w.start));
                  const x1 = Math.min(W - M.r, g.x(w.end));
                  if (x1 <= x0) return null;
                  return (
                    <g key={i} className="sw-window" style={{ transformBox: "fill-box" }}>
                      <rect x={x0} y={M.t - 12} width={x1 - x0} height={PLOT_BOTTOM - M.t + 12} fill="url(#sw-hatch)" />
                      <rect x={x0} y={M.t - 12} width={x1 - x0} height={PLOT_BOTTOM - M.t + 12} fill="#4f9fe0" fillOpacity={0.08} />
                      <rect x={x0} y={M.t - 12} width={x1 - x0} height={PLOT_BOTTOM - M.t + 12} fill="url(#sw-rain)" opacity={0.55} />
                    </g>
                  );
                })}
                {win ? (
                  <g className="sw-window-label">
                    <text x={g.x(new Date(win.end)) - 12} y={M.t + 8} textAnchor="end" className="tabular fill-metar text-[13.5px] font-medium">
                      Storm window {winLabel}
                    </text>
                    <text x={g.x(new Date(win.end)) - 12} y={M.t + 26} textAnchor="end" className="fill-cloud-500 text-[12px]">
                      computed by the engine from METAR
                    </text>
                  </g>
                ) : null}

                {/* axes */}
                <g className="sw-axis">
                  <line x1={M.l} x2={W - M.r} y1={PLOT_BOTTOM} y2={PLOT_BOTTOM} stroke="#33445e" />
                  {g.hours.map((h) => (
                    <g key={h.getTime()}>
                      <line x1={g.x(h)} x2={g.x(h)} y1={PLOT_BOTTOM} y2={PLOT_BOTTOM + 5} stroke="#33445e" />
                      <text x={g.x(h)} y={PLOT_BOTTOM + 21} textAnchor="middle" className="tabular fill-cloud-500 text-[12px]">
                        {hhmm(h.toISOString())}
                      </text>
                    </g>
                  ))}
                  {[20, 40, 60].map((v) => (
                    <g key={v}>
                      <line x1={M.l} x2={W - M.r} y1={g.y(v)} y2={g.y(v)} stroke="rgba(200,208,219,0.06)" />
                      <text x={M.l - 12} y={g.y(v) + 4} textAnchor="end" className="tabular fill-cloud-500 text-[11.5px]">
                        {v}
                      </text>
                    </g>
                  ))}
                  <text x={M.l - 12} y={M.t - 2} textAnchor="end" className="fill-cloud-500 text-[11.5px]">
                    kt
                  </text>
                  <line x1={g.x(g.midnight)} x2={g.x(g.midnight)} y1={M.t - 70} y2={ARR_Y + 10} stroke="#4f617a" strokeDasharray="2 4" />
                  <text x={g.x(g.midnight) - 10} y={M.t - 74} textAnchor="end" className="fill-cloud-500 font-mono text-[11px]">
                    {dayLabel(new Date(g.midnight.getTime() - 1))}
                  </text>
                  <text x={g.x(g.midnight) + 10} y={M.t - 74} className="fill-cloud-300 font-mono text-[11px]">
                    {dayLabel(g.midnight)}
                  </text>
                </g>

                {/* wind barbs from the reports, every three hours */}
                {g.barbs.map((b) => (
                  <g key={b.at.getTime()} className="sw-barb">
                    <path d={`${b.staff} ${b.feathers}`} stroke="#a5b0bf" strokeWidth="1.3" strokeLinecap="round" fill="none" />
                    <path d={b.pennants} fill="#a5b0bf" />
                  </g>
                ))}

                <path className="sw-fill" d={g.fill} fill="url(#sw-gfill)" />
                <path className="sw-mean" d={g.mean} fill="none" stroke="#73839a" strokeWidth="1.5" {...PLOTTED} />
                <path ref={gustRef} className="sw-gust" d={g.gust} fill="none" stroke="#f4f6f9" strokeWidth="2.4" strokeLinecap="round" strokeLinejoin="round" {...PLOTTED} />

                {g.facts.gustLimitKt ? (
                  <>
                    <line className="sw-limit" style={{ transformBox: "fill-box" }} x1={M.l} x2={W - M.r} y1={g.y(g.facts.gustLimitKt)} y2={g.y(g.facts.gustLimitKt)} stroke="#4f9fe0" strokeOpacity={0.7} strokeWidth="1.3" strokeDasharray="6 5" />
                    <text x={W - M.r} y={g.y(g.facts.gustLimitKt) - 8} textAnchor="end" className="sw-limit-label tabular fill-metar text-[12.5px]">
                      gust limit {g.facts.gustLimitKt} kt
                    </text>
                  </>
                ) : null}
                <g className="sw-axis" transform={`translate(${W - M.r - 150} ${M.t - 6})`}>
                  <line x1="0" x2="18" y1="0" y2="0" stroke="#f4f6f9" strokeWidth="2.4" strokeLinecap="round" />
                  <text x="26" y="4" className="fill-cloud-400 text-[12px]">
                    gusts
                  </text>
                  <line x1="80" x2="98" y1="0" y2="0" stroke="#73839a" strokeWidth="1.5" />
                  <text x="106" y="4" className="fill-cloud-400 text-[12px]">
                    wind
                  </text>
                </g>

                {/* lanes */}
                <g className="sw-lane">
                  <line x1={M.l} x2={W - M.r} y1={DEP_Y} y2={DEP_Y} stroke="#1f2d45" />
                  <line x1={M.l} x2={W - M.r} y1={ARR_Y} y2={ARR_Y} stroke="#1f2d45" />
                  <text x={M.l - 12} y={DEP_Y + 4} textAnchor="end" className="fill-cloud-500 font-mono text-[10.5px]">
                    DEP
                  </text>
                  <text x={M.l - 12} y={ARR_Y + 4} textAnchor="end" className="fill-cloud-500 font-mono text-[10.5px]">
                    ARR
                  </text>
                </g>

                {/* cancelled: coded as OCC typed them, then settled by the re-check */}
                {g.facts.ticks
                  .filter((t) => t.verdict !== "operated" && !t.recoded && t.at >= g.facts.domain[0] && t.at <= g.facts.domain[1])
                  .map((t) => (
                    <g key={t.id} className="sw-tick" data-flight={t.number}>
                      <circle className="sw-tick-dot" cx={g.x(t.at)} cy={t.lane === "dep" ? DEP_Y : ARR_Y} r="5.5" fill={TONE[t.verdict]} />
                    </g>
                  ))}

                {/* operated after the window: they flew */}
                {g.facts.ticks
                  .filter((t) => t.verdict === "operated" && t.lane === "dep")
                  .map((t) => (
                    <rect key={t.id} className="sw-op" x={g.x(t.at) - 1.5} y={DEP_Y - 8} width="3" height="16" rx="1" fill={TONE.operated} />
                  ))}
                {opFirst && opLast ? (
                  <text x={(g.x(new Date(opFirst.flight.sched_dep)) + g.x(new Date(opLast.flight.sched_dep))) / 2} y={DEP_Y - 17} textAnchor="middle" className="sw-op-label tabular fill-slate-400 text-[12px]">
                    {count(operated.length)} departures flew {hhmm(opFirst.flight.sched_dep)}–{hhmm(opLast.flight.sched_dep)}Z
                  </text>
                ) : null}

                {/* NS31: after the window */}
                {focus && win ? (
                  <>
                    <g className="sw-ns31">
                      <circle cx={g.x(new Date(focus.flight.sched_dep))} cy={DEP_Y} r="8" fill={TONE.notweather} />
                      <circle className="sw-ns31-ring" cx={g.x(new Date(focus.flight.sched_dep))} cy={DEP_Y} r="15" fill="none" stroke={TONE.notweather} strokeOpacity="0.5" />
                    </g>
                    <g className="sw-margin" style={{ transformBox: "fill-box" }}>
                      <line x1={g.x(new Date(win.end))} x2={g.x(new Date(focus.flight.sched_dep))} y1={DEP_Y + 24} y2={DEP_Y + 24} stroke="#ff8d72" strokeWidth="1.2" />
                      <line x1={g.x(new Date(win.end))} x2={g.x(new Date(win.end))} y1={DEP_Y + 20} y2={DEP_Y + 28} stroke="#ff8d72" />
                      <line x1={g.x(new Date(focus.flight.sched_dep))} x2={g.x(new Date(focus.flight.sched_dep))} y1={DEP_Y + 20} y2={DEP_Y + 28} stroke="#ff8d72" />
                    </g>
                    <text x={g.x(new Date(focus.flight.sched_dep)) + 22} y={DEP_Y + 28} className="sw-margin-label fill-[#ff8d72] text-[12.5px]">
                      <tspan className="tabular font-medium">{focus.flight.number} {zulu(focus.flight.sched_dep)}</tspan>
                      {margin !== null ? <tspan className="fill-cloud-300"> · {duration(margin)} after the window</tspan> : null}
                    </text>
                  </>
                ) : null}

                {/* the reading that rides the gust line (positioned by the effect above) */}
                <g ref={headRef} className="sw-head" style={{ opacity: 0, transition: "opacity 0.4s" }} aria-hidden="true">
                  <line x1="0" x2="0" y1={M.t} y2={PLOT_BOTTOM} stroke="#f4f6f9" strokeOpacity="0.35" strokeDasharray="2 3" />
                  <circle cx="0" cy={PLOT_BOTTOM} r="4.5" fill="#f4f6f9" stroke="#080d17" strokeWidth="2" />
                  <text x="0" y={PLOT_BOTTOM} textAnchor="middle" className="tabular fill-cloud-100 font-mono text-[11.5px]" style={{ paintOrder: "stroke", stroke: "#080d17", strokeWidth: 4, strokeLinejoin: "round" }} />
                </g>

                {/* the tech log, the evening before */}
                {log?.at ? (
                  <>
                    <path className="sw-fault" style={{ transformBox: "fill-box" }} d={`M${g.x(log.at)},${DEP_Y} L${g.x(log.at)},${M.t - 30}`} stroke={TONE.notweather} strokeWidth="1.6" strokeDasharray="3 4" />
                    <g className="sw-fault-label">
                      <rect x={g.x(log.at) + 10} y={M.t - 30} width="300" height="70" rx="4" fill="#160d10" stroke={TONE.notweather} strokeOpacity="0.55" />
                      <text x={g.x(log.at) + 22} y={M.t - 10} className="tabular fill-[#ff8d72] text-[12.5px] font-medium tracking-[0.02em]">
                        TECH LOG · {zulu(log.at.toISOString())} · {focus?.flight.aircraft ?? ""}
                      </text>
                      <text x={g.x(log.at) + 22} y={M.t + 9} className="fill-cloud-50 font-mono text-[12px]">
                        {ecamOf(log.quote) ?? ""}
                      </text>
                      <text x={g.x(log.at) + 22} y={M.t + 28} className="fill-cloud-400 text-[12px]">
                        {logObs ? `${hub ?? ""} then: ${logObs.sknt ?? "—"} kt${logObs.gust ? `, gusts ${logObs.gust} kt` : ", no gusts"}` : ""}
                      </text>
                    </g>
                  </>
                ) : null}
              </svg>
            ) : (
              <div className={cn("mx-auto aspect-[1200/560] w-[1000px] max-w-none animate-pulse rounded-xl bg-white/[0.03] md:w-full")} aria-hidden="true" />
            )}
          </div>
        </div>
        <div className="sw-legend mx-auto mt-2 flex w-full max-w-[1280px] flex-wrap gap-x-6 gap-y-2 px-5 text-[12.5px] text-cloud-400 md:px-12 md:pl-[calc(3rem+70px*var(--sw-scale,1))]">
          {[
            ["weather", "weather: no compensation; refunds and care still due"],
            ["held", "held: one question to Legal"],
            ["notweather", "not weather"],
          ].map(([tone, label]) => (
            <span key={tone} className="flex items-center gap-2">
              <span className="size-2 rounded-full" style={{ background: TONE[tone as keyof typeof TONE] }} aria-hidden="true" />
              {label}
            </span>
          ))}
          <span className="flex items-center gap-2">
            <span className="h-3 w-[3px] rounded-sm" style={{ background: TONE.operated }} aria-hidden="true" />
            operated
          </span>
        </div>
      </div>
    </section>
  );
}
