import { useMemo, type ReactNode } from "react";
import { Link, useSearchParams } from "react-router";
import { ChevronRight } from "lucide-react";
import { useStormRun, useStorms } from "@/api/queries";
import type { FlightRow, StormRun } from "@/api/types";
import { MicroLabel, StatusChip } from "@/components/chips";
import { ConfidenceLine, Empty, ErrorNote, PageHeader, Shimmer } from "@/components/kit";
import { VERDICT_COLOR, verdictChip, verdictOf, type VerdictKind } from "@/components/verdict";
import { count, longDate, routedTo, zulu } from "@/lib/format";
import { stormName } from "@/lib/storms";
import { cn } from "@/lib/utils";
import { cityOf, consequence, flightHref, splitRecode, VERDICT_HEADLINE } from "./lib";
import { Recode } from "./Recode";

/** Not weather first: the 1% the run caught, then what waits on a person, then the rest. */
const ORDER: VerdictKind[] = ["notweather", "held", "weather", "operated", "pending"];

type Group = { kind: VerdictKind; rows: FlightRow[] };

function groupFlights(run: StormRun): Group[] {
  const by = new Map<VerdictKind, FlightRow[]>();
  for (const row of run.flights) {
    const kind = verdictOf(row);
    by.set(kind, [...(by.get(kind) ?? []), row]);
  }
  return ORDER.filter((k) => by.has(k)).map((kind) => ({
    kind,
    rows: [...by.get(kind)!].sort((a, b) => a.flight.sched_dep.localeCompare(b.flight.sched_dep) || a.flight.number.localeCompare(b.flight.number)),
  }));
}

export default function FlightIndex() {
  const [params] = useSearchParams();
  const storms = useStorms();
  const stormId = params.get("storm") ?? storms.data?.[0]?.id;
  const run = useStormRun(stormId);

  if (storms.isError || run.isError) {
    return (
      <Frame>
        <PageHeader title="Flight File">Why each flight got its verdict.</PageHeader>
        <ErrorNote
          className="mt-8"
          error={storms.error ?? run.error}
          onRetry={() => {
            void storms.refetch();
            void run.refetch();
          }}
        />
      </Frame>
    );
  }
  if (storms.data && !storms.data.length) {
    return (
      <Frame>
        <PageHeader title="Flight File">Why each flight got its verdict.</PageHeader>
        <Empty title="No storm runs yet" className="mt-8">
          Run a storm from the Judge&rsquo;s Desk and its flights appear here.
        </Empty>
      </Frame>
    );
  }
  if (!run.data) return <IndexSkeleton />;
  return <IndexBody run={run.data} />;
}

function Frame({ children }: { children: ReactNode }) {
  return <div className="mx-auto max-w-[1240px]">{children}</div>;
}

function IndexBody({ run }: { run: StormRun }) {
  const groups = useMemo(() => groupFlights(run), [run]);
  const name = stormName(run.id);
  const cancelled = run.counters.cancelled ?? run.flights.filter((r) => r.flight.status === "cancelled").length;
  const operated = run.counters.operated ?? run.flights.filter((r) => r.flight.status === "operated").length;
  const passengers = run.counters.passengers;

  return (
    <Frame>
      <PageHeader eyebrow={<MicroLabel>{[name, run.station, longDate(run.date)].filter(Boolean).join(" · ")}</MicroLabel>} title="Flight File">
        Why each flight got its verdict. {count(cancelled)} cancelled, {count(operated)} operated
        {passengers ? <>, {count(passengers)} passengers</> : null}.
      </PageHeader>

      {run.flights.length ? (
        <>
          <VerdictRibbon groups={groups} total={run.flights.length} />
          <div className="mt-8 flex flex-col gap-8">
            {groups.map((g) => (
              <FlightGroup key={g.kind} group={g} runDate={run.date} />
            ))}
          </div>
        </>
      ) : (
        <Empty title="No flights in this run" className="mt-8">
          {run.message ?? "The schedule had no Northstar flights at this station that day."}
        </Empty>
      )}
    </Frame>
  );
}

