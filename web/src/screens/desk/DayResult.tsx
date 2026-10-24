import { useEffect, useMemo, useRef, useState } from "react";
import { Link } from "react-router";
import { AnimatePresence, motion, useReducedMotion } from "motion/react";
import { ArrowRight, ChevronDown } from "lucide-react";
import { useStorms } from "@/api/queries";
import type { FlightRow, Question, StormRun, StormWindow, TraceEvent } from "@/api/types";
import { MicroLabel, StatusChip } from "@/components/chips";
import { EvidenceList } from "@/components/evidence";
import { ConfidenceLine, FeedRow, LoopFooter, Money, Panel, RoutedTo } from "@/components/kit";
import { RouteLegend, RouteMap } from "@/components/storm/RouteMap";
import { StormTimeline } from "@/components/storm/StormTimeline";
import { VERDICT_COLOR, type VerdictKind, verdictChip, verdictOf } from "@/components/verdict";
import { airport as mapAirport, iataOf } from "@/lib/airports";
import { count, longDate, zulu, zuluDay } from "@/lib/format";
import { stormName } from "@/lib/storms";
import { cn } from "@/lib/utils";
import { airportByIcao } from "./airports";
import { dayLabel } from "./dates";
import { flightOf, useDesk } from "./state";
import { useBringIntoView } from "./useBringIntoView";

/** Counter keys the StormRun carries (CONTRACTS §1), in reading order, with their words. */
const COUNTERS: [string, string][] = [
  ["passengers", "passengers"],
  ["cancelled", "cancelled"],
  ["operated", "operated"],
  ["recoded", "recoded"],
  ["drafted", "payouts drafted"],
  ["settled", "settled"],
  ["held", "held"],
  ["needs_ruling", "need a ruling"],
  ["questions", "questions"],
  ["open_questions", "still open"],
  ["people", "people asked"],
  ["rules_cited", "rulings cited"],
  ["repeat_questions", "repeat questions"],
];

/** Known counters in reading order, then any the server adds, in its words. */
function counterRows(c: Record<string, number>, skip: string[]) {
  const known = new Map(COUNTERS);
  const order = [...COUNTERS.map(([k]) => k), ...Object.keys(c).filter((k) => !known.has(k)).sort()];
  return order.filter((k) => c[k] !== undefined && !skip.includes(k)).map((k) => [k, known.get(k) ?? k.replace(/_/g, " ")] as const);
}

/** Cool blue on the navy readout; wraps on a phone instead of running off the panel. */
const WINDOW_CHIP = "h-auto min-h-6 whitespace-normal bg-metar/15 py-1 text-[#9ccbf2]";

const runKey = (run: StormRun) => run.id.match(/[A-Z0-9]{4}@\d{4}-\d{2}-\d{2}/)?.[0] ?? `${run.station}@${run.date}`;

function windowSpan(w: StormWindow, runDate: string) {
  const sameDay = (iso: string) => iso.slice(0, 10) === runDate;
  const a = sameDay(w.start) ? zulu(w.start) : zuluDay(w.start);
  const b = sameDay(w.end) ? zulu(w.end) : zuluDay(w.end);
  return `${a}–${b}`;
}

function useIsNarrow() {
  const [narrow, setNarrow] = useState(() => typeof window !== "undefined" && window.matchMedia("(max-width: 767px)").matches);
  useEffect(() => {
    const mq = window.matchMedia("(max-width: 767px)");
    const on = () => setNarrow(mq.matches);
    mq.addEventListener("change", on);
    return () => mq.removeEventListener("change", on);
  }, []);
  return narrow;
}

