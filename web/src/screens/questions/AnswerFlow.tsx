import { useId, useState, type FormEvent } from "react";
import { Link } from "react-router";
import { AnimatePresence, motion } from "motion/react";
import { ArrowUpRight, Check, Loader2 } from "lucide-react";
import { api } from "@/api/client";
import { invalidateAfterWrite, useQuestions, useRules } from "@/api/queries";
import type { AnswerResponse, ConfirmResponse, Question } from "@/api/types";
import { MicroLabel, StatusChip } from "@/components/chips";
import { ReplaySummary } from "@/components/journal";
import { ErrorNote, LoopFooter } from "@/components/kit";
import { RadioGroup, RadioGroupItem } from "@/components/ui/radio-group";
import { ruleRef, TIER_LABEL } from "@/components/rule-sentence";
import { ROLE_LABEL } from "@/lib/format";
import { cn } from "@/lib/utils";
import { findProposalRule, isReleaseProposal, nextStormLine, REJECT_RE, seatPhrase, settledHereLine } from "./lib";
import { RulePreview } from "./RulePreview";
import { useViewAs } from "./viewAs";

export type Flow =
  | { step: "answer" }
  | { step: "preview"; answer: AnswerResponse }
  | { step: "saved"; answer: AnswerResponse; confirmed: ConfirmResponse }
  | { step: "recorded"; answer: AnswerResponse };

const REJECT_OPTION = "Reject the proposal";

const EASE = [0.16, 1, 0.3, 1] as const;

/** One card's ruling: answer → rule preview → confirm → saved. Held by the screen so a refetch can't drop it. */
export function AnswerFlow({ question, flow, onFlow, canAnswer }: { question: Question; flow: Flow; onFlow: (f: Flow) => void; canAnswer: boolean }) {
  return (
    <AnimatePresence mode="wait" initial={false}>
      <motion.div key={flow.step} initial={{ opacity: 0, y: 10 }} animate={{ opacity: 1, y: 0 }} exit={{ opacity: 0, y: -6 }} transition={{ duration: 0.28, ease: EASE }}>
        {flow.step === "answer" ? (
          canAnswer ? (
            <AnswerForm question={question} onFlow={onFlow} />
          ) : (
            <ReadOnly question={question} />
          )
        ) : flow.step === "preview" ? (
          <Preview question={question} flow={flow} onFlow={onFlow} />
        ) : flow.step === "saved" ? (
          <Saved question={question} flow={flow} />
        ) : (
          <Recorded answer={flow.answer} />
        )}
      </motion.div>
    </AnimatePresence>
  );
}