/** One slim bar, proportional by flight count, doubling as jump links to each group. */
function VerdictRibbon({ groups, total }: { groups: Group[]; total: number }) {
  return (
    <nav aria-label="Verdicts" className="mt-7">
      <div className="flex h-2 w-full gap-[3px] overflow-hidden rounded-full" aria-hidden="true">
        {groups.map((g) => (
          <span key={g.kind} className="h-full first:rounded-l-full last:rounded-r-full" style={{ flexGrow: g.rows.length, flexBasis: 0, minWidth: 6, background: VERDICT_COLOR[g.kind] }} />
        ))}
      </div>
      <ul className="mt-3 flex flex-wrap gap-x-5 gap-y-2 text-[13px]">
        {groups.map((g) => (
          <li key={g.kind}>
            <a href={`#verdict-${g.kind}`} className="inline-flex items-center gap-2 rounded text-slate-600 hover:text-navy-900">
              <span className="size-2 rounded-full" style={{ background: VERDICT_COLOR[g.kind] }} aria-hidden="true" />
              {VERDICT_HEADLINE[g.kind]}
              <span className="figure text-slate-400">{count(g.rows.length)}</span>
            </a>
          </li>
        ))}
        <li className="ml-auto hidden font-mono text-[11.5px] text-slate-400 sm:block">{count(total)} flights</li>
      </ul>
    </nav>
  );
}

function groupNote(group: Group): string | null {
  if (group.kind === "held") {
    const role = group.rows.find((r) => r.decision?.routed_to)?.decision?.routed_to;
    return role ? `${routedTo(role)}; ${consequence("held")}` : consequence("held");
  }
  if (group.kind === "notweather") return group.rows.every((r) => r.decision?.recoded) ? "Recoded from the weather code OCC typed. Compensation owed." : "Not extraordinary: compensation owed.";
  if (group.kind === "operated") return "Flew as scheduled.";
  return consequence(group.kind);
}

function FlightGroup({ group, runDate }: { group: Group; runDate: string }) {
  const expanded = group.kind === "notweather" || group.kind === "held";
  const headingId = `verdict-${group.kind}-title`;
  return (
    <section id={`verdict-${group.kind}`} aria-labelledby={headingId} className="scroll-mt-20">
      <div className="mb-2.5 flex flex-wrap items-baseline gap-x-3 gap-y-1 px-1">
        <h2 id={headingId} className="flex items-center gap-2 text-[15px] font-semibold text-navy-900">
          <span className="size-2 rounded-full" style={{ background: VERDICT_COLOR[group.kind] }} aria-hidden="true" />
          {VERDICT_HEADLINE[group.kind]}
          <span className="figure font-normal text-slate-400">{count(group.rows.length)}</span>
        </h2>
        {groupNote(group) ? <p className="text-[13px] text-slate-500">{groupNote(group)}</p> : null}
      </div>
      <ul
        className={cn(
          "overflow-hidden rounded-xl bg-card shadow-[0_0_0_1px_var(--color-cloud-200),0_1px_2px_rgba(13,21,36,0.04)]",
          group.kind === "notweather" && "shadow-[0_0_0_1px_var(--color-cloud-200),0_1px_2px_rgba(13,21,36,0.04),inset_3px_0_0_var(--color-notweather)]",
          group.kind === "held" && "shadow-[0_0_0_1px_var(--color-cloud-200),0_1px_2px_rgba(13,21,36,0.04),inset_3px_0_0_var(--color-held)]",
        )}
      >
        {group.rows.map((row) => (
          <FlightRowLink key={row.flight.id} row={row} runDate={runDate} expanded={expanded} />
        ))}
      </ul>
    </section>
  );
}

/** "+1"/"−1" after a time that falls on another UTC day, as departure boards write it. */
function DayOffset({ iso, runDate }: { iso: string; runDate: string }) {
  const d = Math.round((Date.parse(iso.slice(0, 10)) - Date.parse(runDate)) / 86_400_000);
  if (!d) return null;
  return (
    <sup className="ml-0.5 text-[9.5px] font-semibold text-slate-400" title={longDate(iso.slice(0, 10))}>
      {d > 0 ? `+${d}` : `−${-d}`}
    </sup>
  );
}