/** A compact Storm Run for the judge's own day: counters, windows, METAR timeline, routes, flights, money, feed. */
export function DayResult({ run }: { run: StormRun }) {
  const narrow = useIsNarrow();
  const [openFlight, setOpenFlight] = useState<string | null>(null);
  const listRef = useRef<HTMLDivElement>(null);
  const storms = useStorms();
  const known = storms.data?.some((st) => st.id === run.id) ?? false;

  const c = run.counters ?? {};
  const place = airportByIcao(run.station);
  const rc = (run.real_context ?? {}) as Record<string, unknown>;
  const name = typeof rc.name === "string" && rc.name ? rc.name : stormName(runKey(run));
  // Say where the weather came from, and never call generated observations real.
  const mockMetar = run.metar.some((o) => /\bRMK MOCK\b/.test(o.raw));
  const metarSource = typeof rc.metar_source === "string" ? rc.metar_source : null;
  const metarLabel = mockMetar ? "mock METAR" : metarSource && /real|iem|awc|pinned/i.test(metarSource) ? "real METAR" : "METAR";
  const recoded = run.flights.filter((r) => r.decision?.recoded);
  const hub = place?.iata ?? iataOf(run.station);
  const routes = new Set(run.flights.map((r) => (r.flight.origin === hub ? r.flight.dest : r.flight.origin)));
  // One route (a judge's own airport ⇄ DUB) is a line, not a map: the list says it better.
  const hasMap = !!mapAirport(hub) && routes.size >= 3;
  const ref = useBringIntoView<HTMLDivElement>();
  const cited = run.feed.filter((e) => e.chip === "CITED");
  const cancelled = c.cancelled ?? run.flights.filter((r) => r.flight.status === "cancelled").length;

  const select = (id: string) => {
    setOpenFlight(id);
    window.requestAnimationFrame(() => listRef.current?.querySelector(`[data-flight-id="${CSS.escape(id)}"]`)?.scrollIntoView({ behavior: "smooth", block: "nearest" }));
  };

  return (
    <div ref={ref} className="flex scroll-mt-[72px] flex-col gap-3" data-testid="desk-run-result" data-run-id={run.id}>
      {/* The readout: same instrument as Storm Run, sized for one day. */}
      <section className="relative overflow-hidden rounded-2xl bg-navy-900 text-cloud-50 shadow-[0_20px_60px_-24px_rgba(8,13,23,0.55)]" aria-label={`Run for ${run.station}, ${longDate(run.date)}`}>
        <div aria-hidden="true" className="pointer-events-none absolute -right-32 -top-44 size-[480px] rounded-full bg-[radial-gradient(closest-side,rgba(79,159,224,0.14),transparent)]" />
        <div className="relative px-4 pb-4 pt-5 md:px-7 md:pt-6">
          <div className="min-w-0">
            <p className="micro text-cloud-500">
              {name ? `${name} · ` : ""}
              {place ? `${place.name} · ` : ""}
              {run.station} · {dayLabel(run.date)} · local
            </p>
            {run.message ? (
              <>
                <h2 className="display mt-2.5 text-[28px] text-cloud-50 md:text-[36px]" data-testid="desk-headline">
                  <span data-testid="desk-message">{run.message}</span>
                </h2>
                <p className="mt-2 font-mono text-[12.5px] text-cloud-400">
                  {[c.operated !== undefined ? `${count(c.operated)} operated` : null, `${count(cancelled)} cancelled`, c.questions !== undefined ? `${count(c.questions)} ${c.questions === 1 ? "question" : "questions"}` : null].filter(Boolean).join(" · ")}
                </p>
              </>
            ) : (
              <h2 className="display mt-2.5 text-[28px] text-cloud-50 md:text-[36px]" data-testid="desk-headline">
                {c.passengers !== undefined ? (
                  <>
                    {count(c.passengers)} passengers <span className="text-cloud-500">·</span>{" "}
                  </>
                ) : null}
                {count(cancelled)} cancelled
                {c.questions !== undefined ? (
                  <>
                    {" "}
                    <span className="text-cloud-500">·</span> {count(c.questions)} {c.questions === 1 ? "question" : "questions"}
                  </>
                ) : null}
              </h2>
            )}
            <div className="mt-3 flex flex-wrap items-center gap-2">
              <StatusChip tone="metar" className={WINDOW_CHIP} title={metarSource ?? undefined}>
                {metarLabel} · {count(run.metar.length)} obs
              </StatusChip>
              {run.windows.map((w, i) => (
                <StatusChip key={i} tone="metar" dot={false} className={WINDOW_CHIP} title={w.definition}>
                  storm window {windowSpan(w, run.date)} · peak gust {w.peak_gust_kt} kt{w.obs_count ? ` · ${w.obs_count} obs` : ""}
                </StatusChip>
              ))}
            </div>
            {run.windows[0]?.definition ? <p className="mt-2 font-mono text-[11px] leading-relaxed text-cloud-500">window = {run.windows[0].definition}</p> : null}
            <RealContext rc={rc} />
          </div>

          <ChangedSince run={run} />

          {recoded.length ? <NotWeather rows={recoded} onOpen={select} /> : null}

          {/* On a phone the day keeps a readable width and scrolls sideways inside the readout. */}
          <div className="-mx-4 mt-5 overflow-x-auto overscroll-x-contain px-4 md:mx-0 md:overflow-visible md:px-0">
            <div className="min-w-[640px] md:min-w-0">
              <StormTimeline key={run.id} run={run} tone="dark" compact={narrow} onSelectFlight={select} />
            </div>
          </div>
          <div className="mt-2 flex flex-wrap items-center justify-between gap-3 border-t border-white/[0.06] pt-3">
            <RouteLegend tone="dark" />
            <span className="font-mono text-[11px] text-cloud-500">UTC · point at the curve for the raw METAR</span>
          </div>
        </div>
      </section>

      {cancelled > 0 ? <MoneyRow run={run} /> : null}

      <div className={cn("grid gap-3", hasMap && "lg:grid-cols-[minmax(0,5fr)_minmax(0,7fr)]")}>
        {hasMap ? (
          <section className="min-w-0 overflow-hidden rounded-xl bg-navy-900 p-4 text-cloud-50 shadow-[0_0_0_1px_var(--color-navy-800)]" aria-label="Routes">
            <div className="flex items-center justify-between gap-3 px-1">
              <h3 className="text-[14.5px] font-semibold">Routes from {place?.name ?? run.station}</h3>
            </div>
            <RouteMap key={run.id} run={run} tone="dark" compact={narrow} onSelectFlight={select} className="mt-2" />
            <VerdictMix rows={run.flights} />
          </section>
        ) : null}
        <div ref={listRef} className="min-w-0">
          <FlightList run={run} open={openFlight} onToggle={(id) => setOpenFlight((cur) => (cur === id ? null : id))} linkable={known} beside={hasMap} />
        </div>
      </div>

      <div className="grid gap-3 lg:grid-cols-2">
        <Panel
          title="What it asked"
          actions={
            run.questions.length ? (
              <Link to="/questions" className="inline-flex items-center gap-1 text-[12.5px] font-medium text-metar-ink hover:underline">
                Questions <ArrowRight className="size-3.5" aria-hidden="true" />
              </Link>
            ) : null
          }
        >
          <AskedList questions={run.questions} />
          {cited.length ? (
            <div className="mt-4 flex flex-col gap-1.5 border-t border-cloud-100 pt-3">
              {cited.map((e) => (
                <LoopFooter key={e.seq}>{e.summary}</LoopFooter>
              ))}
            </div>
          ) : null}
        </Panel>
        <RunFeed events={run.feed} />
      </div>
    </div>
  );
}

