import { useEffect, useMemo, useRef, useState } from "react";
import { Link } from "react-router";
import { AnimatePresence, motion, useReducedMotion } from "motion/react";
import { ArrowUpRight } from "lucide-react";
import { toast } from "sonner";
import { api } from "@/api/client";
import { invalidateAfterWrite, useAudit } from "@/api/queries";
import type { JournalEntry, Role } from "@/api/types";
import { MicroLabel, StatusChip } from "@/components/chips";
import { JournalCard, KIND_LABEL, statusLabel } from "@/components/journal";
import { ActionPair, Empty, ErrorNote, Money, Shimmer } from "@/components/kit";
import { Sheet, SheetContent, SheetDescription, SheetHeader, SheetTitle } from "@/components/ui/sheet";
import { count, longDate, periodLabel, shortId, zuluDay } from "@/lib/format";
import { cn } from "@/lib/utils";
import { preparerRole } from "./model";
import { Denied, Segmented } from "./ui";

type Filter = "draft" | "approved";

const KIND_ORDER: JournalEntry["kind"][] = ["change_in_estimate", "compensation_estimate", "recode", "out_of_period_adjustment", "claim_approved", "derecognition", "voucher_in_lieu", "voucher_void"];
const rank = (k: JournalEntry["kind"]) => {
  const i = KIND_ORDER.indexOf(k);
  return i < 0 ? KIND_ORDER.length : i;
};

/** Parked journals for the period, newest first, with [Edit][Approve] where the seat may act. */
export function JournalDrafts({
  period,
  entries,
  loading,
  error,
  onRetry,
  role,
  canAct,
  focusId,
}: {
  period: string;
  entries: JournalEntry[] | undefined;
  loading: boolean;
  error: unknown;
  onRetry: () => void;
  role: Role;
  canAct: boolean;
  focusId?: string | null;
}) {
  const [filter, setFilter] = useState<Filter>("draft");
  const [editing, setEditing] = useState<JournalEntry | null>(null);
  const [ringed, setRinged] = useState<string | null>(null);
  const reduce = useReducedMotion();
  const jumped = useRef<string | null>(null);

  // A deep link (#JE-…) opens the entry's tab, scrolls to it once and rings it briefly. Later refetches don't scroll.
  useEffect(() => {
    if (!focusId || jumped.current === focusId || !entries) return;
    const target = entries.find((e) => e.id === focusId);
    if (!target) return;
    jumped.current = focusId;
    const open = window.setTimeout(() => {
      setFilter(target.status === "draft" ? "draft" : "approved");
      setRinged(focusId);
    }, 0);
    const scroll = window.setTimeout(() => document.getElementById(focusId)?.scrollIntoView({ behavior: reduce ? "auto" : "smooth", block: "center" }), 180);
    const unring = window.setTimeout(() => setRinged(null), 2800);
    return () => {
      window.clearTimeout(open);
      window.clearTimeout(scroll);
      window.clearTimeout(unring);
    };
  }, [focusId, entries, reduce]);
  const sorted = useMemo(() => [...(entries ?? [])].sort((a, b) => b.event_date.localeCompare(a.event_date) || rank(a.kind) - rank(b.kind) || a.id.localeCompare(b.id)), [entries]);
  const drafts = sorted.filter((e) => e.status === "draft");
  const approved = sorted.filter((e) => e.status !== "draft");
  const shown = filter === "draft" ? drafts : approved;

  return (
    <section id="journal" aria-labelledby="journal-title" className="scroll-mt-20">
      <div className="flex flex-wrap items-end justify-between gap-x-4 gap-y-2 px-1">
        <div className="min-w-0">
          <MicroLabel>Parked · StormCheck never posts</MicroLabel>
          <h2 id="journal-title" className="mt-1 text-[17px] font-semibold text-navy-900">
            Journal · {periodLabel(period)}
          </h2>
          <p className="mt-0.5 text-[13px] text-slate-500">Drafted, pending approval. The preparer can never approve their own entry.</p>
        </div>
        <Segmented
          label="Journal status"
          value={filter}
          onChange={setFilter}
          size="sm"
          options={[
            { value: "draft", label: "Pending approval", badge: entries ? <Badge n={drafts.length} on={filter === "draft"} /> : null },
            { value: "approved", label: "Approved", badge: entries ? <Badge n={approved.length} on={filter === "approved"} /> : null },
          ]}
        />
      </div>

      <div className="mt-3">
        {error ? (
          <ErrorNote error={error} onRetry={onRetry} />
        ) : loading || !entries ? (
          <div className="grid grid-cols-[minmax(0,1fr)] gap-3 lg:grid-cols-2">
            <Shimmer className="h-[230px]" />
            <Shimmer className="h-[230px]" />
          </div>
        ) : !shown.length ? (
          <Empty title={filter === "draft" ? `Nothing waiting for approval in ${periodLabel(period)}` : `Nothing approved yet in ${periodLabel(period)}`}>
            {filter === "draft" ? "Month-end drafts the change in estimate here, pending approval." : "Approved journals stay parked; posting happens in the ledger, never from StormCheck."}
          </Empty>
        ) : (
          <ul className="grid grid-cols-[minmax(0,1fr)] items-start gap-3 lg:grid-cols-2">
            <AnimatePresence initial={false}>
              {shown.map((je) => (
                <motion.li
                  key={je.id}
                  layout
                  initial={{ opacity: 0, y: 6 }}
                  animate={{ opacity: 1, y: 0 }}
                  exit={{ opacity: 0, scale: 0.98 }}
                  transition={{ duration: 0.25 }}
                  id={je.id}
                  data-testid={`je-${je.id}`}
                  className={cn("scroll-mt-24 rounded-xl transition-shadow duration-500 [&_tbody_td:nth-child(2)]:pr-5", ringed === je.id && "shadow-[0_0_0_2px_var(--color-navy-900)]")}
                >
                  <JournalCard entry={je} actions={<EntryActions key={`${je.id}:${role}`} entry={je} role={role} canAct={canAct} onEdit={() => setEditing(je)} />} />
                </motion.li>
              ))}
            </AnimatePresence>
          </ul>
        )}
      </div>

      <ProposeChange entry={editing} onClose={() => setEditing(null)} />
    </section>
  );
}

