import { useState } from "react";
import { AnimatePresence, motion } from "motion/react";
import { ArrowDown, Check, Lock, Minus } from "lucide-react";
import { toast } from "sonner";
import { api } from "@/api/client";
import { invalidateAfterWrite, useInvariants } from "@/api/queries";
import type { InvariantResult, MonthEndResponse } from "@/api/types";
import { MicroLabel, StatusChip, TiesChip } from "@/components/chips";
import { Empty, ErrorNote, Shimmer } from "@/components/kit";
import { Button } from "@/components/ui/button";
import { Dialog, DialogContent, DialogDescription, DialogFooter, DialogHeader, DialogTitle } from "@/components/ui/dialog";
import { count, eur, periodLabel } from "@/lib/format";
import { stormName } from "@/lib/storms";
import { cn } from "@/lib/utils";
import { cohortName, liabilityChange } from "./model";
import { Denied } from "./ui";

const METHOD: Record<string, string> = { bf: "Bornhuetter-Ferguson", expected_loss: "Expected loss", chain_ladder: "Chain ladder" };

/** A rail block after the first: ruled above when stacked, ruled at the left when side by side. */
const BLOCK = "mx-5 mt-4 border-t border-cloud-100 pt-4 md:mx-0 md:mt-0 md:border-l md:border-t-0 md:px-5 md:pt-0 min-[87.5rem]:mx-5 min-[87.5rem]:mt-4 min-[87.5rem]:border-l-0 min-[87.5rem]:border-t min-[87.5rem]:px-0 min-[87.5rem]:pt-4";

