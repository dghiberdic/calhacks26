import { Fragment, useEffect, useRef, useState } from "react";
import { Link } from "react-router";
import { motion, useReducedMotion } from "motion/react";
import { ArrowRight } from "lucide-react";
import type { StormRun } from "@/api/types";
import { ConfidenceLine } from "@/components/kit";
import { mainWindowOf } from "@/components/storm/model";
import { StormTimeline } from "@/components/storm/StormTimeline";
import { RouteLegend } from "@/components/storm/RouteMap";
import { count, longDate, zulu } from "@/lib/format";
import { stormName } from "@/lib/storms";

const plural = (n: number | undefined, one: string, many: string) => `${count(n)} ${n === 1 ? one : many}`;

/** "Real context · EIDW, 24 Jan 2025 · 179 departures (Eurocontrol) vs ~292–316 normal · ~119 cancelled (reported) · red warning 06:00–11:00". */
function RealContext({ run }: { run: StormRun }) {
  const rc = (run.real_context ?? {}) as Record<string, unknown>;
  const parts: string[] = [];
  if (rc.eurocontrol_departures !== undefined) parts.push(`${count(Number(rc.eurocontrol_departures))} departures (Eurocontrol)${rc.normal_departures ? ` vs ${String(rc.normal_departures)} normal` : ""}`);
  if (rc.reported_cancellations_dep !== undefined) parts.push(`~${count(Number(rc.reported_cancellations_dep))} cancelled (reported)`);
  if (rc.red_warning) parts.push(`red warning ${String(rc.red_warning).replace("-", "–")}`);
  if (rc.orange_warning) parts.push(`orange ${String(rc.orange_warning)}`);
  if (!parts.length) return null;
  return (
    <p className="max-w-[90ch] font-mono text-[11px] leading-relaxed text-cloud-500">
      <span className="text-cloud-300">Real context</span> · {run.station}, {longDate(run.date)} · {parts.join(" · ")}
    </p>
  );
}

