import { useEffect, useState } from "react";
import { Link } from "react-router";
import { AnimatePresence, motion, useReducedMotion } from "motion/react";
import { ArrowRight } from "lucide-react";
import type { StormRun } from "@/api/types";
import { ConfidenceLine } from "@/components/kit";
import { StormTimeline } from "@/components/storm/StormTimeline";
import { RouteLegend } from "@/components/storm/RouteMap";
import { count, longDate, zulu } from "@/lib/format";
import { stormName } from "@/lib/storms";

/** "Dublin, 24 Jan 2025 · 179 departures (Eurocontrol) vs ~300 normal · ~119 cancelled (reported) · red warning 06:00–11:00". */
function RealContext({ run }: { run: StormRun }) {
  const rc = (run.real_context ?? {}) as Record<string, unknown>;
  const parts: string[] = [];
  if (rc.eurocontrol_departures !== undefined) parts.push(`${count(Number(rc.eurocontrol_departures))} departures (Eurocontrol)${rc.normal_departures ? ` vs ${String(rc.normal_departures)} normal` : ""}`);
  if (rc.reported_cancellations_dep !== undefined) parts.push(`~${count(Number(rc.reported_cancellations_dep))} cancelled (reported)`);
  if (rc.red_warning) parts.push(`red warning ${String(rc.red_warning).replace("-", "–")}`);
  if (rc.orange_warning) parts.push(`orange ${String(rc.orange_warning)}`);
  if (!parts.length) return null;
  return (
    <p className="font-mono text-[11.5px] leading-relaxed text-cloud-500">
      <span className="text-cloud-300">Real context</span> · {run.station}, {longDate(run.date)} · {parts.join(" · ")}
    </p>
  );
}

export function Hero({ run, onSelectFlight }: { run: StormRun; onSelectFlight: (id: string) => void }) {
  const reduce = useReducedMotion();
  const [settled, setSettled] = useState(!!reduce);
  useEffect(() => {
    if (reduce) return;
    const t = window.setTimeout(() => setSettled(true), 4200);
    return () => window.clearTimeout(t);
  }, [reduce, run.id]);

  const c = run.counters ?? {};
  const name = stormName(run.id);
  const recoded = run.flights.filter((r) => r.decision?.recoded);
  const focus = recoded[0];
  const window0 = run.windows[0];
  const knownAt = run.flights.find((r) => r.decision)?.decision?.known_at;

  return (
    <section className="relative overflow-hidden rounded-2xl bg-navy-900 text-cloud-50 shadow-[0_20px_60px_-20px_rgba(8,13,23,0.55)]" aria-label="Storm run">
      {/* soft storm light, decoration only */}
      <div aria-hidden="true" className="pointer-events-none absolute -right-40 -top-40 size-[520px] rounded-full bg-[radial-gradient(closest-side,rgba(79,159,224,0.16),transparent)]" />
      <div className="relative px-5 pb-5 pt-6 md:px-8 md:pt-8">
        <div className="flex flex-wrap items-start justify-between gap-6">
          <div className="min-w-0 max-w-[760px]">
            <p className="micro text-cloud-500">
              {name ? `${name} · ` : ""}
              {run.station} · {longDate(run.date)}
              {knownAt ? ` · re-checked ${zulu(knownAt)}` : ""}
            </p>
            <h1 className="display mt-3 text-[34px] text-cloud-50 md:text-[46px]" data-testid="storm-headline">
              {count(c.passengers)} passengers <span className="text-cloud-500">·</span> {count(c.questions)} questions <span className="text-cloud-500">·</span> {count(c.people)} people
            </h1>
            <p className="mt-3 max-w-[64ch] text-[15px] leading-relaxed text-cloud-400">
              OCC coded {c.cancelled === undefined ? "every" : `all ${count(c.cancelled)}`} cancellations weather. StormCheck re-checked each against the airport&rsquo;s METAR and the aircraft&rsquo;s own logs
              {window0 ? (
                <>
                  : the storm window ran {zulu(window0.start)}–{zulu(window0.end)}
                  {c.operated ? <>, and {count(c.operated)} departures operated after it</> : null}
                </>
              ) : null}
              .
            </p>
          </div>

          <AnimatePresence>
            {settled && focus ? (
              <motion.div
                initial={{ opacity: 0, y: 10 }}
                animate={{ opacity: 1, y: 0 }}
                transition={{ duration: 0.6, ease: [0.16, 1, 0.3, 1] }}
                className="w-full max-w-[340px] rounded-xl bg-navy-950/70 p-4 ring-1 ring-white/10 backdrop-blur-sm"
                data-testid="not-weather-callout"
              >
                <p className="display-tight text-[22px] leading-tight text-cloud-50">
                  Not weather. <span className="text-notweather">Broken plane.</span>
                </p>
                <p className="mt-2 font-mono text-[12px] text-cloud-300">
                  {focus.flight.number} {focus.flight.origin}–{focus.flight.dest} · <span className="text-notweather">{focus.decision?.recode_label}</span> · {count(focus.flight.pax)} passengers
                </p>
                {focus.decision ? <ConfidenceLine confidence={focus.decision.confidence} reason={focus.decision.reason} showCaps={false} className="mt-2 text-cloud-400 [&_span.font-bold]:text-cloud-50" /> : null}
                <Link to={`/flights/${encodeURIComponent(focus.flight.id)}`} className="mt-3 inline-flex items-center gap-1.5 text-[13px] font-medium text-cloud-50 hover:underline">
                  Open the flight file <ArrowRight className="size-3.5" aria-hidden="true" />
                </Link>
              </motion.div>
            ) : null}
          </AnimatePresence>
        </div>

        <div className="mt-6">
          <StormTimeline run={run} tone="dark" onSelectFlight={onSelectFlight} />
        </div>
        <div className="mt-3 flex flex-wrap items-center justify-between gap-3 border-t border-white/[0.06] pt-3">
          <RouteLegend tone="dark" />
          <RealContext run={run} />
        </div>
        {run.message ? <p className="mt-3 font-mono text-[12px] text-cloud-400">{run.message}</p> : null}
      </div>
    </section>
  );
}