/** An injection after this run touched one of its flights: say so, and offer to run the day again. */
function ChangedSince({ run }: { run: StormRun }) {
  const ranFor = useDesk((s) => s.ranFor);
  const injected = useDesk((s) => s.inject.result);
  const runDay = useDesk((s) => s.runDay);
  if (!ranFor || !injected || injected.at < ranFor.at) return null;
  const ids = new Set(run.flights.map((r) => r.flight.id));
  const touched = [...new Set(injected.response.affected.map(flightOf).filter((id): id is string => !!id && ids.has(id)))];
  if (!touched.length) return null;
  return (
    <div className="mt-4 flex flex-wrap items-center gap-x-3 gap-y-1.5 rounded-xl bg-white/[0.04] px-4 py-2.5 text-[13px] text-cloud-300 ring-1 ring-white/10" data-testid="desk-changed-since">
      <span className="font-mono text-cloud-500" aria-hidden="true">
        ↻
      </span>
      <span>
        Your injection changed <span className="font-mono text-cloud-50">{touched.map((id) => id.split("@")[0]).join(", ")}</span> on this day since it ran.
      </span>
      <button type="button" onClick={() => void runDay(ranFor.icao, ranFor.date, ranFor.airport)} className="ml-auto text-[13px] font-medium text-[#9ccbf2] hover:underline">
        Run it again
      </button>
    </div>
  );
}

