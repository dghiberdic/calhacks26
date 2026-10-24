import { Fragment, useEffect, useMemo, useRef, useState } from "react";
import { Link, useSearchParams } from "react-router";
import { keepPreviousData, useQuery } from "@tanstack/react-query";
import { motion, useReducedMotion } from "motion/react";
import { ChevronRight, GitCommitVertical, Search } from "lucide-react";
import { api } from "@/api/client";
import { qk } from "@/api/queries";
import type { Commit, CommitKind } from "@/api/types";
import { Empty, ErrorNote, Shimmer } from "@/components/kit";
import { longDate, zulu } from "@/lib/format";
import { cn } from "@/lib/utils";
import { KIND_ORDER, blameTarget, chainOrder, shortHash, timeOrdered } from "./model";
import { FilterChip, Principal } from "./parts";

const PAGE = 100;


/** J5 · Commits: `git log --oneline`, made legible. Newest first; each commit opens to its payload, inputs and parent. */
export function CommitsTab() {
  const reduce = useReducedMotion();
  const [params, setParams] = useSearchParams();
  const [limit, setLimit] = useState(PAGE);
  const commits = useQuery({ queryKey: qk.commits(limit), queryFn: () => api.commits(limit), placeholderData: keepPreviousData });
  const [kind, setKind] = useState<CommitKind | "all">("all");
  const grep = params.get("q") ?? "";
  const setGrep = (q: string) =>
    setParams(
      (prev) => {
        const next = new URLSearchParams(prev);
        if (q) next.set("q", q);
        else next.delete("q");
        return next;
      },
      { replace: true },
    );
  const open = params.get("commit");
  const [flash, setFlash] = useState<string | null>(null);
  const listRef = useRef<HTMLOListElement>(null);

  const { ordered: sorted, linked } = useMemo(() => chainOrder(commits.data ?? []), [commits.data]);
  const byHash = useMemo(() => new Map(sorted.map((c) => [c.hash, c])), [sorted]);
  const counts = useMemo(() => {
    const m = new Map<CommitKind, number>();
    for (const c of sorted) m.set(c.kind, (m.get(c.kind) ?? 0) + 1);
    return [...m.entries()].sort((a, b) => KIND_ORDER.indexOf(a[0]) - KIND_ORDER.indexOf(b[0]));
  }, [sorted]);

  const headed = useMemo(() => timeOrdered(sorted), [sorted]);
  const needle = grep.trim().toLowerCase();
  const shown = sorted.filter(
    (c) => (kind === "all" || c.kind === kind) && (!needle || [c.hash, c.message, c.actor, c.payload_ref, c.kind].some((s) => s.toLowerCase().includes(needle))),
  );

  const setOpen = (hash: string | null) =>
    setParams(
      (prev) => {
        const next = new URLSearchParams(prev);
        if (hash) next.set("commit", hash);
        else next.delete("commit");
        return next;
      },
      { replace: true },
    );

  /** Jump to a commit (a parent, an input): clear filters that hide it, open it, scroll, outline it. */
  const jump = (hash: string) => {
    const target = byHash.get(hash);
    if (!target) return;
    if (kind !== "all" && target.kind !== kind) setKind("all");
    if (needle) setGrep("");
    setOpen(hash);
    setFlash(hash);
    window.setTimeout(() => setFlash(null), 2400);
  };

  // A deep link (?commit=) or a jump scrolls its row into view once it renders.
  useEffect(() => {
    if (!open || !commits.data) return;
    const el = listRef.current?.querySelector<HTMLElement>(`[data-hash="${CSS.escape(open)}"]`);
    el?.scrollIntoView({ block: "center", behavior: reduce ? "auto" : "smooth" });
  }, [open, commits.data, reduce, kind, needle]);

  if (commits.isLoading) return <CommitsSkeleton />;
  if (commits.isError) return <ErrorNote error={commits.error} onRetry={() => void commits.refetch()} />;
  if (!sorted.length) return <Empty title="No commits yet">Every fact, decision, rule, ruling, journal event and LLM call lands here as a commit.</Empty>;

  return (
    <div>
      <div className="flex flex-col gap-3 md:flex-row md:items-center md:justify-between">
        <div role="group" aria-label="Filter by kind" className="-mx-1 flex gap-1 overflow-x-auto px-1 pb-1 md:flex-wrap md:overflow-visible md:pb-0">
          <FilterChip active={kind === "all"} onClick={() => setKind("all")} label="all" n={sorted.length} />
          {counts.map(([k, n]) => (
            <FilterChip key={k} active={kind === k} onClick={() => setKind(kind === k ? "all" : k)} label={k} n={n} />
          ))}
        </div>
        <label className="relative flex h-9 w-full items-center md:w-[260px]">
          <span className="sr-only">Filter commits by message, hash or actor</span>
          <Search className="pointer-events-none absolute left-3 size-3.5 text-slate-400" aria-hidden="true" />
          <input
            value={grep}
            onChange={(e) => setGrep(e.target.value)}
            placeholder="grep message, hash, actor"
            className="h-9 w-full rounded-lg bg-white pl-8 pr-3 text-[13px] text-navy-900 shadow-[inset_0_0_0_1px_var(--color-cloud-300)] outline-none placeholder:text-slate-400 focus:shadow-[inset_0_0_0_1.5px_var(--color-metar-ink)]"
          />
        </label>
      </div>

      <div className="mt-4 overflow-hidden rounded-xl bg-card shadow-[0_0_0_1px_var(--color-cloud-200),0_1px_2px_rgba(13,21,36,0.04)]">
        {shown.length === 0 ? (
          <p className="px-5 py-10 text-center text-[13.5px] text-slate-500">No commits match.</p>
        ) : (
          <ol ref={listRef} className="relative" aria-label="Commits, newest first">
            {/* the graph rail */}
            <span className="pointer-events-none absolute bottom-0 left-[27px] top-0 w-px bg-cloud-200" aria-hidden="true" />
            {shown.map((c, i) => {
              const day = longDate(c.at);
              const header = headed && (i === 0 || longDate(shown[i - 1].at) !== day);
              return (
                <Fragment key={c.hash}>
                  {header ? (
                    <li className="relative border-t border-cloud-100 bg-cloud-25 py-1.5 pl-[52px] pr-5 first:border-t-0" aria-hidden="true">
                      <span className="micro text-slate-400">{day}</span>
                    </li>
                  ) : null}
                  <CommitRow commit={c} index={i} dated={!headed} open={open === c.hash} flash={flash === c.hash} onToggle={() => setOpen(open === c.hash ? null : c.hash)} byHash={byHash} onJump={jump} />
                </Fragment>
              );
            })}
          </ol>
        )}
        <footer className="flex flex-wrap items-center justify-between gap-3 border-t border-cloud-100 px-5 py-3 text-[12.5px] text-slate-500">
          <span className="flex flex-wrap items-center gap-x-4 gap-y-1">
            <Legend />
            <span className="font-mono text-[11px] text-slate-400">
              {sorted.length} loaded · {linked ? "one chain, parent to parent" : "more than one chain on this page"}
            </span>
          </span>
          {(commits.data?.length ?? 0) >= limit ? (
            <button type="button" onClick={() => setLimit((l) => l + PAGE)} disabled={commits.isFetching} className="rounded-lg px-3 py-1.5 text-[13px] font-medium text-metar-ink hover:bg-cloud-50 disabled:opacity-50">
              {commits.isFetching ? "Loading…" : "Load older commits"}
            </button>
          ) : null}
        </footer>
      </div>
      <p className="mt-3 text-[12.5px] text-slate-400">Replay never calls the LLM: an llm_call commit is read back, not re-run.</p>
    </div>
  );
}