/** The close for one period: run month-end (drafts the change in estimate), then lock once it ties. */
export function CloseRail({
  period,
  locked,
  canAct,
  monthEnd,
  onMonthEnd,
  onLocked,
  pendingDrafts,
  tiesToGl,
}: {
  period: string;
  locked: boolean;
  canAct: boolean;
  pendingDrafts: number;
  tiesToGl: boolean | null;
  monthEnd: MonthEndResponse | null;
  onMonthEnd: (res: MonthEndResponse) => void;
  onLocked: (period: string) => void;
}) {
  const [busy, setBusy] = useState<null | "month-end" | "lock">(null);
  const [error, setError] = useState<{ action: "month-end" | "lock"; error: unknown } | null>(null);
  const [confirm, setConfirm] = useState(false);
  const label = periodLabel(period);
  const result = monthEnd && monthEnd.rollforward?.period === period ? monthEnd : null;

  const runMonthEnd = async () => {
    setBusy("month-end");
    setError(null);
    try {
      const res = await api.monthEnd(period);
      onMonthEnd(res);
      await invalidateAfterWrite();
      toast(`${label} month-end drafted`, { description: `${eur(liabilityChange(res), { signed: true })} change in estimate (IAS 8.36), pending approval.` });
    } catch (e) {
      setError({ action: "month-end", error: e });
    } finally {
      setBusy(null);
    }
  };

  const lock = async () => {
    setBusy("lock");
    setError(null);
    try {
      await api.lockPeriod(period);
      onLocked(period);
      setConfirm(false);
      await invalidateAfterWrite();
      toast(`${label} locked`, { description: "Never written again. Later corrections go to the open period." });
    } catch (e) {
      setConfirm(false);
      setError({ action: "lock", error: e });
    } finally {
      setBusy(null);
    }
  };

  return (
    <section aria-labelledby="close-rail" className="flex flex-col rounded-xl bg-card shadow-[0_0_0_1px_var(--color-cloud-200),0_1px_2px_rgba(13,21,36,0.04)]">
      <div className="px-5 pt-4">
        <div className="flex items-center justify-between gap-3">
          <MicroLabel>Close · {label}</MicroLabel>
          {locked ? (
            <StatusChip tone="slate" dot={false}>
              <Lock className="size-3" aria-hidden="true" /> locked
            </StatusChip>
          ) : (
            <StatusChip tone="outline" dot={false}>
              open
            </StatusChip>
          )}
        </div>
        <h2 id="close-rail" className="mt-1.5 text-[15.5px] font-semibold text-navy-900">
          Month-end and lock
        </h2>
      </div>

      {/* Three blocks: stacked beside the rollforward on wide screens, side by side under it otherwise. */}
      <div className="mt-3 grid grid-cols-[minmax(0,1fr)] pb-4 md:grid-cols-3 min-[87.5rem]:grid-cols-[minmax(0,1fr)]">
        {/* month-end */}
        <div className="px-5">
          <AnimatePresence mode="wait" initial={false}>
            {result ? (
              <MonthEndResult key="result" res={result} />
            ) : (
              <motion.p key="what" initial={{ opacity: 0 }} animate={{ opacity: 1 }} exit={{ opacity: 0 }} className="text-[13px] leading-relaxed text-slate-500">
                Re-estimates every cohort on its claim curve and drafts the change in estimate for approval: prospective, per IAS 8.36.
              </motion.p>
            )}
          </AnimatePresence>
          {canAct && !locked ? (
            <Button
              variant={result ? "outline" : "default"}
              onClick={() => void runMonthEnd()}
              disabled={busy !== null}
              className={cn("mt-3 h-9 w-full rounded-lg text-[13.5px]", result ? "" : "bg-navy-900 font-semibold text-cloud-50 hover:bg-navy-800")}
              data-testid="month-end"
            >
              {busy === "month-end" ? "Running month-end…" : result ? `Run ${label} month-end again` : `Run ${label} month-end`}
            </Button>
          ) : null}
          {error?.action === "month-end" ? <Denied error={error.error} className="mt-2.5" /> : null}
        </div>

        {/* lock */}
        <div className={BLOCK}>
          {locked ? (
            <p className="text-[13px] leading-relaxed text-slate-500">
              <span className="font-medium text-navy-900">{label} is locked.</span> Nothing is written to it again; anything found later is corrected in the open period.
            </p>
          ) : (
            <>
              <p className="text-[13px] leading-relaxed text-slate-500">Lock {label} once it ties. Locked periods are never written; anything found later is corrected in the open period.</p>
              {canAct ? (
                <Button variant="outline" onClick={() => setConfirm(true)} disabled={busy !== null} className="mt-3 h-9 w-full rounded-lg text-[13.5px]" data-testid="lock-period">
                  <Lock className="size-3.5" aria-hidden="true" />
                  Lock {label}
                </Button>
              ) : null}
            </>
          )}
          {error?.action === "lock" ? <Denied error={error.error} className="mt-2.5" /> : null}
          {!canAct ? <p className="mt-3 text-[12.5px] text-slate-400">The Controller runs month-end and locks periods.</p> : null}
        </div>

        {!locked ? (
          <div className={BLOCK}>
            <ReadyToLock monthEnd={!!result} pendingDrafts={pendingDrafts} tiesToGl={tiesToGl} />
          </div>
        ) : null}
      </div>

      <Dialog open={confirm} onOpenChange={(o) => busy === null && setConfirm(o)}>
        <DialogContent className="sm:max-w-[420px]">
          <DialogHeader>
            <DialogTitle className="text-[16px] font-semibold text-navy-900">Lock {label}?</DialogTitle>
            <DialogDescription className="text-[13.5px] leading-relaxed text-slate-500">
              Nothing is written to a locked period again. A later claim or ruling becomes a change in estimate (IAS 8.36) in the open period; evidence that was available and missed becomes a prior-period error, corrected in current period (immaterial).
            </DialogDescription>
            {pendingDrafts > 0 ? (
              <p className="rounded-lg bg-cloud-50 px-3 py-2 text-[13px] leading-snug text-navy-900 shadow-[inset_0_0_0_1px_var(--color-cloud-200)]">
                {count(pendingDrafts)} {pendingDrafts === 1 ? "entry is" : "entries are"} still drafted, pending approval in {label}.
              </p>
            ) : null}
          </DialogHeader>
          <DialogFooter>
            <Button variant="outline" onClick={() => setConfirm(false)} disabled={busy !== null}>
              Cancel
            </Button>
            <Button onClick={() => void lock()} disabled={busy !== null} className="bg-navy-900 text-cloud-50 hover:bg-navy-800" data-testid="lock-confirm">
              {busy === "lock" ? "Locking…" : `Lock ${label}`}
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </section>
  );
}