function Badge({ n, on }: { n: number; on: boolean }) {
  return <span className={cn("inline-flex h-[18px] min-w-[18px] items-center justify-center rounded-full px-1 font-mono text-[10px] font-bold", on ? "bg-white/15 text-cloud-50" : "bg-cloud-100 text-slate-500")}>{count(n)}</span>;
}

type ActState = { kind: "idle" } | { kind: "busy" } | { kind: "refused"; error: unknown } | { kind: "approved" };

/** [Edit][Approve]. A refusal (SoD or authority) replaces the pair in place with the server's reason. */
function EntryActions({ entry, role, canAct, onEdit }: { entry: JournalEntry; role: Role; canAct: boolean; onEdit: () => void }) {
  const [state, setState] = useState<ActState>({ kind: "idle" });
  const own = preparerRole(entry.preparer) === role;
  const trail = (
    <button type="button" onClick={onEdit} className="rounded-lg px-2.5 py-1.5 text-[12.5px] font-medium text-slate-600 shadow-[inset_0_0_0_1px_var(--color-cloud-300)] transition-colors hover:bg-cloud-50 hover:text-navy-900">
      View trail
    </button>
  );
  if (entry.status !== "draft") return trail;
  if (!canAct && !own)
    return (
      <span className="inline-flex items-center gap-3">
        <span className="text-[12px] text-slate-400">pending approval</span>
        {trail}
      </span>
    );
  if (state.kind === "refused") return <Denied error={state.error} className="basis-full rounded-lg bg-cloud-50 px-2.5 py-2 shadow-[inset_0_0_0_1px_var(--color-cloud-200)]" />;
  if (state.kind === "approved")
    return (
      <StatusChip tone="slate" dot={false}>
        approved · parked
      </StatusChip>
    );

  const approve = async () => {
    setState({ kind: "busy" });
    try {
      const je = await api.approveJournal(entry.id);
      setState({ kind: "approved" });
      toast(`${je.id ?? entry.id} approved`, { description: "Parked, not posted. Posting stays in the ledger." });
      await invalidateAfterWrite();
    } catch (e) {
      setState({ kind: "refused", error: e });
      // The refusal is itself on the record (an access_denied commit): refresh what shows it.
      void invalidateAfterWrite();
    }
  };

  return <ActionPair onEdit={onEdit} onApprove={() => void approve()} busy={state.kind === "busy"} />;
}