/** Node shapes carry the kind without colour: ● commit · ○ llm_call · ■ access_denied. */
function Node({ kind }: { kind: CommitKind }) {
  if (kind === "llm_call") return <span className="block size-[9px] rounded-full bg-card shadow-[inset_0_0_0_1.5px_var(--color-navy-800)]" />;
  if (kind === "access_denied") return <span className="block size-[8px] rounded-[1.5px] bg-navy-900" />;
  return <span className="block size-[7px] rounded-full bg-navy-800" />;
}

function Legend() {
  return (
    <span className="flex items-center gap-3 font-mono text-[11px] text-slate-500" aria-label="Legend">
      <span className="inline-flex items-center gap-1.5">
        <Node kind="decision" /> commit
      </span>
      <span className="inline-flex items-center gap-1.5">
        <Node kind="llm_call" /> llm_call
      </span>
      <span className="inline-flex items-center gap-1.5">
        <Node kind="access_denied" /> access_denied
      </span>
    </span>
  );
}

function CommitRow({ commit: c, index, dated, open, flash, onToggle, byHash, onJump }: { commit: Commit; index: number; dated: boolean; open: boolean; flash: boolean; onToggle: () => void; byHash: Map<string, Commit>; onJump: (hash: string) => void }) {
  const reduce = useReducedMotion();
  return (
    <motion.li
      data-hash={c.hash}
      initial={reduce ? false : { opacity: 0 }}
      animate={{ opacity: 1 }}
      transition={{ delay: Math.min(index, 20) * 0.015, duration: 0.25 }}
      className={cn("relative border-t border-cloud-100 transition-colors duration-500", open && "bg-cloud-25", flash && "bg-metar-wash/60")}
    >
      <button
        type="button"
        onClick={onToggle}
        aria-expanded={open}
        className="grid w-full grid-cols-[40px_minmax(0,1fr)] items-start gap-x-3 py-2.5 pr-4 text-left transition-colors hover:bg-cloud-25 focus-visible:outline-2 focus-visible:-outline-offset-2 focus-visible:outline-metar-ink md:grid-cols-[40px_72px_112px_minmax(0,1fr)_180px_92px] md:items-center md:pr-5"
      >
        <span className="relative z-10 flex h-5 items-center justify-center pl-[15px] md:h-auto" aria-hidden="true">
          <Node kind={c.kind} />
        </span>
        {/* phone: three short lines */}
        <span className="block min-w-0 md:contents">
          <span className="flex items-center gap-2 md:contents">
            <span className="font-mono text-[12px] font-bold text-navy-900">{shortHash(c.hash)}</span>
            <span className="md:block">
              <KindChip kind={c.kind} />
            </span>
            <span className="figure ml-auto text-[12px] text-slate-400 md:hidden">{dated ? `${longDate(c.at)} · ${zulu(c.at)}` : zulu(c.at)}</span>
          </span>
          <span className={cn("mt-1 block text-[13.5px] leading-snug text-navy-900 md:mt-0", !open && "md:truncate")}>{c.message}</span>
          <span className="mt-1.5 flex md:mt-0">
            <Principal principal={c.actor} />
          </span>
          <span className="figure hidden text-right text-[12px] leading-tight text-slate-400 md:block">
            {dated ? (
              <>
                <span className="block text-slate-500">{longDate(c.at)}</span>
                {zulu(c.at)}
              </>
            ) : (
              zulu(c.at)
            )}
          </span>
        </span>
      </button>
      {open ? <CommitDetail commit={c} byHash={byHash} onJump={onJump} /> : null}
    </motion.li>
  );
}