/** Before you lock: what the record says about this period, item by item. Green only for the GL tie and the invariants. */
function ReadyToLock({ monthEnd, pendingDrafts, tiesToGl }: { monthEnd: boolean; pendingDrafts: number; tiesToGl: boolean | null }) {
  const inv = useInvariants();
  const failing = inv.data ? inv.data.filter((i) => !i.ok).length : null;
  const items: { ok: boolean | null; text: string; green?: boolean }[] = [
    { ok: monthEnd, text: monthEnd ? "Month-end drafted" : "Month-end not run yet" },
    { ok: pendingDrafts === 0, text: pendingDrafts ? `${count(pendingDrafts)} ${pendingDrafts === 1 ? "entry" : "entries"} pending approval` : "No entries pending approval" },
    { ok: tiesToGl, text: tiesToGl === false ? "2140 doesn't tie to the GL" : "2140 ties to GL 2140", green: true },
    { ok: failing === null ? null : failing === 0, text: failing ? `${count(failing)} invariant${failing === 1 ? "" : "s"} failing` : "Every invariant holds", green: true },
  ];
  return (
    <div>
      <h3 className="text-[13px] font-semibold text-navy-900">Before you lock</h3>
      <ul className="mt-2 flex flex-col gap-1.5" data-testid="ready-to-lock">
        {items.map((it) => (
          <li key={it.text} className="flex items-center gap-2 text-[12.5px]">
            {it.ok === null ? (
              <span className="size-4 shrink-0 animate-pulse rounded-full bg-cloud-100" aria-hidden="true" />
            ) : it.ok ? (
              <span className={cn("inline-flex size-4 shrink-0 items-center justify-center rounded-full", it.green ? "bg-tie-wash" : "bg-cloud-100")} aria-label="done">
                <Check className={cn("size-2.5", it.green ? "text-tie-ink" : "text-navy-900")} strokeWidth={3} />
              </span>
            ) : (
              <span className="inline-flex size-4 shrink-0 rounded-full shadow-[inset_0_0_0_1.5px_var(--color-slate-400)]" aria-label="open" />
            )}
            <span className={it.ok === false ? "text-navy-900" : "text-slate-600"}>{it.text}</span>
          </li>
        ))}
      </ul>
    </div>
  );
}

/** "+€3,990 change in estimate", read off what the month-end returned. */
function MonthEndResult({ res }: { res: MonthEndResponse }) {
  const change = liabilityChange(res);
  const est = res.estimate;
  const cohortRow = est ? res.rollforward?.rows.find((r) => r.cohort === est.cohort) : undefined;
  const drafted = res.entries?.filter((e) => e.status === "draft").length ?? 0;
  return (
    <motion.div key="result" initial={{ opacity: 0, y: 6 }} animate={{ opacity: 1, y: 0 }} exit={{ opacity: 0 }} transition={{ duration: 0.35, ease: [0.16, 1, 0.3, 1] }} data-testid="month-end-result">
      <p className="micro text-slate-500">{periodLabel(res.rollforward?.period ?? "")} month-end</p>
      <p className="mt-1.5 flex flex-wrap items-baseline gap-x-2">
        <span className="display-tight text-[30px] leading-none text-navy-900">{eur(change, { signed: true })}</span>
        <span className="text-[13.5px] text-navy-900">change in estimate (IAS 8.36)</span>
      </p>
      <p className="mt-1 text-[12.5px] text-slate-500">Drafted, pending approval.</p>
      <ul className="mt-2.5 flex flex-col gap-1 text-[13px] leading-snug text-slate-600">
        {est ? (
          <li>
            {METHOD[est.selected] ?? est.selected} selected
            {est.actual_vs_expected !== null ? <> · A/E {est.actual_vs_expected.toFixed(2)}</> : null}
          </li>
        ) : null}
        {cohortRow ? (
          <li>
            {cohortName(cohortRow.cohort, est?.cohort === cohortRow.cohort ? est.segment : null, stormName)} closes at {eur(cohortRow.closing_cents)}
          </li>
        ) : null}
        {res.rollforward ? (
          <li className="flex flex-wrap items-center gap-2">
            2140 closes at {eur(res.rollforward.closing_total_cents)} <TiesChip ok={res.rollforward.ties_to_gl} />
          </li>
        ) : null}
      </ul>
      {drafted ? (
        <a href="#journal" className="mt-2.5 inline-flex items-center gap-1 text-[12.5px] font-medium text-metar-ink hover:underline">
          {drafted === 1 ? "See the drafted entry" : `See the ${count(drafted)} drafted entries`} <ArrowDown className="size-3.5" aria-hidden="true" />
        </a>
      ) : null}
    </motion.div>
  );
}

