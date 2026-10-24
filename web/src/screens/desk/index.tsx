import { useEffect, useRef } from "react";
import { useSearchParams } from "react-router";
import { motion, useReducedMotion } from "motion/react";
import { Loader2 } from "lucide-react";
import { MicroLabel } from "@/components/chips";
import { PageHeader } from "@/components/kit";
import { cn } from "@/lib/utils";
import { airportByIcao, choiceLabel, ICAO_SHAPE } from "./airports";
import { dayLabel, editLabel, isValidDate, parts } from "./dates";
import { DayForm } from "./DayForm";
import { DayResult } from "./DayResult";
import { InjectPanel } from "./InjectPanel";
import { useDesk } from "./state";

/**
 * J7 · Judge's Desk. "Name an airport and a date": real METAR → a run of that day, then hand the
 * Reader a document of your own and watch what it changes. Plan §3 screen 7, §4 beat 2:00.
 */
export default function DeskScreen() {
  const run = useDesk((s) => s.run);
  const ranFor = useDesk((s) => s.ranFor);
  const pending = useDesk((s) => s.pending);
  usePrefillFromUrl();

  return (
    <div className="mx-auto flex max-w-[1280px] flex-col gap-3">
      <PageHeader eyebrow={<MicroLabel>Judge&rsquo;s Desk · real METAR</MicroLabel>} title="Name an airport and a date." className="mb-2">
        StormCheck pulls that day&rsquo;s METAR, runs Northstar&rsquo;s flights to and from the airport through the engine, and drafts what&rsquo;s owed. Then hand it a document of your own.
      </PageHeader>

      <DayForm />

      <div aria-busy={!!pending}>
        {run ? (
          // A new run dims the last one instead of replacing it, so a plain 422 leaves the old day exactly as it was.
          <div className="relative">
            <div className={cn("transition-opacity duration-200", pending && "pointer-events-none opacity-40 saturate-50")} aria-hidden={pending ? true : undefined}>
              <DayResult key={`${run.id}-${ranFor?.date ?? ""}`} run={run} />
            </div>
            {pending ? <RunningPill icao={pending.icao} date={pending.date} /> : null}
          </div>
        ) : pending ? (
          <RunSkeleton icao={pending.icao} />
        ) : (
          <Idle />
        )}
      </div>

      <div className="mt-6">
        <InjectPanel />
      </div>
    </div>
  );
}

/**
 * `/desk?icao=EGLL&date=2024-01-21` fills the form on arrival (it doesn't run: the person presses
 * Enter). After each run the URL names that day, so it can be shared; a run that was already on
 * screen when the page opened never overwrites the link someone followed.
 */
function usePrefillFromUrl() {
  const [params, setParams] = useSearchParams();
  const ranAt = useDesk((s) => s.ranFor?.at);
  const synced = useRef(ranAt);

  useEffect(() => {
    const s = useDesk.getState();
    const icao = params.get("icao")?.toUpperCase();
    const date = params.get("date");
    if (icao && ICAO_SHAPE.test(icao) && icao !== s.airport?.icao) {
      const choice = { icao, airport: airportByIcao(icao) };
      s.setAirport(choice, choiceLabel(choice));
    }
    if (date && /^\d{4}-\d{2}-\d{2}$/.test(date) && date !== s.date) {
      const { y, m, d } = parts(date);
      if (isValidDate(y, m, d)) s.setDate(date, editLabel(date));
    }
    // Arrival only.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  useEffect(() => {
    if (!ranAt || ranAt === synced.current) return;
    synced.current = ranAt;
    const ranFor = useDesk.getState().ranFor;
    if (ranFor) setParams({ icao: ranFor.icao, date: ranFor.date }, { replace: true });
  }, [ranAt, setParams]);
}