/** Edit opens this, read-only: drafts are parked and amounts are never typed, so a change goes to its source. */
function ProposeChange({ entry, onClose }: { entry: JournalEntry | null; onClose: () => void }) {
  const audit = useAudit(entry?.id);
  const flight = entry?.source_decision_id ?? entry?.lines.map((l) => l.dims?.flight).find(Boolean) ?? null;
  return (
    <Sheet open={!!entry} onOpenChange={(o) => !o && onClose()}>
      <SheetContent side="right" className="w-full gap-0 overflow-y-auto bg-background p-0 sm:max-w-[520px]">
        {entry ? (
          <>
            <SheetHeader className="border-b border-cloud-200 bg-card px-5 pb-4 pt-5">
              <MicroLabel>Propose a change · read-only</MicroLabel>
              <SheetTitle className="mt-1 text-[17px] font-semibold text-navy-900">
                {entry.id} <span className="font-normal text-slate-500">· {KIND_LABEL[entry.kind] ?? entry.kind.replace(/_/g, " ")}</span>
              </SheetTitle>
              <SheetDescription className="mt-1 text-[13px] leading-relaxed text-slate-500">
                Drafts are parked and their amounts are never typed. Change what the entry was built from and StormCheck redrafts it, with the trail.
              </SheetDescription>
            </SheetHeader>

            <div className="flex flex-col gap-5 px-5 py-5">
              <EntryLines entry={entry} />

              <div>
                <h3 className="text-[13.5px] font-semibold text-navy-900">Where a change goes</h3>
                <ul className="mt-2 flex flex-col overflow-hidden rounded-xl bg-card shadow-[0_0_0_1px_var(--color-cloud-200)]">
                  {flight ? (
                    <Route to={`/flights/${encodeURIComponent(flight)}`} title={`Challenge ${shortId(flight)}'s cause`} body="A new fact routes to the right person; it never flips a decision by itself." />
                  ) : null}
                  <Route to="/questions" title="Answer or reject the estimate" body="A ruling becomes a versioned rule, replayed before it applies." />
                  <Route to="/trace" title="Trace every source" body="Blame the € back to its log line, rule and ruling." />
                </ul>
              </div>

              <div>
                <h3 className="text-[13.5px] font-semibold text-navy-900">Audit trail</h3>
                <div className="mt-2">
                  {audit.isError ? <ErrorNote error={audit.error} onRetry={() => void audit.refetch()} /> : !audit.data ? <Shimmer className="h-24" /> : <AuditTrail data={audit.data} />}
                </div>
              </div>
            </div>
          </>
        ) : null}
      </SheetContent>
    </Sheet>
  );
}

/** The entry, read-only, in a form that fits a sheet: one line per account, amounts on the right. */
function EntryLines({ entry }: { entry: JournalEntry }) {
  const dr = entry.lines.reduce((t, l) => t + (l.dr_cents ?? 0), 0);
  const cr = entry.lines.reduce((t, l) => t + (l.cr_cents ?? 0), 0);
  return (
    <div className="rounded-xl bg-card shadow-[0_0_0_1px_var(--color-cloud-200)]">
      <div className="px-4 pt-3.5">
        <MicroLabel>{statusLabel(entry)}</MicroLabel>
        <p className="mt-1.5 text-[13px] leading-relaxed text-slate-600">{entry.memo}</p>
      </div>
      <ul className="mt-3">
        {entry.lines.map((l, i) => (
          <li key={i} className="grid grid-cols-[28px_minmax(0,1fr)_auto] items-baseline gap-2 border-t border-cloud-100 px-4 py-2 text-[13px]">
            <span className="font-mono text-[11px] text-slate-400">{l.dr_cents ? "Dr" : "Cr"}</span>
            <span className={cn("min-w-0", !l.dr_cents && "pl-4")}>
              <span className="font-mono text-[11.5px] text-slate-500">{l.account}</span> <span className="text-navy-900">{l.account_name}</span>
            </span>
            <Money cents={l.dr_cents || l.cr_cents || 0} withCents className={cn("text-[13px]", l.dr_cents ? "text-navy-900" : "text-slate-600")} />
          </li>
        ))}
        <li className="flex items-baseline justify-between gap-3 border-t border-cloud-200 px-4 py-2 text-[12.5px] text-slate-500">
          <span>{dr === cr ? "Balanced" : "Out of balance"}</span>
          <span>
            Dr <Money cents={dr} withCents /> · Cr <Money cents={cr} withCents />
          </span>
        </li>
      </ul>
      <p className="border-t border-cloud-100 px-4 py-2.5 text-[12px] text-slate-500">
        Event {longDate(entry.event_date)} · period {periodLabel(entry.period)} · prepared by {entry.preparer}
      </p>
    </div>
  );
}

