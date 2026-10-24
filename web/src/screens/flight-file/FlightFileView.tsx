import { useLayoutEffect, useMemo, useRef, useState, type ReactNode } from "react";
import { Link } from "react-router";
import { MotionConfig } from "motion/react";
import { ApiError } from "@/api/client";
import { useFlightFile, useStormRun, useStorms } from "@/api/queries";
import type { Flight, FlightFile, MetarObs, StormSummary, StormWindow } from "@/api/types";
import { EvidenceList, TIER_NAME } from "@/components/evidence";
import { Empty, ErrorNote, Shimmer } from "@/components/kit";
import { verdictOf } from "@/components/verdict";
import { longDate, shortId, zuluDay } from "@/lib/format";
import { iataOf } from "@/lib/airports";
import { stormName } from "@/lib/storms";
import { ChallengePanel } from "./ChallengePanel";
import { weatherDefence } from "./defence";
import { WeatherDefenceRows } from "./WeatherDefence";
import { ConfidenceCard } from "./ConfidenceCard";
import { FlightTimeline } from "./FlightTimeline";
import { JournalDrafts } from "./JournalDrafts";
import { MoneyCard } from "./MoneyCard";
import { PassengersPanel } from "./PassengersPanel";
import { RulesPanel } from "./RulesPanel";
import { VerdictCover } from "./VerdictCover";

/**
 * The storm run a flight belongs to: its local date, else the UTC day it arrives (overnight inbounds land
 * on the storm's day), else the day it leaves, else the nearest storm within a day.
 */
function stormFor(storms: StormSummary[] | undefined, flight: Flight | undefined) {
  if (!storms?.length || !flight) return undefined;
  for (const day of [flight.date, flight.sched_arr.slice(0, 10), flight.sched_dep.slice(0, 10)]) {
    const hit = storms.find((s) => s.date === day);
    if (hit) return hit;
  }
  const t = Date.parse(flight.date);
  return storms.find((s) => Math.abs(Date.parse(s.date) - t) <= 86_400_000) ?? storms[0];
}

export default function FlightFileView({ flightId }: { flightId: string }) {
  const file = useFlightFile(flightId);
  const storms = useStorms();
  const storm = stormFor(storms.data, file.data?.flight);
  const run = useStormRun(storm?.id);

  if (file.isError) {
    const missing = file.error instanceof ApiError && file.error.status === 404;
    return (
      <Frame>
        <BackLink />
        {missing ? (
          <Empty title={`No flight file for ${shortId(flightId)}`} className="mt-6">
            It may be from another storm run, or the ID is mistyped. <Link to="/flights" className="font-medium text-metar-ink hover:underline">See every flight</Link>.
          </Empty>
        ) : (
          <ErrorNote className="mt-6" error={file.error} onRetry={() => void file.refetch()} />
        )}
      </Frame>
    );
  }
  if (!file.data) return <FileSkeleton />;

  const stormLabel = storm ? [stormName(storm.id) ?? storm.station, longDate(storm.date)].join(" · ") : null;
  return (
    <MotionConfig reducedMotion="user">
      <FileBody file={file.data} stormLabel={stormLabel} stormId={storm?.id} hub={iataOf(run.data?.station ?? storm?.station ?? "")} windows={run.data?.windows} metar={run.data?.metar} realContext={run.data?.real_context} />
    </MotionConfig>
  );
}

function Frame({ children }: { children: ReactNode }) {
  return <div className="mx-auto max-w-[1240px]">{children}</div>;
}

function BackLink() {
  return (
    <Link to="/flights" className="text-[13px] text-slate-500 hover:text-navy-900">
      ← Flight File
    </Link>
  );
}

/**
 * The rail sticks under the app header when it fits; a taller rail scrolls with the page until its bottom
 * is in view and sticks there, so the confidence and the money stay next to whatever is being read.
 */
function useRailTop(header: number) {
  const ref = useRef<HTMLElement>(null);
  const [top, setTop] = useState(header);
  useLayoutEffect(() => {
    const el = ref.current;
    if (!el) return;
    const check = () => setTop(Math.min(header, window.innerHeight - el.offsetHeight - 24));
    const ro = new ResizeObserver(check);
    ro.observe(el);
    window.addEventListener("resize", check);
    check();
    return () => {
      ro.disconnect();
      window.removeEventListener("resize", check);
    };
  }, [header]);
  return [ref, top] as const;
}