/** Over the dimmed last run: which day is on its way. */
function RunningPill({ icao, date }: { icao: string; date: string }) {
  const a = airportByIcao(icao);
  return (
    <div className="pointer-events-none absolute inset-x-0 top-6 flex justify-center" role="status">
      <span className="inline-flex items-center gap-2 rounded-full bg-navy-950 px-4 py-2 text-[13px] text-cloud-50 shadow-lg ring-1 ring-white/10">
        <Loader2 className="size-3.5 animate-spin text-metar" aria-hidden="true" />
        Running {a ? `${a.iata} · ${a.name}` : icao}, {dayLabel(date)}
      </span>
    </div>
  );
}

/** Before the first run: the instrument, idle. */
function Idle() {
  return (
    <section className="relative overflow-hidden rounded-2xl bg-navy-900 px-5 py-8 text-cloud-50 md:px-8" aria-label="No run yet" data-testid="desk-idle">
      <IdleTrace />
      <div className="relative max-w-[56ch]">
        <p className="micro text-cloud-500">Readout</p>
        <p className="display-tight mt-2 text-[22px] text-cloud-100 md:text-[26px]">Your day lands here.</p>
        <p className="mt-2 text-[14px] leading-relaxed text-cloud-400">
          The wind from that airport&rsquo;s METAR, any storm window it meets, every Northstar flight that day with its verdict, and the EU261 compensation liability drafted. Try a quick pick if you&rsquo;re short of a date.
        </p>
      </div>
    </section>
  );
}

/** A flat, faint trace: decoration only, no data. */
function IdleTrace() {
  return (
    <svg aria-hidden="true" className="pointer-events-none absolute inset-x-0 bottom-0 h-[70%] w-full" preserveAspectRatio="none" viewBox="0 0 1000 200">
      {Array.from({ length: 9 }, (_, i) => (
        <line key={i} x1={(i + 1) * 100} x2={(i + 1) * 100} y1={20} y2={200} stroke="rgba(200,208,219,0.05)" />
      ))}
      {Array.from({ length: 4 }, (_, i) => (
        <line key={`h${i}`} x1={0} x2={1000} y1={40 + i * 45} y2={40 + i * 45} stroke="rgba(200,208,219,0.05)" />
      ))}
      <path d="M0 168 C 120 160, 220 172, 330 164 S 560 158, 680 166 S 880 160, 1000 164" fill="none" stroke="rgba(238,242,247,0.18)" strokeWidth={1.5} />
    </svg>
  );
}

/** While the server works: the readout's shape, with a sweep across where the METAR will draw. */
function RunSkeleton({ icao }: { icao: string }) {
  const reduce = useReducedMotion();
  return (
    <div className="flex flex-col gap-3" data-testid="desk-run-skeleton" role="status" aria-label={`Running ${icao}`}>
      <section className="relative overflow-hidden rounded-2xl bg-navy-900 px-4 pb-5 pt-6 md:px-7">
        <div className="h-3 w-56 animate-pulse rounded bg-white/[0.07]" />
        <div className="mt-4 h-8 w-[min(520px,80%)] animate-pulse rounded-md bg-white/[0.08]" />
        <div className="mt-4 flex gap-2">
          <div className="h-6 w-36 animate-pulse rounded-md bg-metar/15" />
          <div className="h-6 w-64 animate-pulse rounded-md bg-metar/10" />
        </div>
        <div className="relative mt-6 h-[230px] overflow-hidden rounded-lg md:h-[300px]">
          {Array.from({ length: 5 }, (_, i) => (
            <div key={i} className="absolute inset-x-0 h-px bg-white/[0.05]" style={{ top: `${(i + 1) * 16}%` }} />
          ))}
          {!reduce ? (
            <motion.div
              className="absolute inset-y-0 w-[18%] bg-gradient-to-r from-transparent via-metar/[0.13] to-transparent"
              initial={{ left: "-20%" }}
              animate={{ left: "105%" }}
              transition={{ duration: 1.8, repeat: Infinity, ease: "easeInOut" }}
            />
          ) : null}
        </div>
      </section>
      <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-4">
        {Array.from({ length: 4 }, (_, i) => (
          <div key={i} className="h-[112px] animate-pulse rounded-xl bg-cloud-100" />
        ))}
      </div>
    </div>
  );
}