/** What really happened at the airport that day, when the API has it (Eurocontrol, Met Éireann). */
function RealContext({ rc }: { rc: Record<string, unknown> }) {
  const parts: string[] = [];
  if (rc.eurocontrol_departures !== undefined) parts.push(`${count(Number(rc.eurocontrol_departures))} departures (Eurocontrol)${rc.normal_departures ? ` vs ${String(rc.normal_departures)} normal` : ""}`);
  if (rc.reported_cancellations_dep !== undefined) parts.push(`~${count(Number(rc.reported_cancellations_dep))} cancelled (reported)`);
  if (rc.red_warning) parts.push(`red warning ${String(rc.red_warning).replace("-", "–")}`);
  if (rc.orange_warning) parts.push(`orange ${String(rc.orange_warning).replace("-", "–")}`);
  if (!parts.length) return null;
  return (
    <p className="mt-1 font-mono text-[11px] leading-relaxed text-cloud-500">
      <span className="text-cloud-300">real context</span> · {parts.join(" · ")}
    </p>
  );
}

/** "Not weather." for each flight the re-check recoded: the miscode it caught, one line each. */
function NotWeather({ rows, onOpen }: { rows: FlightRow[]; onOpen: (id: string) => void }) {
  const reduce = useReducedMotion();
  return (
    <div className="mt-4 flex flex-col gap-2" data-testid="desk-recoded">
      {rows.slice(0, 3).map((r, i) => {
        const d = r.decision!;
        const notWeather = d.extraordinary === "not_extraordinary";
        return (
          <motion.button
            key={r.flight.id}
            type="button"
            onClick={() => onOpen(r.flight.id)}
            initial={{ opacity: 0, y: 6 }}
            animate={{ opacity: 1, y: 0 }}
            transition={{ delay: reduce ? 0 : 3.5 + i * 0.12, duration: reduce ? 0 : 0.5, ease: [0.16, 1, 0.3, 1] }}
            className={cn(
              "group grid w-full grid-cols-[minmax(0,1fr)_auto] items-center gap-x-4 rounded-xl bg-navy-950/70 px-4 py-3 text-left ring-1 ring-white/10 transition-colors hover:bg-navy-950",
              notWeather && "shadow-[inset_3px_0_0_var(--color-notweather)]",
            )}
          >
            <span className="min-w-0">
              <span className="display-tight block text-[18px] leading-tight text-cloud-50">
                {notWeather ? (
                  <>
                    Not weather. <span className="text-notweather">Miscode caught.</span>
                  </>
                ) : (
                  "Recoded."
                )}
              </span>
              <span className="mt-1.5 flex flex-wrap items-center gap-x-3 gap-y-1">
                <span className="font-mono text-[12px] text-cloud-300">
                  {r.flight.number} {r.flight.origin}–{r.flight.dest} · <span className={notWeather ? "text-notweather" : undefined}>{d.recode_label ?? "recoded"}</span> · {count(r.flight.pax)} passengers
                </span>
                <ConfidenceLine confidence={d.confidence} reason={d.reason} showCaps={false} className="text-[11.5px] text-cloud-400 [&_span.font-bold]:text-cloud-50" />
              </span>
            </span>
            <span className="inline-flex items-center gap-1 text-[12.5px] text-cloud-400 transition-colors group-hover:text-cloud-50">
              Why <ArrowRight className="size-3.5" aria-hidden="true" />
            </span>
          </motion.button>
        );
      })}
      {rows.length > 3 ? <p className="px-1 font-mono text-[11.5px] text-cloud-500">and {rows.length - 3} more recoded, in the list below</p> : null}
    </div>
  );
}

