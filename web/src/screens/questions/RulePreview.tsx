import { Check, Loader2, X } from "lucide-react";
import type { AnswerResponse, Question } from "@/api/types";
import { MicroLabel, StatusChip } from "@/components/chips";
import { ReplayFlips, ReplaySummary } from "@/components/journal";
import { ErrorNote } from "@/components/kit";
import { GroundedQuote, RuleSentence, ruleRef, TIER_LABEL } from "@/components/rule-sentence";
import { count, eur } from "@/lib/format";
import { cn } from "@/lib/utils";
import { CHECK_ORDER, checkLabel, readableRule } from "./lib";

/**
 * What a ruling would become before anyone commits to it: the rule as a sentence, the ruler's own
 * words with the phrases that ground each value, the six checks, and the replay over past decisions.
 */
export function RulePreview({
  answer,
  question,
  onConfirm,
  confirming,
  error,
}: {
  answer: AnswerResponse;
  question: Question;
  onConfirm: () => void;
  confirming: boolean;
  error: unknown;
}) {
  const proposal = answer.proposal!;
  const { rule, checks, would_flip: flip } = proposal;
  const keys = [...CHECK_ORDER.filter((k) => k in checks), ...Object.keys(checks).filter((k) => !CHECK_ORDER.includes(k))];
  const failing = keys.filter((k) => !checks[k]);
  const n = flip.flips.length;

  return (
    <div className="flex flex-col gap-5" data-testid="rule-preview">
      <div>
        <div className="flex flex-wrap items-center gap-2">
          <MicroLabel>Rule preview</MicroLabel>
          <span className="font-mono text-[12px] font-bold text-navy-900">{ruleRef(rule)}</span>
          <StatusChip tone="outline" dot={false} className="h-5 text-[10.5px]">
            {rule.status}
          </StatusChip>
        </div>
        <p className="mt-1 text-[12.5px] text-slate-500">
          {TIER_LABEL[rule.tier]}
          {rule.supersedes ? <> · supersedes <span className="font-mono text-[12px]">{rule.supersedes}</span></> : null} · you ruled <span className="text-navy-900">&ldquo;{answer.ruling.decision}&rdquo;</span>
        </p>
        <RuleSentence rule={readableRule(rule)} className="mt-3 text-[15.5px]" />
      </div>

      <div>
        <MicroLabel>In your words</MicroLabel>
        <div className="mt-1.5 rounded-lg bg-card px-4 py-3 shadow-[0_0_0_1px_var(--color-cloud-200)]">
          <GroundedQuote text={answer.ruling.explanation} grounding={rule.grounding} />
        </div>
        {Object.keys(rule.grounding ?? {}).length ? <p className="mt-1.5 text-[12px] text-slate-500">Highlighted words ground the rule&rsquo;s values. Nothing in it comes from anywhere else.</p> : null}
      </div>

      <div>
        <MicroLabel>Checks</MicroLabel>
        <ul className="mt-2 grid gap-x-6 gap-y-1.5 sm:grid-cols-2 lg:grid-cols-1">
          {keys.map((k) => {
            const ok = checks[k];
            return (
              <li key={k} className="flex items-start gap-2 text-[13px] leading-snug">
                <span className={cn("mt-px inline-flex size-4 shrink-0 items-center justify-center rounded-full", ok ? "bg-navy-900 text-cloud-50" : "bg-held-wash text-held-ink")} aria-hidden="true">
                  {ok ? <Check className="size-2.5" strokeWidth={3} /> : <X className="size-2.5" strokeWidth={3} />}
                </span>
                <span className={ok ? "text-slate-600" : "font-medium text-held-ink"}>
                  {checkLabel(k)}
                  <span className="sr-only">{ok ? ": passed" : ": failed"}</span>
                </span>
              </li>
            );
          })}
        </ul>
      </div>

      <div>
        <MicroLabel>Replay before you confirm</MicroLabel>
        <p className="mt-1.5 text-[14px] text-navy-900">
          {n ? (
            <>
              Would change <span className="figure font-semibold">{count(n)}</span> past decision{n === 1 ? "" : "s"} · Δ{" "}
              <span className="figure font-semibold">{eur(flip.total_delta_cents, { signed: true })}</span>
            </>
          ) : (
            "Changes no past decision. It applies from the next case on."
          )}
        </p>
        {n ? (
          <div className="mt-2 rounded-lg bg-card px-3.5 py-1 shadow-[0_0_0_1px_var(--color-cloud-200)]">
            <ReplayFlips diff={flip} limit={4} className="[&_li>span:first-child]:whitespace-normal" />
          </div>
        ) : null}
        <ReplaySummary diff={flip} className="mt-2 text-[11.5px] text-slate-500" />
      </div>

      {error ? <ErrorNote error={error} /> : null}

      <div className="flex flex-col gap-2">
        <button
          type="button"
          onClick={onConfirm}
          disabled={confirming || failing.length > 0}
          className="inline-flex h-10 items-center justify-center gap-2 rounded-lg bg-navy-900 px-4 text-[14px] font-semibold text-cloud-50 transition-colors hover:bg-navy-800 disabled:cursor-not-allowed disabled:opacity-45"
        >
          {confirming ? <Loader2 className="size-4 animate-spin" aria-hidden="true" /> : null}
          {confirming ? "Saving" : "Confirm as policy"}
        </button>
        <p className="text-center text-[12px] text-slate-500">
          {failing.length
            ? `It can't become a policy while ${failing.length === 1 ? "a check fails" : `${count(failing.length)} checks fail`}. Your ruling stands for this case only; the next case like it will be asked again.`
            : question.case_refs.length > 1
              ? `Settles all ${count(question.case_refs.length)} cases, then every match after them.`
              : "Nothing changes until you confirm."}
        </p>
      </div>
    </div>
  );
}