export function Hero({ run, onSelectFlight }: { run: StormRun; onSelectFlight: (id: string) => void }) {
  const reduce = useReducedMotion();
  // The callout lands once the timeline has settled (about 4 s), per storm.
  const [settledFor, setSettledFor] = useState<string | null>(null);
  useEffect(() => {
    if (reduce) return;
    const t = window.setTimeout(() => setSettledFor(run.id), 4200);
    return () => window.clearTimeout(t);
  }, [reduce, run.id]);
  const settled = !!reduce || settledFor === run.id;
  const pan = useRef<HTMLDivElement>(null);
  useEffect(() => {
    const el = pan.current;
    if (el && el.scrollWidth > el.clientWidth) el.scrollLeft = el.scrollWidth;
  }, [run.id]);

  const c = run.counters ?? {};
  const name = run.name ?? (run.real_context?.storm_name as string | undefined) ?? (run.real_context?.name as string | undefined) ?? stormName(run.id);
  const focus = run.flights.find((r) => r.decision?.recoded);
  const window0 = mainWindowOf(run.windows);
  const knownAt = run.flights.find((r) => r.decision)?.decision?.known_at;
  const headline = [plural(c.passengers, "passenger", "passengers"), plural(c.questions, "question", "questions"), plural(c.people, "person", "people")];

  return (
    <section className="relative overflow-hidden rounded-2xl bg-navy-900 text-cloud-50 shadow-[0_20px_60px_-20px_rgba(8,13,23,0.55)]" aria-label="Storm run">
      {/* soft storm light, decoration only */}
      <div aria-hidden="true" className="pointer-events-none absolute -right-40 -top-48 size-[560px] rounded-full bg-[radial-gradient(closest-side,rgba(79,159,224,0.15),transparent)]" />
      <div className="relative px-5 pb-5 pt-6 md:px-8 md:pt-8">
        <p className="micro text-cloud-500">
          {name ? `${name} · ` : ""}
          {run.station} · {longDate(run.date)}
          {knownAt ? ` · re-checked ${zulu(knownAt)}` : ""}
        </p>
        {/* One line on a laptop; on a phone the three counts stack, without the dots. */}
        <h1 className="display mt-3 flex flex-col text-[clamp(32px,3.3vw,48px)] leading-[1.04] text-cloud-50 sm:block" data-testid="storm-headline">
          {headline.map((part, i) => (
            <Fragment key={part}>
              <span className="whitespace-nowrap">
                {part}
                {i < headline.length - 1 ? <span className="hidden text-cloud-500 sm:inline"> ·</span> : null}
              </span>{" "}
            </Fragment>
          ))}
        </h1>

        <div className="mt-4 grid items-start gap-5 lg:grid-cols-[minmax(0,1fr)_300px]">
          <p className="max-w-[62ch] text-[15px] leading-relaxed text-cloud-400">
            OCC coded {c.cancelled === undefined ? "every cancellation" : `all ${count(c.cancelled)} cancellations`} weather. StormCheck re-checked each against the airport&rsquo;s METAR and the aircraft&rsquo;s own logs
            {window0 ? (
              <>
                : the storm window ran {zulu(window0.start)}–{zulu(window0.end)}
                {c.operated ? <>, and {plural(c.operated, "departure", "departures")} operated after it</> : null}
              </>
            ) : null}
            .
          </p>

          {focus ? (
            <motion.div
              initial={false}
              animate={settled ? { opacity: 1, y: 0 } : { opacity: 0, y: 8 }}
              transition={{ duration: 0.6, ease: [0.16, 1, 0.3, 1] }}
              className="rounded-xl bg-navy-950/70 p-4 ring-1 ring-white/10 backdrop-blur-sm"
              data-testid="not-weather-callout"
              aria-live="polite"
            >
              <p className="display-tight text-[26px] leading-[1.05] text-cloud-50">
                <span className="block">Not weather.</span>
                <span className="block text-notweather">Broken plane.</span>
              </p>
              <p className="mt-2 font-mono text-[12px] text-cloud-300">
                {focus.flight.number} {focus.flight.origin}–{focus.flight.dest} · <span className="text-notweather">{focus.decision?.recode_label}</span> · {plural(focus.flight.pax, "passenger", "passengers")}
              </p>
              {focus.decision ? <ConfidenceLine confidence={focus.decision.confidence} reason={focus.decision.reason} showCaps={false} className="mt-2 text-cloud-400 [&_span.font-bold]:text-cloud-50" /> : null}
              <Link to={`/flights/${encodeURIComponent(focus.flight.id)}`} className="mt-3 inline-flex items-center gap-1.5 text-[13px] font-medium text-cloud-50 hover:underline" tabIndex={settled ? 0 : -1}>
                Open the flight file <ArrowRight className="size-3.5" aria-hidden="true" />
              </Link>
            </motion.div>
          ) : null}
        </div>

        {/* Phones pan the timeline instead of squeezing 30 hours into 350 px; it opens on the window's end and NS31. */}
        <div ref={pan} className="-mx-5 mt-6 overflow-x-auto px-5 [scrollbar-width:none] md:mx-0 md:overflow-visible md:px-0">
          <div className="min-w-[700px] md:min-w-0">
            <StormTimeline run={run} tone="dark" onSelectFlight={onSelectFlight} />
          </div>
        </div>
        <p className="mt-1 font-mono text-[10.5px] text-cloud-500 md:hidden">← swipe back to the evening before: the fault was logged at the red line</p>
        <div className="mt-3 flex flex-wrap items-center justify-between gap-x-6 gap-y-2 border-t border-white/[0.06] pt-3">
          <RouteLegend tone="dark" />
          <RealContext run={run} />
        </div>
        {run.message ? <p className="mt-3 font-mono text-[12px] text-cloud-400">{run.message}</p> : null}
      </div>
    </section>
  );
}