function Route({ to, title, body }: { to: string; title: string; body: string }) {
  return (
    <li className="border-t border-cloud-100 first:border-t-0">
      <Link to={to} className="group flex items-start justify-between gap-3 px-4 py-3 transition-colors hover:bg-cloud-25">
        <span className="min-w-0">
          <span className="block text-[13.5px] font-medium text-navy-900">{title}</span>
          <span className="mt-0.5 block text-[12.5px] leading-snug text-slate-500">{body}</span>
        </span>
        <ArrowUpRight className="mt-0.5 size-4 shrink-0 text-slate-400 transition-colors group-hover:text-navy-900" aria-hidden="true" />
      </Link>
    </li>
  );
}

type CommitLike = { hash?: string; kind?: string; actor?: string; message?: string; at?: string };

const isObj = (v: unknown): v is Record<string, unknown> => !!v && typeof v === "object" && !Array.isArray(v);
const short = (v: unknown) => (v === null || v === undefined ? "—" : typeof v === "object" ? JSON.stringify(v) : String(v));

/** GET /audit/{je_id} is loosely typed (JE + register rows + decision commits): show what's there, plainly. */
function AuditTrail({ data }: { data: Record<string, unknown> }) {
  const lists = Object.entries(data).filter(([, v]) => Array.isArray(v)) as [string, unknown[]][];
  const commits = lists.filter(([k, v]) => /commit/i.test(k) || v.some((x) => isObj(x) && "hash" in x));
  const others = lists.filter((l) => !commits.includes(l));
  if (!commits.length && !others.length) return <p className="text-[13px] text-slate-500">No trail returned for this entry.</p>;
  return (
    <div className="flex flex-col gap-3">
      {commits.map(([key, rows]) => (
        <ol key={key} className="relative flex flex-col gap-0 rounded-xl bg-card px-4 py-1 shadow-[0_0_0_1px_var(--color-cloud-200)]">
          {(rows as CommitLike[]).map((c, i) => (
            <li key={`${c.hash ?? i}`} className="grid grid-cols-[64px_minmax(0,1fr)] gap-3 border-t border-cloud-100 py-2.5 first:border-t-0">
              <span className="pt-0.5 font-mono text-[11px] text-slate-400">{(c.hash ?? "").slice(0, 7) || "—"}</span>
              <span className="min-w-0">
                <span className="block text-[13px] leading-snug text-navy-900">{c.message ?? short(c)}</span>
                <span className="mt-0.5 block font-mono text-[11px] text-slate-400">{[c.kind, c.actor, c.at ? zuluDay(c.at) : null].filter(Boolean).join(" · ")}</span>
              </span>
            </li>
          ))}
        </ol>
      ))}
      {others.map(([key, rows]) => (
        <div key={key} className="rounded-xl bg-card px-4 py-3 shadow-[0_0_0_1px_var(--color-cloud-200)]">
          <p className="micro text-slate-400">{key.replace(/_/g, " ")}</p>
          <ul className="mt-1.5 flex flex-col gap-1.5">
            {rows.map((r, i) => (
              <li key={i} className="font-mono text-[11.5px] leading-relaxed text-slate-600">
                {isObj(r)
                  ? Object.entries(r)
                      .map(([k, v]) => `${k} ${short(v)}`)
                      .join(" · ")
                  : short(r)}
              </li>
            ))}
          </ul>
        </div>
      ))}
    </div>
  );
}