function MoneyRow({ run }: { run: StormRun }) {
  const c = run.counters ?? {};
  return (
    <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-[1fr_1fr_1fr_1.35fr]" data-testid="desk-money">
      <Panel>
        <MicroLabel>EU261 compensation liability</MicroLabel>
        <p className="display mt-2 text-[30px] text-navy-900">
          <Money cents={run.liability_drafted_cents} />
        </p>
        <p className="mt-1.5 text-[12.5px] leading-relaxed text-slate-500">drafted, pending approval</p>
      </Panel>
      <Panel>
        <MicroLabel>Full Art. 7 entitlement</MicroLabel>
        <p className="display mt-2 text-[30px] text-navy-900">
          <Money cents={run.entitlement_cents} />
        </p>
        <p className="mt-1.5 text-[12.5px] leading-relaxed text-slate-500">if every passenger claims</p>
      </Panel>
      {c.drafted !== undefined ? (
        <Panel>
          <MicroLabel>Payouts</MicroLabel>
          <p className="display mt-2 text-[30px] text-navy-900">{count(c.drafted)}</p>
          <p className="mt-1.5 text-[12.5px] leading-relaxed text-slate-500">drafted, pending Claims Lead approval</p>
        </Panel>
      ) : null}
      <Panel>
        <MicroLabel>Counters</MicroLabel>
        <dl className="mt-2 grid grid-cols-2 gap-x-3 gap-y-1 text-[12.5px]">
          {counterRows(c, ["passengers", "drafted"]).map(([k, label]) => (
            <div key={k} className="flex items-baseline justify-between gap-2 border-b border-cloud-100 py-0.5">
              <dt className="whitespace-nowrap text-slate-500">{label}</dt>
              <dd className="figure font-semibold text-navy-900">{count(c[k])}</dd>
            </div>
          ))}
        </dl>
      </Panel>
    </div>
  );
}

/** What a reader needs first: the miscode, then what waits on a person, then the rest. */
const SEVERITY: Record<VerdictKind, number> = { notweather: 0, held: 1, pending: 2, weather: 3, operated: 4 };
const MIX_LABEL: Record<VerdictKind, string> = { notweather: "not weather", held: "held", pending: "pending", weather: "weather", operated: "operated" };

/** How the day's flights split by verdict, as one bar: counts from the run, colours from the palette. */
function VerdictMix({ rows }: { rows: FlightRow[] }) {
  const tally = (Object.keys(SEVERITY) as VerdictKind[]).map((k) => ({ k, n: rows.filter((r) => verdictOf(r) === k).length })).filter((x) => x.n > 0);
  const total = rows.length || 1;
  return (
    <div className="mt-3 border-t border-white/[0.06] px-1 pt-3" data-testid="desk-mix">
      <div className="flex h-2 overflow-hidden rounded-full bg-white/[0.04]" role="img" aria-label={tally.map((x) => `${x.n} ${MIX_LABEL[x.k]}`).join(", ")}>
        {tally.map((x) => (
          <span key={x.k} style={{ width: `${(x.n / total) * 100}%`, background: VERDICT_COLOR[x.k] }} className="h-full first:rounded-l-full last:rounded-r-full [&+&]:ml-[2px]" />
        ))}
      </div>
      <ul className="mt-2 flex flex-wrap gap-x-4 gap-y-1 font-mono text-[11px] text-cloud-400">
        {tally.map((x) => (
          <li key={x.k} className="flex items-center gap-1.5">
            <span className="size-1.5 rounded-full" style={{ background: VERDICT_COLOR[x.k] }} aria-hidden="true" />
            <span className="text-cloud-100">{count(x.n)}</span> {MIX_LABEL[x.k]}
          </li>
        ))}
      </ul>
    </div>
  );
}