function FileBody({ file, stormLabel, stormId, hub, windows, metar, realContext }: { file: FlightFile; stormLabel: string | null; stormId?: string; hub: string; windows?: StormWindow[]; metar?: MetarObs[]; realContext?: Record<string, unknown> }) {
  const kind = useMemo(() => verdictOf({ flight: file.flight, decision: file.decision }), [file]);
  const defence = useMemo(() => (kind === "weather" ? weatherDefence(file, hub, windows, realContext) : null), [kind, file, hub, windows, realContext]);
  const [railRef, railTop] = useRailTop(80);
  const d = file.decision;
  const tiers = [...new Set(d.evidence.map((e) => e.trust_tier))].sort();

  return (
    <Frame>
      <VerdictCover file={file} kind={kind} stormLabel={stormLabel} stormId={stormId} />

      <div className="mt-6 grid items-start gap-6 lg:grid-cols-[minmax(0,1fr)_340px] xl:grid-cols-[minmax(0,1fr)_372px]">
        <aside ref={railRef} className="flex flex-col gap-6 lg:sticky lg:col-start-2 lg:row-start-1" style={{ top: railTop }} aria-label="Confidence and money">
          {kind === "operated" ? null : <ConfidenceCard confidence={d.confidence} reason={d.reason} />}
          <MoneyCard file={file} kind={kind} />
        </aside>

        <div className="flex min-w-0 flex-col gap-6 lg:col-start-1 lg:row-start-1">
          <Section
            title="Evidence"
            note="Ranked by trust tier. The losing source is struck through."
            testId="evidence"
            legend={
              <ul className="mt-1.5 hidden flex-wrap gap-x-4 gap-y-1 sm:flex">
                {tiers.map((t) => (
                  <li key={t} className="text-[11.5px] text-slate-400">
                    <span className="font-mono text-[10.5px] font-bold text-slate-500">T{t}</span> {TIER_NAME[t]}
                  </li>
                ))}
              </ul>
            }
            footer={
              <span className="flex flex-wrap items-center gap-x-2 gap-y-1 text-[12px] tabular-nums text-slate-400">
                <span>known at {zuluDay(d.known_at)}</span>
                {d.commit ? (
                  <>
                    <span>·</span>
                    <Link to={`/trace?target=${encodeURIComponent(d.flight_id)}`} className="text-metar-ink hover:underline" title={d.commit}>
                      commit <span className="font-mono text-[11.5px]">{d.commit.slice(0, 7)}</span>
                    </Link>
                  </>
                ) : null}
                <span>·</span>
                <span>{d.outcome === "auto" ? "decided by the engine" : d.outcome === "escalated" ? "escalated to a person" : "decided by a person"}</span>
              </span>
            }
          >
            {d.evidence.length ? <EvidenceList evidence={d.evidence} /> : <p className="py-2 text-[13.5px] text-slate-500">No evidence recorded.</p>}
          </Section>

          {defence ? (
            <Section
              title="Defence prepared · Art. 5(3)"
              note="What the airline would answer a compensation claim on this flight, from this file's evidence."
              testId="weather-defence"
              footer={<span className="text-[12px] text-slate-400">A draft: verdict and amounts unchanged, and nothing goes to a passenger until the Claims Lead approves it.</span>}
            >
              <WeatherDefenceRows defence={defence} />
            </Section>
          ) : null}

          {file.timeline?.length ? (
            <Section title="Timeline" note="Tech log, MCC, OCC, METAR and CRM, in UTC. Hover a mark for its line.">
              <FlightTimeline marks={file.timeline} flight={file.flight} kind={kind} hub={hub} windows={windows} metar={metar} />
            </Section>
          ) : null}

          <PassengersPanel file={file} />

          {file.journal_preview?.length ? <JournalDrafts entries={file.journal_preview} /> : null}

          <RulesPanel decision={d} />
          {kind === "operated" ? null : <ChallengePanel flightId={file.flight.id} kind={kind} />}
        </div>
      </div>
    </Frame>
  );
}

function Section({ title, note, legend, footer, children, testId }: { title: string; note?: string; legend?: ReactNode; footer?: ReactNode; children: ReactNode; testId?: string }) {
  const id = `${title.toLowerCase().replace(/\W+/g, "-")}-title`;
  return (
    <section aria-labelledby={id} data-testid={testId} className="rounded-xl bg-card shadow-[0_0_0_1px_var(--color-cloud-200),0_1px_2px_rgba(13,21,36,0.04)]">
      <header className="px-5 pt-4">
        <h2 id={id} className="text-[14.5px] font-semibold text-navy-900">
          {title}
        </h2>
        {note ? <p className="mt-0.5 text-[12.5px] text-slate-500">{note}</p> : null}
        {legend}
      </header>
      <div className="px-5 pb-4 pt-2">{children}</div>
      {footer ? <div className="border-t border-cloud-100 px-5 py-2.5">{footer}</div> : null}
    </section>
  );
}

function FileSkeleton() {
  return (
    <Frame>
      <div role="status" aria-label="Loading the flight file">
        <Shimmer className="h-3.5 w-40" />
        <Shimmer className="mt-4 h-10 w-80 max-w-full" />
        <Shimmer className="mt-3 h-4 w-[30rem] max-w-full" />
        <Shimmer className="mt-6 h-44 w-full rounded-xl" />
        <div className="mt-6 grid gap-6 lg:grid-cols-[minmax(0,1fr)_340px] xl:grid-cols-[minmax(0,1fr)_372px]">
          <div className="flex flex-col gap-6">
            <Shimmer className="h-96 rounded-xl" />
            <Shimmer className="h-52 rounded-xl" />
          </div>
          <div className="flex flex-col gap-6">
            <Shimmer className="h-80 rounded-xl" />
            <Shimmer className="h-56 rounded-xl" />
          </div>
        </div>
      </div>
    </Frame>
  );
}

