import { useMemo, useState } from "react";
import { Link, useSearchParams } from "react-router";
import { AnimatePresence, motion } from "motion/react";
import { ArrowRight, Search, X } from "lucide-react";
import { useTrace } from "@/api/queries";
import { mergeFeed, useLiveFeed, type StreamStatus } from "@/api/stream";
import type { TraceChip as TraceChipKind, TraceEvent } from "@/api/types";
import { TraceChip } from "@/components/chips";
import { Empty, ErrorNote, Money, Shimmer } from "@/components/kit";
import { longDate, zulu } from "@/lib/format";
import { cn } from "@/lib/utils";
import { eventRef, matchesTarget, timeOrdered } from "./model";
import { FilterChip, Principal } from "./parts";

const CHIP_ORDER: TraceChipKind[] = ["APPLIED", "DRAFTED", "HELD", "ASKED", "RULED", "LEARNED", "CITED", "DENIED", "LOCKED", "INFO"];
const PAGE = 150;

/**
 * J5 · Live: every trace event from every storm, newest first: the server's history (`/trace`) merged with
 * what the stream delivers while you watch. Storm Run shows one storm's feed; this is the whole of it.
 */
export function LiveTab() {
  const trace = useTrace();
  const live = useLiveFeed((s) => s.events);
  const status = useLiveFeed((s) => s.status);
  const [params, setParams] = useSearchParams();
  const target = params.get("target");
  const all = useMemo(() => mergeFeed(trace.data ?? [], live), [trace.data, live]);
  const [chip, setChip] = useState<TraceChipKind | "all">("all");
  const [grep, setGrep] = useState("");
  const [limit, setLimit] = useState(PAGE);

  const counts = useMemo(() => {
    const m = new Map<TraceChipKind, number>();
    for (const e of all) m.set(e.chip, (m.get(e.chip) ?? 0) + 1);
    return CHIP_ORDER.filter((c) => m.has(c)).map((c) => [c, m.get(c)!] as const);
  }, [all]);
  const needle = grep.trim().toLowerCase();
  const about = target ? all.filter((e) => matchesTarget(e.ref, target)) : all;
  const filtered = about.filter((e) => (chip === "all" || e.chip === chip) && (!needle || [e.summary, e.actor, e.ref ?? "", e.kind].some((s) => s.toLowerCase().includes(needle))));
  const clearTarget = () =>
    setParams(
      (prev) => {
        const next = new URLSearchParams(prev);
        next.delete("target");
        return next;
      },
      { replace: true },
    );
  const shown = filtered.slice(0, limit);
  const headed = timeOrdered(shown);

  if (trace.isLoading && !live.length) return <LiveSkeleton />;
  if (trace.isError && !live.length) return <ErrorNote error={trace.error} onRetry={() => void trace.refetch()} />;
  if (!all.length) return <Empty title="Nothing has happened yet">Events appear here as StormCheck reads, decides, asks and drafts.</Empty>;

  return (
    <div>
      <div className="flex flex-col gap-3 md:flex-row md:items-center md:justify-between">
        <div role="group" aria-label="Filter by chip" className="-mx-1 flex gap-1 overflow-x-auto px-1 pb-1 md:flex-wrap md:overflow-visible md:pb-0">
          <FilterChip active={chip === "all"} onClick={() => setChip("all")} label="all" n={all.length} />
          {counts.map(([c, n]) => (
            <FilterChip key={c} active={chip === c} onClick={() => setChip(chip === c ? "all" : c)} label={c.toLowerCase()} n={n} />
          ))}
        </div>
        <label className="relative flex h-9 w-full items-center md:w-[240px]">
          <span className="sr-only">Filter events by text, actor or ref</span>
          <Search className="pointer-events-none absolute left-3 size-3.5 text-slate-400" aria-hidden="true" />
          <input
            value={grep}
            onChange={(e) => setGrep(e.target.value)}
            placeholder="grep events"
            className="h-9 w-full rounded-lg bg-white pl-8 pr-3 text-[13px] text-navy-900 shadow-[inset_0_0_0_1px_var(--color-cloud-300)] outline-none placeholder:text-slate-400 focus:shadow-[inset_0_0_0_1.5px_var(--color-metar-ink)]"
          />
        </label>
      </div>

      {target ? (
        <p className="mt-3 flex flex-wrap items-center gap-2 text-[13px] text-slate-500">
          Events about
          <span className="inline-flex h-7 items-center gap-1 rounded-md bg-navy-900 pl-2 pr-1 font-mono text-[11.5px] text-cloud-50">
            {target}
            <button type="button" onClick={clearTarget} aria-label={`Show every event, not just ${target}`} className="inline-flex size-5 items-center justify-center rounded text-cloud-400 hover:bg-navy-800 hover:text-cloud-50">
              <X className="size-3.5" aria-hidden="true" />
            </button>
          </span>
          <span className="font-mono text-[11px] text-slate-400">
            {about.length} of {all.length}
          </span>
        </p>
      ) : null}

      <div className="mt-4 overflow-hidden rounded-xl bg-card shadow-[0_0_0_1px_var(--color-cloud-200),0_1px_2px_rgba(13,21,36,0.04)]">
        <div className="flex items-center justify-between gap-3 border-b border-cloud-100 px-5 py-2.5">
          <StreamState status={status} />
          <span className="font-mono text-[11px] text-slate-400">
            {filtered.length === all.length ? `${all.length} events` : `${filtered.length} of ${all.length} events`}
          </span>
        </div>
        {shown.length === 0 ? (
          <p className="px-5 py-10 text-center text-[13.5px] text-slate-500">{target && !about.length ? `No events about ${target} yet.` : "No events match."}</p>
        ) : (
          <ol aria-label="Trace events, newest first" aria-live="polite" aria-relevant="additions" className="relative">
            <AnimatePresence initial={false}>
              {shown.map((e, i) => (
                <LiveRow key={e.seq} event={e} dated={!headed} dayBreak={headed && (i === 0 || longDate(shown[i - 1].at) !== longDate(e.at))} />
              ))}
            </AnimatePresence>
          </ol>
        )}
        <footer className="flex flex-wrap items-center justify-between gap-3 border-t border-cloud-100 px-5 py-3 text-[12.5px] text-slate-500">
          <span>Every event is also a content-hashed commit.</span>
          <span className="flex items-center gap-2">
            {filtered.length > shown.length ? (
              <button type="button" onClick={() => setLimit((l) => l + PAGE)} className="rounded-lg px-3 py-1.5 text-[13px] font-medium text-metar-ink hover:bg-cloud-50">
                Show older events
              </button>
            ) : null}
            <button
              type="button"
              onClick={() =>
                setParams(
                  (prev) => {
                    const next = new URLSearchParams(prev);
                    next.set("tab", "commits");
                    return next;
                  },
                  { replace: true },
                )
              }
              className="inline-flex items-center gap-1 rounded-lg px-2 py-1.5 text-[13px] font-medium text-metar-ink hover:bg-cloud-50"
            >
              Commit log <ArrowRight className="size-3.5" aria-hidden="true" />
            </button>
          </span>
        </footer>
      </div>
    </div>
  );
}