function AnswerForm({ question, onFlow }: { question: Question; onFlow: (f: Flow) => void }) {
  const id = useId();
  const rules = useRules();
  const release = isReleaseProposal(question);
  // When the server already offers a rejection among the options, answering with it is the rejection.
  // Otherwise the UI adds one, sent to POST /rules/{id}/reject when the proposal is a rule.
  const serverReject = question.options.some((o) => REJECT_RE.test(o));
  const options = release && !serverReject ? [...question.options, REJECT_OPTION] : question.options;
  const recommended = options.includes(question.recommended_option) ? question.recommended_option : options[0];
  const [choice, setChoice] = useState(recommended);
  const [explanation, setExplanation] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<unknown>(null);
  const rejecting = release && (choice === REJECT_OPTION || REJECT_RE.test(choice));
  const proposalRule = release && !serverReject ? findProposalRule(rules.data, question) : null;

  const submit = async (e: FormEvent) => {
    e.preventDefault();
    const text = explanation.trim();
    if (!text || busy) return;
    setBusy(true);
    setError(null);
    try {
      const answer = choice === REJECT_OPTION && proposalRule ? await api.reject(proposalRule.id, text) : await api.answer(question.id, { decision: choice, explanation: text });
      void invalidateAfterWrite();
      onFlow(answer.proposal ? { step: "preview", answer } : { step: "recorded", answer });
    } catch (err) {
      setError(err);
    } finally {
      setBusy(false);
    }
  };

  return (
    <form onSubmit={submit} className="flex flex-col gap-5" aria-label={`Rule on: ${question.title}`}>
      <fieldset className="min-w-0">
        <legend className="micro mb-2.5 text-slate-500">{release ? "Your decision" : "Your ruling"}</legend>
        <RadioGroup value={choice} onValueChange={setChoice} className="gap-2" aria-label={release ? "Your decision" : "Your ruling"}>
          {options.map((opt, i) => {
            const itemId = `${id}-opt-${i}`;
            const isRec = opt === question.recommended_option;
            return (
              <label
                key={opt}
                htmlFor={itemId}
                className={cn(
                  "flex cursor-pointer items-start gap-3 rounded-lg bg-card px-3.5 py-3 shadow-[inset_0_0_0_1px_var(--color-cloud-200)] transition-shadow hover:shadow-[inset_0_0_0_1px_var(--color-cloud-400)]",
                  choice === opt && "shadow-[inset_0_0_0_1.5px_var(--color-navy-900)] hover:shadow-[inset_0_0_0_1.5px_var(--color-navy-900)]",
                )}
              >
                <RadioGroupItem id={itemId} value={opt} className="mt-0.5 border-cloud-400 bg-white data-[state=checked]:border-navy-900 data-[state=checked]:bg-navy-900" />
                <span className="min-w-0 flex-1 text-[14px] leading-snug text-navy-900">
                  {opt}
                  {isRec ? (
                    <span className="mt-1 block">
                      <StatusChip tone="outline" dot={false} className="h-5 text-[10.5px]">
                        {release ? "proposed by the engine" : "recommended"}
                      </StatusChip>
                    </span>
                  ) : null}
                </span>
              </label>
            );
          })}
        </RadioGroup>
      </fieldset>

      <div>
        <label htmlFor={`${id}-why`} className="flex flex-wrap items-baseline justify-between gap-x-3 gap-y-0.5">
          <span className="micro text-slate-500">In your words</span>
          <span className="text-[12px] text-slate-400">the rule is built from what you write</span>
        </label>
        <textarea
          id={`${id}-why`}
          value={explanation}
          onChange={(e) => setExplanation(e.target.value)}
          onKeyDown={(e) => {
            if (e.key === "Enter" && (e.metaKey || e.ctrlKey)) void submit(e);
          }}
          required
          rows={4}
          maxLength={2000}
          placeholder={rejecting ? "Why it shouldn't happen, and what to do instead" : "Your ruling and the reason for it"}
          className="mt-2 block w-full resize-y rounded-lg bg-card px-3.5 py-3 text-[14.5px] leading-relaxed text-navy-900 shadow-[inset_0_0_0_1px_var(--color-cloud-300)] outline-none transition-shadow placeholder:text-slate-400 focus:shadow-[inset_0_0_0_1px_var(--color-metar-ink),0_0_0_3px_color-mix(in_srgb,var(--color-metar)_22%,transparent)]"
        />
      </div>

      {error ? <ErrorNote error={error} /> : null}

      <button
        type="submit"
        disabled={busy || !explanation.trim()}
        className="inline-flex h-10 items-center justify-center gap-2 rounded-lg bg-navy-900 px-4 text-[14px] font-semibold text-cloud-50 transition-colors hover:bg-navy-800 disabled:cursor-not-allowed disabled:opacity-45"
      >
        {busy ? <Loader2 className="size-4 animate-spin" aria-hidden="true" /> : null}
        {busy ? "Drafting the rule" : rejecting ? "Reject and preview the rule" : "Submit ruling"}
      </button>
      <p className="-mt-3 text-center text-[12px] text-slate-500">You&rsquo;ll see the rule and what it changes before anything is saved.</p>
    </form>
  );
}

function ReadOnly({ question }: { question: Question }) {
  const { viewAs, busy } = useViewAs();
  const who = ROLE_LABEL[question.routed_to];
  return (
    <div className="flex flex-col gap-4">
      <div>
        <MicroLabel>Options</MicroLabel>
        <ul className="mt-2 flex flex-col gap-1.5">
          {question.options.map((opt) => (
            <li key={opt} className="flex items-start gap-2.5 rounded-lg bg-card px-3.5 py-2.5 text-[13.5px] leading-snug text-slate-600 shadow-[inset_0_0_0_1px_var(--color-cloud-200)]">
              <span className={cn("mt-1 size-2 shrink-0 rounded-full", opt === question.recommended_option ? "bg-navy-900" : "bg-cloud-300")} aria-hidden="true" />
              <span className="min-w-0 flex-1">
                {opt}
                {opt === question.recommended_option ? <span className="ml-2 font-mono text-[10.5px] uppercase tracking-[0.06em] text-slate-400">recommended</span> : null}
              </span>
            </li>
          ))}
        </ul>
      </div>
      <p className="text-[13px] leading-relaxed text-slate-500">Only {seatPhrase(question.routed_to)} can rule on this. Every other seat sees it read-only.</p>
      <button
        type="button"
        disabled={!!busy}
        onClick={() => void viewAs(question.routed_to)}
        className="inline-flex h-10 items-center justify-center gap-2 rounded-lg px-4 text-[14px] font-semibold text-navy-900 shadow-[inset_0_0_0_1px_var(--color-cloud-300)] transition-colors hover:bg-white disabled:opacity-50"
      >
        {busy ? <Loader2 className="size-4 animate-spin" aria-hidden="true" /> : null}
        View as {who} to answer
      </button>
    </div>
  );
}

