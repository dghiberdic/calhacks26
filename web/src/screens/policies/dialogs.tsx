import { useState, type ReactNode } from "react";
import { Link } from "react-router";
import { useMutation } from "@tanstack/react-query";
import { Check, Loader2, RotateCcw, Waypoints, X } from "lucide-react";
import { toast } from "sonner";
import { ApiError, api } from "@/api/client";
import { invalidateAfterWrite } from "@/api/queries";
import type { ReplayDiff, Role, Rule, RuleProposal } from "@/api/types";
import { useSession } from "@/app/session";
import { MicroLabel } from "@/components/chips";
import { ErrorNote } from "@/components/kit";
import { ReplayFlips, ReplaySummary } from "@/components/journal";
import { RuleSentence, ruleRef } from "@/components/rule-sentence";
import { Dialog, DialogContent, DialogDescription, DialogTitle } from "@/components/ui/dialog";
import { ROLE_LABEL } from "@/lib/format";
import { cn } from "@/lib/utils";
import { caseClause, caseKeys, droppedCaseKeys, stamp, withoutCaseScope } from "./model";

const CHECK_LABEL: Record<string, string> = {
  compiles: "compiles",
  reproduces_case: "reproduces the case",
  no_hard_control: "touches no hard control",
  grounded: "grounded in the ruling",
  author_has_authority: "author holds the authority",
  no_conflict: "no conflict",
};

// ---------- shell ----------
function Shell({ open, onClose, children, label }: { open: boolean; onClose: () => void; children: ReactNode; label: string }) {
  return (
    <Dialog open={open} onOpenChange={(o) => (o ? null : onClose())}>
      <DialogContent aria-label={label} className="max-h-[calc(100svh-2rem)] gap-0 overflow-y-auto rounded-2xl p-0 sm:max-w-[600px]">
        {children}
      </DialogContent>
    </Dialog>
  );
}

function Head({ eyebrow, title, children }: { eyebrow: ReactNode; title: ReactNode; children?: ReactNode }) {
  return (
    <div className="px-6 pb-4 pt-6">
      <MicroLabel>{eyebrow}</MicroLabel>
      <DialogTitle className="display-tight mt-1.5 text-[22px] font-[620] leading-tight text-navy-900">{title}</DialogTitle>
      {children ? <DialogDescription className="mt-2 text-[13.5px] leading-relaxed text-slate-500">{children}</DialogDescription> : null}
    </div>
  );
}

function Foot({ children }: { children: ReactNode }) {
  return <div className="sticky bottom-0 flex flex-wrap items-center justify-end gap-2 border-t border-cloud-100 bg-card px-6 py-4">{children}</div>;
}

const PRIMARY = "inline-flex h-9 items-center gap-2 rounded-lg bg-navy-900 px-4 text-[13.5px] font-semibold text-cloud-50 transition-colors hover:bg-navy-800 disabled:opacity-50";
const SECONDARY = "inline-flex h-9 items-center rounded-lg px-3.5 text-[13.5px] text-slate-600 transition-colors hover:bg-cloud-50";

/** A 403 says whose authority the action needs; offer that seat in one click. */
function Denied({ error, role, onSwitched }: { error: unknown; role: Role; onSwitched: () => void }) {
  const signIn = useSession((s) => s.signIn);
  const current = useSession((s) => s.role);
  const [busy, setBusy] = useState(false);
  const forbidden = error instanceof ApiError && error.status === 403;
  return (
    <div className="px-6 pb-5">
      <ErrorNote error={error} />
      {forbidden && current !== role ? (
        <button
          type="button"
          disabled={busy}
          className="mt-3 text-[13px] font-medium text-metar-ink hover:underline disabled:opacity-50"
          onClick={async () => {
            setBusy(true);
            try {
              await signIn(role);
              await invalidateAfterWrite();
              toast(`Viewing as ${ROLE_LABEL[role]}`);
              onSwitched();
            } catch {
              toast.error("Couldn't switch role.");
            } finally {
              setBusy(false);
            }
          }}
        >
          View as {ROLE_LABEL[role]} and try again
        </button>
      ) : null}
    </div>
  );
}