const STATUS_TEXT: Record<StreamStatus, string> = { live: "live", polling: "polling every 2 s", connecting: "connecting", offline: "offline · showing what was loaded" };

function StreamState({ status }: { status: StreamStatus }) {
  return (
    <span className="inline-flex items-center gap-2 font-mono text-[11.5px] text-slate-500" role="status">
      <span className="relative flex size-2" aria-hidden="true">
        {status === "live" ? <span className="absolute inline-flex size-full animate-ping rounded-full bg-navy-800/40" /> : null}
        <span className={cn("relative inline-flex size-2 rounded-full", status === "live" ? "bg-navy-800" : status === "offline" ? "bg-cloud-400" : "bg-slate-400")} />
      </span>
      {STATUS_TEXT[status]}
    </span>
  );
}

/** One event, in the feed's grammar: past tense, then `ref · €amount · actor`, then its chip. */
function LiveRow({ event: e, dayBreak, dated }: { event: TraceEvent; dayBreak: boolean; dated: boolean }) {
  const ref = eventRef(e.ref);
  return (
    <motion.li
      layout="position"
      initial={{ opacity: 0, y: -8 }}
      animate={{ opacity: 1, y: 0 }}
      exit={{ opacity: 0 }}
      transition={{ duration: 0.35, ease: [0.16, 1, 0.3, 1] }}
      className="border-t border-cloud-100 first:border-t-0"
    >
      {dayBreak ? (
        <div className="border-b border-cloud-100 bg-cloud-25 px-5 py-1.5" aria-hidden="true">
          <span className="micro text-slate-400">{longDate(e.at)}</span>
        </div>
      ) : null}
      <div className="grid grid-cols-[52px_minmax(0,1fr)_auto] items-start gap-3 px-5 py-2.5 md:grid-cols-[60px_minmax(0,1fr)_auto]">
        <span className="figure pt-0.5 text-[12px] leading-tight text-slate-400">
          {dated ? <span className="block text-slate-500">{longDate(e.at).slice(0, -5)}</span> : null}
          {zulu(e.at)}
        </span>
        <div className="min-w-0">
          <p className="text-[13.5px] leading-snug text-navy-900">{e.summary}</p>
          <p className="mt-1 flex flex-wrap items-center gap-x-2 gap-y-1 text-[11.5px] text-slate-400">
            {ref ? (
              ref.to ? (
                <Link to={ref.to} className="font-mono text-metar-ink hover:underline">
                  {ref.label}
                </Link>
              ) : (
                <span className="font-mono">{ref.label}</span>
              )
            ) : null}
            {e.amount_cents !== null && e.amount_cents !== undefined ? (
              <>
                {ref ? <span aria-hidden="true">·</span> : null}
                <Money cents={e.amount_cents} className="text-[12px] text-slate-600" />
              </>
            ) : null}
            {ref || (e.amount_cents !== null && e.amount_cents !== undefined) ? <span aria-hidden="true">·</span> : null}
            <Principal principal={e.actor} className="[&>span:last-child]:text-[11px] [&>span:last-child]:text-slate-400" />
            <span className="font-mono text-cloud-400">#{e.seq}</span>
          </p>
        </div>
        <TraceChip chip={e.chip} className="mt-0.5" />
      </div>
    </motion.li>
  );
}

function LiveSkeleton() {
  return (
    <div aria-busy="true" aria-label="Loading events">
      <div className="flex gap-1.5">
        {Array.from({ length: 6 }, (_, i) => (
          <Shimmer key={i} className="h-7 w-20 rounded-md" />
        ))}
      </div>
      <div className="mt-4 flex flex-col gap-px overflow-hidden rounded-xl">
        {Array.from({ length: 9 }, (_, i) => (
          <Shimmer key={i} className="h-12 rounded-none" />
        ))}
      </div>
    </div>
  );
}