/** Flights in reading order (miscode, held, weather, then operated), each with its verdict. Click to see why. */
function FlightList({ run, open, onToggle, linkable, beside }: { run: StormRun; open: string | null; onToggle: (id: string) => void; linkable: boolean; beside: boolean }) {
  const rows = useMemo(() => {
    const at = (r: FlightRow) => new Date(r.flight.sched_dep).getTime();
    return [...run.flights].sort((a, b) => SEVERITY[verdictOf(a)] - SEVERITY[verdictOf(b)] || at(a) - at(b));
  }, [run.flights]);
  const operated = rows.filter((r) => r.flight.status === "operated");
  const disrupted = rows.filter((r) => r.flight.status !== "operated");
  const [showOperated, setShowOperated] = useState(disrupted.length === 0);

  return (
    <Panel title={`Flights · ${count(run.flights.length)}`} padded={false} className="h-full">
      {rows.length === 0 ? <p className="px-5 pb-5 text-[13.5px] text-slate-500">No Northstar flights at {run.station} that day.</p> : null}
      <ul className={cn("max-h-[520px] overflow-y-auto overscroll-contain px-2 pb-2", beside && "lg:max-h-[364px]")} data-testid="desk-flights">
        {disrupted.map((r) => (
          <FlightItem key={r.flight.id} row={r} open={open === r.flight.id} onToggle={() => onToggle(r.flight.id)} linkable={linkable} />
        ))}
        {operated.length ? (
          <li className="px-3 pb-1 pt-3">
            <button type="button" onClick={() => setShowOperated((v) => !v)} className="flex w-full items-center justify-between gap-2 text-left" aria-expanded={showOperated}>
              <span className="micro text-slate-500">
                Operated · {count(operated.length)}
              </span>
              <ChevronDown className={cn("size-4 text-slate-400 transition-transform", showOperated && "rotate-180")} aria-hidden="true" />
            </button>
            {!showOperated ? (
              <p className="mt-1.5 flex flex-wrap gap-1.5">
                {operated.map((r) => (
                  <span key={r.flight.id} className="font-mono text-[11.5px] text-slate-500">
                    {r.flight.number}
                  </span>
                ))}
              </p>
            ) : null}
          </li>
        ) : null}
        {showOperated ? operated.map((r) => <FlightItem key={r.flight.id} row={r} open={open === r.flight.id} onToggle={() => onToggle(r.flight.id)} linkable={linkable} />) : null}
      </ul>
    </Panel>
  );
}