function Working({ label }: { label: string }) {
  return (
    <div role="status" className="flex items-center gap-2 px-6 pb-8 pt-2 text-[13.5px] text-slate-500">
      <Loader2 className="size-4 animate-spin" aria-hidden="true" />
      {label}
    </div>
  );
}

/** "flips N · Δ€ · Jan locked, untouched", the flips, and the adjustments drafted. */
function Diff({ diff, empty }: { diff: ReplayDiff; empty: string }) {
  return (
    <div className="px-6 pb-5">
      <div className="rounded-xl bg-cloud-50 px-4 py-3.5">
        <div className="flex flex-wrap items-baseline justify-between gap-x-4 gap-y-1">
          <ReplaySummary diff={diff} className="figure font-sans text-[15px] font-medium text-navy-900" />
          <span className="figure text-[12px] text-slate-400">known at {stamp(diff.known_at)}</span>
        </div>
        {diff.flips.length ? <ReplayFlips diff={diff} limit={8} className="mt-2.5" /> : <p className="mt-2 text-[13px] text-slate-500">{empty}</p>}
      </div>
      {diff.adjustment_je_ids?.length ? (
        <p className="mt-3 text-[13px] text-slate-500">
          Adjustments drafted, pending approval:{" "}
          {diff.adjustment_je_ids.map((id, i) => (
            <span key={id}>
              {i > 0 ? ", " : null}
              <Link to="/close" className="font-mono text-[12px] text-navy-900 hover:underline">
                {id}
              </Link>
            </span>
          ))}
        </p>
      ) : null}
    </div>
  );
}

// ---------- widen ----------
export function WidenDialog({ rule, proposal, pending, error, onRetry, onClose }: { rule: Rule | null; proposal: RuleProposal | null; pending: boolean; error: unknown; onRetry: () => void; onClose: () => void }) {
  const confirm = useMutation({ mutationFn: (id: string) => api.confirm(id) });
  const close = () => {
    confirm.reset();
    onClose();
  };
  const dropped = rule && proposal ? droppedCaseKeys(rule, proposal.rule) : [];
  const failing = proposal ? Object.entries(proposal.checks).filter(([, ok]) => !ok) : [];

  return (
    <Shell open={!!rule} onClose={close} label="Widen rule">
      {rule ? (
        <>
          <Head eyebrow="Widen · one rung" title={proposal ? `${ruleRef(rule)} → ${ruleRef(proposal.rule)}` : ruleRef(rule)}>
            Drops one condition that was copied from the case, then replays history before anything changes.
          </Head>
          {pending ? <Working label="Drafting the wider rule and replaying history…" /> : null}
          {error ? <Denied error={error} role={rule.authority_required} onSwitched={onRetry} /> : null}
          {proposal ? (
            <>
              <div className="px-6 pb-4">
                <div className="border-l-2 border-navy-900/80 pl-4">
                  <RuleSentence rule={withoutCaseScope(proposal.rule)} className="text-[15px]" />
                  <div className="mt-2.5 flex flex-wrap items-center gap-1.5">
                    {dropped.map((d) => (
                      <span key={d.key} title="Dropped: the wider rule no longer needs this" className="inline-flex h-6 items-center rounded-md bg-cloud-50 px-2 text-[12.5px] text-slate-400 line-through decoration-slate-400 shadow-[inset_0_0_0_1px_var(--color-cloud-200)]">
                        {caseClause(d.key, d.value)}
                      </span>
                    ))}
                    {caseKeys(proposal.rule).map((k) => (
                      <span key={k} className="inline-flex h-6 items-center rounded-md bg-cloud-100 px-2 text-[12.5px] text-slate-600">
                        {caseClause(k, proposal.rule.scope[k])}
                      </span>
                    ))}
                    {dropped.length ? <span className="text-[12px] text-slate-400">{caseKeys(proposal.rule).length ? "one case-only condition dropped" : "no case-only conditions left"}</span> : null}
                  </div>
                </div>
                <ul className="mt-4 grid grid-cols-1 gap-x-4 gap-y-1.5 sm:grid-cols-2" aria-label="Checks">
                  {Object.entries(proposal.checks).map(([key, ok]) => (
                    <li key={key} className={cn("flex items-center gap-2 text-[13px]", ok ? "text-slate-600" : "font-medium text-navy-900")}>
                      {ok ? <Check className="size-3.5 text-navy-800" aria-hidden="true" /> : <X className="size-3.5 text-navy-900" aria-hidden="true" />}
                      {CHECK_LABEL[key] ?? key.replace(/_/g, " ")}
                      <span className="sr-only">{ok ? "passes" : "fails"}</span>
                    </li>
                  ))}
                </ul>
              </div>
              <Diff diff={proposal.would_flip} empty="No past decision would change." />
              <NextRung proposal={proposal} />
              {confirm.error ? <Denied error={confirm.error} role={rule.authority_required} onSwitched={() => confirm.reset()} /> : null}
            </>
          ) : null}
          <Foot>
            <button type="button" className={SECONDARY} onClick={close}>
              {proposal ? "Not now" : "Close"}
            </button>
            {proposal ? (
              <button
                type="button"
                className={PRIMARY}
                disabled={confirm.isPending || failing.length > 0}
                onClick={() =>
                  confirm.mutate(proposal.rule.id, {
                    onSuccess: async (res) => {
                      await invalidateAfterWrite();
                      toast(`Saved as policy · ${ruleRef(res.rule)}`, { description: `${res.replay.flips.length} past decision${res.replay.flips.length === 1 ? "" : "s"} replayed` });
                      close();
                    },
                  })
                }
              >
                {confirm.isPending ? <Loader2 className="size-4 animate-spin" aria-hidden="true" /> : <Waypoints className="size-4" aria-hidden="true" />}
                Confirm wider rule
              </button>
            ) : error && !(error instanceof ApiError && error.status === 403) ? (
              <button type="button" className={PRIMARY} onClick={onRetry}>
                Try again
              </button>
            ) : null}
          </Foot>
        </>
      ) : null}
    </Shell>
  );
}