function KindChip({ kind }: { kind: CommitKind }) {
  return (
    <span className={cn("inline-flex h-5 items-center rounded px-1.5 font-mono text-[10.5px]", kind === "access_denied" ? "bg-navy-900 text-cloud-50" : "bg-cloud-100 text-slate-600")}>{kind}</span>
  );
}

/** `git show`, short: the full hash, the parent, what the commit stores and what it was computed from. */
function CommitDetail({ commit: c, byHash, onJump }: { commit: Commit; byHash: Map<string, Commit>; onJump: (hash: string) => void }) {
  const target = blameTarget(c.payload_ref);
  const inputs = c.inputs ?? [];
  const parentLoaded = c.parent ? byHash.has(c.parent) : false;
  return (
    <div className="grid gap-x-6 gap-y-2.5 pb-4 pl-[52px] pr-5 pt-1 text-[12.5px] md:grid-cols-[96px_minmax(0,1fr)]">
      <Term>commit</Term>
      <span className="break-all font-mono text-[11.5px] text-navy-900">{c.hash}</span>
      <Term>parent</Term>
      <span>
        {c.parent ? (
          parentLoaded ? (
            <button type="button" onClick={() => onJump(c.parent!)} className="inline-flex items-center gap-1 font-mono text-[11.5px] text-metar-ink hover:underline">
              {shortHash(c.parent, 12)}
              <ChevronRight className="size-3" aria-hidden="true" />
              <span className="font-sans text-[12px] text-slate-500">{byHash.get(c.parent)?.message}</span>
            </button>
          ) : (
            <span className="font-mono text-[11.5px] text-slate-500">{shortHash(c.parent, 12)} · older than this page</span>
          )
        ) : (
          <span className="text-slate-400">none · the first commit</span>
        )}
      </span>
      <Term>payload</Term>
      <span className="flex min-w-0 flex-wrap items-center gap-x-3 gap-y-1">
        <span className="font-mono break-all text-[11.5px] text-navy-900">{c.payload_ref}</span>
        <span className="font-mono text-[11px] text-slate-400">sha256 {shortHash(c.payload_hash, 12)}</span>
      </span>
      {inputs.length ? (
        <>
          <Term>inputs</Term>
          <span className="flex flex-wrap gap-1.5">
            {inputs.map((input) => {
              const hit = byHash.get(input) ?? [...byHash.values()].find((x) => x.payload_hash === input);
              return hit ? (
                <button key={input} type="button" onClick={() => onJump(hit.hash)} title={hit.message} className="inline-flex h-6 items-center rounded-md bg-white px-1.5 font-mono text-[11px] text-metar-ink shadow-[inset_0_0_0_1px_var(--color-cloud-300)] hover:bg-cloud-50">
                  {shortHash(hit.hash)} · {hit.kind}
                </button>
              ) : (
                <span key={input} className="font-mono inline-flex h-6 items-center rounded-md bg-cloud-100 px-1.5 text-[11px] text-slate-600">
                  {/^[0-9a-f]{16,}$/.test(input) ? shortHash(input, 10) : input}
                </span>
              );
            })}
          </span>
        </>
      ) : null}
      <Term>at</Term>
      <span className="figure text-slate-600">
        {longDate(c.at)} · {zulu(c.at)}
      </span>
      {target ? (
        <>
          <span className="hidden md:block" />
          <Link to={`/trace?tab=blame&target=${encodeURIComponent(target)}`} className="inline-flex w-fit items-center gap-1.5 text-[12.5px] font-medium text-metar-ink hover:underline">
            <GitCommitVertical className="size-3.5" aria-hidden="true" />
            Blame {target}
          </Link>
        </>
      ) : null}
    </div>
  );
}

function Term({ children }: { children: string }) {
  return <span className="micro pt-0.5 text-slate-400">{children}</span>;
}

function CommitsSkeleton() {
  return (
    <div aria-busy="true" aria-label="Loading commits">
      <div className="flex gap-1.5">
        {Array.from({ length: 6 }, (_, i) => (
          <Shimmer key={i} className="h-7 w-20 rounded-md" />
        ))}
      </div>
      <div className="mt-4 flex flex-col gap-px overflow-hidden rounded-xl">
        {Array.from({ length: 9 }, (_, i) => (
          <Shimmer key={i} className="h-11 rounded-none" />
        ))}
      </div>
    </div>
  );
}