/** The close checklist, checked on every read. ok uses the one green; a failure is said plainly, with its detail, in ink. */
export function InvariantsPanel() {
  const q = useInvariants();
  const items = q.data ?? [];
  const failing = items.filter((i) => !i.ok).length;
  return (
    <section aria-labelledby="invariants-title" className="rounded-xl bg-card px-5 pb-3 pt-4 shadow-[0_0_0_1px_var(--color-cloud-200),0_1px_2px_rgba(13,21,36,0.04)]">
      <div className="flex flex-wrap items-baseline justify-between gap-x-4 gap-y-1">
        <div>
          <MicroLabel>Invariants · checked on every read</MicroLabel>
          <h2 id="invariants-title" className="mt-1 text-[15.5px] font-semibold text-navy-900">
            {q.data && items.length ? (failing ? `${count(failing)} of ${count(items.length)} failing` : `All ${count(items.length)} hold`) : "Invariants"}
          </h2>
        </div>
        <p className="text-[12.5px] text-slate-500">The books are re-checked from the journal each time this page reads them.</p>
      </div>
      {q.isError ? (
        <ErrorNote error={q.error} onRetry={() => void q.refetch()} className="mt-3 mb-1" />
      ) : !q.data ? (
        <div className="mt-3 grid gap-2 pb-2 sm:grid-cols-2 xl:grid-cols-3">
          {Array.from({ length: 6 }, (_, i) => (
            <Shimmer key={i} className="h-9" />
          ))}
        </div>
      ) : !items.length ? (
        <Empty title="No checks reported" className="mt-3 mb-1 py-6" />
      ) : (
        <ul className="mt-2 grid grid-cols-[minmax(0,1fr)] gap-x-8 sm:grid-cols-2 xl:grid-cols-3" data-testid="invariants">
          {[...items].sort((a, b) => Number(a.ok) - Number(b.ok)).map((inv) => (
            <InvariantRow key={inv.id} inv={inv} />
          ))}
        </ul>
      )}
    </section>
  );
}

function InvariantRow({ inv }: { inv: InvariantResult }) {
  return (
    <li className="grid grid-cols-[18px_minmax(0,1fr)] gap-2 border-t border-cloud-100 py-2.5" title={inv.id}>
      {inv.ok ? (
        <span className="mt-0.5 inline-flex size-4 items-center justify-center rounded-full bg-tie-wash" aria-label="holds">
          <Check className="size-2.5 text-tie-ink" strokeWidth={3} />
        </span>
      ) : (
        <span className="mt-0.5 inline-flex size-4 items-center justify-center rounded-full bg-navy-900" aria-label="fails">
          <Minus className="size-2.5 text-cloud-50" strokeWidth={3} />
        </span>
      )}
      <span className="min-w-0">
        <span className={cn("block text-[13px] leading-snug", inv.ok ? "text-slate-600" : "font-medium text-navy-900")}>{inv.description}</span>
        {inv.detail ? <span className={cn("mt-0.5 block text-[12px] leading-snug", inv.ok ? "text-slate-400" : "text-slate-600")}>{inv.detail}</span> : null}
      </span>
    </li>
  );
}