/** What a further widen would drop, when there is one: the question if the API words it, else the condition. */
function NextRung({ proposal }: { proposal: RuleProposal }) {
  const next = proposal.widen_next;
  if (!next) return null;
  const drop = typeof next.drop === "string" ? next.drop : null;
  const text = typeof next.question === "string" ? next.question : drop && proposal.rule.scope[drop] !== undefined ? `drop “${caseClause(drop, proposal.rule.scope[drop])}”` : null;
  if (!text) return null;
  return (
    <p className="-mt-2 px-6 pb-5 text-[13px] text-slate-500">
      <span className="micro mr-2 text-slate-400">next rung</span>
      {text}
    </p>
  );
}

// ---------- revert ----------
export function RevertDialog({ rule, onClose }: { rule: Rule | null; onClose: () => void }) {
  const revert = useMutation({
    mutationFn: (r: Rule) => api.revert(r.id),
    onSuccess: () => invalidateAfterWrite(),
  });
  const run = () => rule && revert.mutate(rule);
  return (
    <Shell open={!!rule} onClose={onClose} label="Revert rule">
      {rule ? (
        <>
          <Head eyebrow={revert.data ? "Replay diff" : "Revert"} title={revert.data ? `${ruleRef(rule)} reverted` : `Revert ${ruleRef(rule)}?`}>
            {revert.data
              ? "Every decision was replayed without this version. What flipped is drafted, pending approval."
              : "StormCheck replays every decision without this version. What flips is drafted as adjustments, pending approval. Locked periods are never rewritten."}
          </Head>
          {revert.isPending ? <Working label="Replaying every decision…" /> : null}
          {revert.error ? <Denied error={revert.error} role={rule.authority_required} onSwitched={run} /> : null}
          {revert.data ? <Diff diff={revert.data} empty="Nothing flipped: no decision depended on this version." /> : null}
          <Foot>
            {revert.data ? (
              <button type="button" className={PRIMARY} onClick={onClose}>
                Done
              </button>
            ) : (
              <>
                <button type="button" className={SECONDARY} onClick={onClose}>
                  Cancel
                </button>
                <button type="button" className={PRIMARY} disabled={revert.isPending} onClick={run}>
                  {revert.isPending ? <Loader2 className="size-4 animate-spin" aria-hidden="true" /> : <RotateCcw className="size-4" aria-hidden="true" />}
                  Revert and replay
                </button>
              </>
            )}
          </Foot>
        </>
      ) : null}
    </Shell>
  );
}
