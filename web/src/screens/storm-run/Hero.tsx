import { Fragment, useEffect, useRef, useState } from "react";
import { Link } from "react-router";
import { motion, useReducedMotion } from "motion/react";
import { ArrowRight } from "lucide-react";
import type { StormRun } from "@/api/types";
import { Explain } from "@/components/explain";
import { FaultLine } from "@/components/fault-line";
import { ConfidenceLine, Details } from "@/components/kit";
import { mainWindowOf, windowName } from "@/components/storm/model";
import { StormTimeline } from "@/components/storm/StormTimeline";
import { RouteLegend } from "@/components/storm/RouteMap";
import { VERDICT_COLOR } from "@/components/verdict";
import { airport, iataOf } from "@/lib/airports";
import { count, longDate, zulu } from "@/lib/format";
import { stormName } from "@/lib/storms";
import { stormStory } from "./story";

const plural = (n: number | undefined, one: string, many: string) => `${count(n)} ${n === 1 ? one : many}`;
const placeOf = (station: string) => airport(iataOf(station))?.name.replace(/ Airport$/, "") ?? station;

/** "179 departures (Eurocontrol) vs 292–316 normal · ~119 cancelled (reported) · red warning 06:00–11:00". */
function RealContext({ run }: { run: StormRun }) {
  const rc = (run.real_context ?? {}) as Record<string, unknown>;
  const parts: string[] = [];
  if (rc.eurocontrol_departures !== undefined) parts.push(`${count(Number(rc.eurocontrol_departures))} departures that day (Eurocontrol)${rc.normal_departures ? `, against ${String(rc.normal_departures)} on a normal day` : ""}`);
  if (rc.reported_cancellations_dep !== undefined) parts.push(`about ${count(Number(rc.reported_cancellations_dep))} cancelled across all airlines (reported)`);
  if (rc.red_warning) parts.push(`Met Éireann red warning ${String(rc.red_warning).replace("-", "–")}`);
  if (rc.orange_warning) parts.push(`orange ${String(rc.orange_warning)}`);
  if (!parts.length) return null;
  return (
    <Details dark summary="Real-world context">
      <p className="max-w-[90ch] text-[12.5px] leading-relaxed text-cloud-400">
        {run.station}, {longDate(run.date)}: {parts.join("; ")}. The weather, traffic and EU law are real; Northstar&rsquo;s flights, logs and passengers are simulated on top.
      </p>
    </Details>
  );
}

/** "Reused 2 learned rules: 31 cases settled without asking." Runs after the first only. */
function ReuseLine({ reuse }: { reuse: { rules: number; cases: number } }) {
  return (
    <p className="mt-3 flex items-start gap-2 text-[14px] leading-relaxed text-cloud-300" data-testid="reuse-line">
      <span aria-hidden="true" className="font-mono text-cloud-500">
        ↻
      </span>
      <span>
        <Link to="/policies" className="text-cloud-100 underline decoration-white/30 underline-offset-[3px] hover:decoration-white">
          Reused {plural(reuse.rules, "learned rule", "learned rules")}
        </Link>
        : {plural(reuse.cases, "case", "cases")} settled without asking.
      </span>
    </p>
  );
}

export function Hero({ run, onSelectFlight, reuse }: { run: StormRun; onSelectFlight: (id: string) => void; reuse?: { rules: number; cases: number } | null }) {
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

  const name = run.name ?? (run.real_context?.storm_name as string | undefined) ?? (run.real_context?.name as string | undefined) ?? stormName(run.id);
  const focus = run.flights.find((r) => r.decision?.recoded);
  const window0 = mainWindowOf(run.windows);
  const story = stormStory(run);
  const operated = run.counters?.operated;

  return (
    <section className="relative overflow-hidden rounded-2xl bg-navy-900 text-cloud-50 shadow-[0_20px_60px_-20px_rgba(8,13,23,0.55)]" aria-label="Storm run">
      {/* soft storm light, decoration only */}
      <div aria-hidden="true" className="pointer-events-none absolute -right-40 -top-48 size-[560px] rounded-full bg-[radial-gradient(closest-side,rgba(79,159,224,0.15),transparent)]" />
      <div className="relative px-5 pb-5 pt-6 md:px-8 md:pt-8">
        <p className="micro text-cloud-500">
          {name ? `${name} · ` : ""}
          {placeOf(run.station)} · {longDate(run.date)}
        </p>

        <div className="mt-3 grid items-start gap-6 lg:grid-cols-[minmax(0,1fr)_300px]">
          <div className="min-w-0">
            <h1 className="display text-balance text-[clamp(28px,2.7vw,40px)] leading-[1.08] text-cloud-50" data-testid="storm-headline">
              {plural(story.cancelled, "flight", "flights")} cancelled, {plural(story.passengers, "passenger", "passengers")} stranded
              {story.outage ? ": a power cut, not a storm." : <>, all coded &lsquo;weather&rsquo;.</>}
            </h1>
            <p className="mt-4 max-w-[64ch] text-[16px] leading-relaxed text-cloud-300" data-testid="storm-story">
              StormCheck checked each one against{" "}
              {story.outage ? (
                <>
                  the <Explain term="grid-outage">grid outage window</Explain>
                </>
              ) : (
                <>
                  the real airport weather (<Explain term="metar">METAR</Explain>)
                </>
              )}{" "}
              and the airline&rsquo;s own logs.{" "}
              {story.parts.map((p, i) => (
                <Fragment key={p.kind}>
                  <span className="whitespace-nowrap">
                    <span className="mr-1.5 inline-block size-2 rounded-full align-middle" style={{ background: VERDICT_COLOR[p.kind] }} aria-hidden="true" />
                    <span className={p.kind === "notweather" ? "font-semibold text-cloud-50" : "text-cloud-100"}>{p.text}</span>
                  </span>
                  {i < story.parts.length - 1 ? (i === story.parts.length - 2 ? ", and " : ", ") : "."}
                </Fragment>
              ))}
            </p>
            {reuse ? <ReuseLine reuse={reuse} /> : null}
          </div>

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
                {focus.flight.number} {focus.flight.origin}–{focus.flight.dest} ·{" "}
                <Explain term="delay-codes" className="text-notweather">
                  {focus.decision?.recode_label}
                </Explain>
              </p>
              {focus.decision ? <p className="mt-2 text-[13px] leading-snug text-cloud-300"><FaultLine decision={focus.decision} /></p> : null}
              {focus.decision ? <ConfidenceLine confidence={focus.decision.confidence} showCaps={false} className="mt-2 text-cloud-400 [&_span.font-bold]:text-cloud-50" /> : null}
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
        <div className="mt-3 flex flex-col gap-3 border-t border-white/[0.06] pt-3">
          <div className="flex flex-wrap items-center justify-between gap-x-6 gap-y-2">
            <RouteLegend tone="dark" />
            {window0 ? (
              <p className="text-[12.5px] text-cloud-400">
                <Explain term={story.outage ? "grid-outage" : "storm-window"}>{windowName(window0)}</Explain> {zulu(window0.start)}–{zulu(window0.end)}
                {operated ? <>; {plural(operated, "flight", "flights")} operated after it</> : null}. Each tick is a flight at its scheduled time.
              </p>
            ) : null}
          </div>
          <RealContext run={run} />
        </div>
        {run.message ? <p className="mt-3 font-mono text-[12px] text-cloud-400">{run.message}</p> : null}
      </div>
    </section>
  );
}