function FlightRowLink({ row, runDate, expanded }: { row: FlightRow; runDate: string; expanded: boolean }) {
  const { flight, decision } = row;
  const kind = verdictOf(row);
  const chip = kind === "operated" ? { text: "operated", tone: "slate" as const } : verdictChip(decision);
  const recode = decision?.recoded ? splitRecode(decision.recode_label, decision) : null;
  const code = recode ? null : (decision?.ops_cause_code ?? flight.ops_cause_code);

  return (
    <li className="border-t border-cloud-100 first:border-t-0">
      <Link
        to={flightHref(flight.id)}
        aria-label={`${flight.number}, ${cityOf(flight.origin)} to ${cityOf(flight.dest)}, ${chip.text}`}
        className="group grid grid-cols-[minmax(0,1fr)_auto] items-center gap-x-4 gap-y-1 px-4 py-3 outline-none transition-colors hover:bg-cloud-25 focus-visible:bg-cloud-25 focus-visible:shadow-[inset_0_0_0_2px_var(--color-metar)] sm:px-5 md:grid-cols-[60px_72px_minmax(0,1fr)_76px_92px_212px_16px]"
      >
        {/* phone: two lines; md+: one board row */}
        <span className="flex min-w-0 items-baseline gap-3 md:contents">
          <span className={cn("font-mono text-[13.5px] font-bold text-navy-900", expanded && "md:text-[14.5px]")}>{flight.number}</span>
          <span className="figure hidden text-[13px] text-slate-600 md:block">
            {zulu(flight.sched_dep)}
            <DayOffset iso={flight.sched_dep} runDate={runDate} />
          </span>
          <span className="min-w-0 truncate text-[13.5px] text-navy-900">
            <span className="font-mono text-[12.5px] text-slate-600">
              {flight.origin} → {flight.dest}
            </span>
            <span className="ml-2 hidden text-slate-500 lg:inline">{cityOf(flight.origin === "DUB" ? flight.dest : flight.origin)}</span>
          </span>
        </span>
        <span className="hidden text-right text-[13px] text-slate-500 md:block">
          <span className="figure text-navy-900">{count(flight.pax)}</span> pax
        </span>
        <span className="hidden font-mono text-[12px] text-slate-500 md:block">{recode ? <Recode from={recode.from} to={recode.to} size="sm" /> : code ? `RSN ${code}` : "—"}</span>
        <span className="justify-self-end md:justify-self-start">
          {/* phones: the group header already names the verdict, so the chip keeps only the outcome */}
          <StatusChip tone={chip.tone}>
            <span className="md:hidden">{chip.text.split(" · ").pop()}</span>
            <span className="hidden md:inline">{chip.text}</span>
          </StatusChip>
        </span>
        <ChevronRight className="hidden size-4 text-slate-400 transition-transform group-hover:translate-x-0.5 md:block" aria-hidden="true" />

        {/* phone meta line */}
        <span className="col-span-2 flex flex-wrap items-center gap-x-2 text-[12px] tabular-nums text-slate-500 md:hidden">
          <span>
            STD {zulu(flight.sched_dep)}
            <DayOffset iso={flight.sched_dep} runDate={runDate} />
          </span>
          <span aria-hidden="true">·</span>
          <span>{count(flight.pax)} pax</span>
          {recode ? (
            <>
              <span aria-hidden="true">·</span>
              <Recode from={recode.from} to={recode.to} size="sm" />
            </>
          ) : null}
        </span>

        {expanded && decision ? (
          <span className="col-span-2 flex flex-col gap-1 md:col-span-5 md:col-start-3 md:-mt-0.5">
            <span className="text-[13.5px] leading-snug text-slate-600">{decision.reason.charAt(0).toUpperCase() + decision.reason.slice(1)}</span>
            <ConfidenceLine confidence={decision.confidence} showCaps={false} className="text-[11.5px]" />
          </span>
        ) : null}
      </Link>
    </li>
  );
}

function IndexSkeleton() {
  return (
    <Frame>
      <div role="status" aria-label="Loading flights">
        <Shimmer className="h-3 w-48" />
        <Shimmer className="mt-3 h-8 w-56" />
        <Shimmer className="mt-3 h-4 w-96 max-w-full" />
        <Shimmer className="mt-8 h-2 w-full" />
        {[1, 3, 8].map((n, i) => (
          <div key={i} className="mt-8">
            <Shimmer className="h-4 w-40" />
            <Shimmer className="mt-3 w-full" />
            <div className="mt-3 flex flex-col gap-px overflow-hidden rounded-xl">
              {Array.from({ length: n }).map((_, j) => (
                <Shimmer key={j} className="h-12 rounded-none" />
              ))}
            </div>
          </div>
        ))}
      </div>
    </Frame>
  );
}