function Preview({ question, flow, onFlow }: { question: Question; flow: Extract<Flow, { step: "preview" }>; onFlow: (f: Flow) => void }) {
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<unknown>(null);
  const confirm = async () => {
    const rule = flow.answer.proposal?.rule;
    if (!rule || busy) return;
    setBusy(true);
    setError(null);
    try {
      const confirmed = await api.confirm(rule.id);
      void invalidateAfterWrite();
      onFlow({ step: "saved", answer: flow.answer, confirmed });
    } catch (err) {
      setError(err);
    } finally {
      setBusy(false);
    }
  };
  return <RulePreview answer={flow.answer} question={question} onConfirm={() => void confirm()} confirming={busy} error={error} />;
}

/** widen_next is loosely typed: prefer a question the server wrote, else name the scope it would drop. */
function widenQuestion(next: Record<string, unknown>): string {
  for (const k of ["question", "label", "text", "prompt"]) if (typeof next[k] === "string") return next[k] as string;
  const entries = Object.entries(next).filter(([, v]) => v !== null && typeof v !== "object");
  if (!entries.length) return "Apply it more widely?";
  return `Apply it beyond ${entries.map(([k, v]) => `${k.replace(/[._]/g, " ")} ${String(v).replace(/^case:/, "")}`).join(", ")}?`;
}

function Saved({ question, flow }: { question: Question; flow: Extract<Flow, { step: "saved" }> }) {
  const rule = flow.confirmed.rule;
  const here = settledHereLine(flow.confirmed.replay, question.case_refs);
  const next = nextStormLine(flow.confirmed.replay, question.case_refs);
  const widenNext = flow.answer.proposal?.widen_next ?? null;
  // Asks come from the server as questions; if it raised the widening as one, point at that card.
  const open = useQuestions("open");
  const followUp = widenNext ? (open.data ?? []).find((q) => q.id !== question.id && (/widen/.test(q.pattern) || q.title === widenQuestion(widenNext))) : undefined;

  return (
    <div className="flex flex-col gap-5" data-testid="saved">
      <div className="flex items-start gap-3.5">
        <motion.span
          initial={{ scale: 0.6, opacity: 0 }}
          animate={{ scale: 1, opacity: 1 }}
          transition={{ type: "spring", stiffness: 420, damping: 22, delay: 0.05 }}
          className="mt-0.5 inline-flex size-9 shrink-0 items-center justify-center rounded-full bg-navy-900 text-cloud-50"
          aria-hidden="true"
        >
          <Check className="size-4.5" strokeWidth={2.6} />
        </motion.span>
        <div className="min-w-0">
          <p className="display-tight text-balance text-[21px] leading-tight text-navy-900">Saved as policy · Never asked again</p>
          <p className="mt-1.5 flex flex-wrap items-center gap-x-2 gap-y-1 text-[13px] text-slate-500">
            <span className="font-mono text-[12.5px] font-bold text-navy-900">{ruleRef(rule)}</span>
            <span>{TIER_LABEL[rule.tier]}</span>
            <StatusChip tone="outline" dot={false} className="h-5 text-[10.5px]">
              {rule.status}
            </StatusChip>
          </p>
        </div>
      </div>

      <div className="flex flex-col gap-2 rounded-lg bg-card px-4 py-3 shadow-[0_0_0_1px_var(--color-cloud-200)]">
        {here ? <LoopFooter className="text-navy-900">{here}</LoopFooter> : null}
        {next ? <LoopFooter className="text-navy-900">{next.settled}</LoopFooter> : null}
        {next?.asks ? <p className="pl-6 text-[13px] text-slate-500">{next.asks}</p> : null}
        {!here && !next ? <LoopFooter className="text-navy-900">The next matching case settles without asking, with this ruling cited.</LoopFooter> : null}
        <ReplaySummary diff={flow.confirmed.replay} className="pl-6 text-[11.5px] text-slate-500" />
      </div>

      {followUp ? (
        <p className="rounded-lg bg-held-wash/60 px-3.5 py-2.5 text-[13px] leading-snug text-held-ink">
          Asked once more, in its own card: <span className="font-semibold">{followUp.title}</span>
        </p>
      ) : widenNext ? (
        <p className="text-[12.5px] leading-snug text-slate-500">One rung wider is possible in Policies: {widenQuestion(widenNext)}</p>
      ) : null}

      <Link to={`/policies#${encodeURIComponent(rule.id)}`} className="inline-flex items-center gap-1 self-start text-[13px] font-medium text-metar-ink hover:underline">
        See it in Policies
        <ArrowUpRight className="size-3.5" aria-hidden="true" />
      </Link>
    </div>
  );
}

function Recorded({ answer }: { answer: AnswerResponse }) {
  return (
    <div className="flex flex-col gap-2" data-testid="recorded">
      <MicroLabel>Ruling recorded</MicroLabel>
      <p className="text-[15px] font-semibold text-navy-900">&ldquo;{answer.ruling.decision}&rdquo;</p>
      <p className="text-[13px] leading-relaxed text-slate-500">Recorded as your ruling on this case. No rule was proposed from it, so a case like it will be asked again.</p>
    </div>
  );
}