function FlightItem({ row, open, onToggle, linkable }: { row: FlightRow; open: boolean; onToggle: () => void; linkable: boolean }) {
  const f = row.flight;
  const d = row.decision;
  const v = verdictOf(row);
  const chip = f.status === "operated" ? { text: "operated", tone: "slate" as const } : verdictChip(d);
  return (
    <li data-flight-id={f.id} className={cn("rounded-lg transition-colors", open && "bg-cloud-50")}>
      <button type="button" onClick={onToggle} aria-expanded={open} className="flex w-full flex-col gap-1.5 rounded-lg px-3 py-2.5 text-left hover:bg-cloud-50 sm:grid sm:grid-cols-[minmax(0,1fr)_auto] sm:items-start sm:gap-x-3 sm:gap-y-1">
        <span className="min-w-0">
          <span className="flex flex-wrap items-baseline gap-x-2.5 gap-y-0.5">
            <span className="font-mono text-[13px] font-bold text-navy-900">{f.number}</span>
            <span className="font-mono text-[12px] text-slate-500">
              {f.origin}→{f.dest}
            </span>
            <span className="figure text-[12.5px] text-slate-500">{zulu(f.sched_dep)}</span>
            <span className="figure text-[12.5px] text-slate-400">{count(f.pax)} pax</span>
          </span>
          {d?.reason && f.status !== "operated" ? <span className="mt-1 block text-[12.5px] leading-snug text-slate-500">{d.reason}</span> : null}
        </span>
        <span className="flex flex-wrap items-center gap-1.5 pt-px">
          {d?.recoded && d.recode_label ? (
            <StatusChip tone={v === "notweather" ? "notweather" : "outline"} dot={false} className="h-5 text-[10.5px]">
              {d.recode_label}
            </StatusChip>
          ) : null}
          <StatusChip tone={chip.tone} className="h-5 text-[10.5px]">
            {chip.text}
          </StatusChip>
          <ChevronDown className={cn("ml-auto size-4 text-slate-400 transition-transform sm:ml-0", open && "rotate-180")} aria-hidden="true" />
        </span>
      </button>
      <AnimatePresence initial={false}>
        {open ? (
          <motion.div initial={{ height: 0, opacity: 0 }} animate={{ height: "auto", opacity: 1 }} exit={{ height: 0, opacity: 0 }} transition={{ duration: 0.22, ease: [0.25, 1, 0.5, 1] }} className="overflow-hidden">
            <div className="px-3 pb-3">
              {f.status === "operated" ? (
                <>
                  <p className="text-[12.5px] text-slate-500">{d?.reason ?? "Operated as scheduled. Nothing to decide."}</p>
                  {d?.evidence.length ? <EvidenceList evidence={d.evidence.slice(0, 3)} compact className="mt-2" /> : null}
                </>
              ) : d ? (
                <>
                  <ConfidenceLine confidence={d.confidence} className="text-[11.5px]" />
                  <div className="mt-2 flex flex-wrap gap-1.5">
                    <StatusChip tone="outline" dot={false} className="h-5 text-[10.5px]">
                      dep {d.in_window_dep} window
                    </StatusChip>
                    <StatusChip tone="outline" dot={false} className="h-5 text-[10.5px]">
                      arr {d.in_window_arr} window
                    </StatusChip>
                    {d.window_margin_min !== null && d.window_margin_min !== undefined ? (
                      <StatusChip tone="outline" dot={false} className="h-5 text-[10.5px]">
                        margin {d.window_margin_min} min
                      </StatusChip>
                    ) : null}
                    {d.legal_basis.map((b) => (
                      <StatusChip key={b} tone="slate" dot={false} className="h-5 text-[10.5px]">
                        {b}
                      </StatusChip>
                    ))}
                    {d.rules_applied.map((r) => (
                      <StatusChip key={r} tone="slate" dot={false} className="h-5 text-[10.5px]">
                        {r}
                      </StatusChip>
                    ))}
                  </div>
                  {d.evidence.length ? <EvidenceList evidence={d.evidence.slice(0, 5)} compact className="mt-2" /> : null}
                  {d.routed_to ? <RoutedTo role={d.routed_to} className="mt-2" /> : null}
                </>
              ) : (
                <p className="text-[12.5px] text-slate-500">No decision yet.</p>
              )}
              {linkable ? (
                <Link to={`/flights/${encodeURIComponent(f.id)}`} className="mt-2 inline-flex items-center gap-1 text-[12.5px] font-medium text-metar-ink hover:underline">
                  Open the flight file <ArrowRight className="size-3.5" aria-hidden="true" />
                </Link>
              ) : null}
            </div>
          </motion.div>
        ) : null}
      </AnimatePresence>
    </li>
  );
}

function AskedList({ questions }: { questions: Question[] }) {
  if (!questions.length) return <p className="text-[13.5px] text-slate-500">Nothing to ask. Every decision was clear enough to draft.</p>;
  return (
    <ul className="flex flex-col divide-y divide-cloud-100">
      {questions.map((q) => (
        <li key={q.id} className="py-3 first:pt-0 last:pb-0">
          <div className="flex flex-wrap items-start justify-between gap-2">
            <p className="text-[14px] font-medium text-navy-900">{q.title}</p>
            <span className="font-mono text-[11.5px] text-slate-400">{q.case_refs.length > 1 ? `${q.case_refs.length} cases` : q.case_refs[0]?.split("@")[0]}</span>
          </div>
          <div className="mt-1.5 flex flex-wrap items-center gap-x-3 gap-y-1">
            <RoutedTo role={q.routed_to} holdsCents={q.holds_cents} />
            <ConfidenceLine confidence={q.confidence} reason={q.reason_tag.replace(/-/g, " ")} showCaps={false} className="text-[11.5px]" />
          </div>
        </li>
      ))}
    </ul>
  );
}

function RunFeed({ events }: { events: TraceEvent[] }) {
  const sorted = useMemo(() => [...events].sort((a, b) => b.seq - a.seq), [events]);
  return (
    <Panel title="What it did" padded={false}>
      {sorted.length ? (
        <ol className="max-h-[360px] overflow-y-auto px-5 pb-2">
          {sorted.map((e) => (
            <FeedRow key={e.seq} event={e} className="border-t border-cloud-100 first:border-t-0" />
          ))}
        </ol>
      ) : (
        <p className="px-5 pb-5 text-[13px] text-slate-500">No activity for this day.</p>
      )}
    </Panel>
  );
}
