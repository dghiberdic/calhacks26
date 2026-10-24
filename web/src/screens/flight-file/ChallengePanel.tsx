import { useId, useState, type FormEvent } from "react";
import { useNavigate } from "react-router";
import { useMutation } from "@tanstack/react-query";
import { AnimatePresence, motion } from "motion/react";
import { Loader2 } from "lucide-react";
import { api } from "@/api/client";
import { invalidateAfterWrite } from "@/api/queries";
import type { ChallengeResponse, Question } from "@/api/types";
import { useSession } from "@/app/session";
import { MicroLabel, StatusChip, type Tone } from "@/components/chips";
import { EvidenceList } from "@/components/evidence";
import { ConfidenceLine, ErrorNote, RoutedTo } from "@/components/kit";
import type { VerdictKind } from "@/components/verdict";
import { ROLE_LABEL } from "@/lib/format";
import { cn } from "@/lib/utils";
import { useViewAs } from "../questions/viewAs";

/** Worded like the challenges people actually send; static copy that only fills the box. */
const EXAMPLES: Partial<Record<VerdictKind, string[]>> = {
  notweather: ["The storm would have grounded it anyway", "Airbus operator notice: hidden defect in this EDP batch"],
  weather: ["The aircraft had a fault logged before the storm"],
  held: ["Passengers weren't offered the earliest reroute"],
};

const CLASS_TONE: Record<ChallengeResponse["classification"], Tone> = {
  assertion: "slate",
  new_fact: "outline",
  new_legal_pattern: "held",
};

export function ChallengePanel({ flightId, kind }: { flightId: string; kind: VerdictKind }) {
  const [text, setText] = useState("");
  const id = useId();
  const challenge = useMutation({
    mutationFn: (body: string) => api.challenge(flightId, body),
    onSuccess: () => void invalidateAfterWrite(),
  });
  const examples = EXAMPLES[kind] ?? [];
  const submit = (e: FormEvent) => {
    e.preventDefault();
    const body = text.trim();
    if (!body || challenge.isPending) return;
    challenge.mutate(body);
  };

  return (
    <section aria-labelledby={`${id}-title`} className="rounded-xl bg-card shadow-[0_0_0_1px_var(--color-cloud-200),0_1px_2px_rgba(13,21,36,0.04)]" data-testid="challenge">
      <header className="px-5 pt-4">
        <h2 id={`${id}-title`} className="text-[14.5px] font-semibold text-navy-900">
          Challenge this decision
        </h2>
        <p className="mt-1 max-w-[64ch] text-[13px] leading-relaxed text-slate-500">
          A challenge is evidence at trust tier 4. It can route a question to the right person; it never flips a decision on its own.
        </p>
      </header>
      <form onSubmit={submit} className="px-5 pb-5 pt-3">
        <label htmlFor={`${id}-text`} className="sr-only">
          Your challenge
        </label>
        <textarea
          id={`${id}-text`}
          value={text}
          onChange={(e) => setText(e.target.value)}
          onKeyDown={(e) => {
            if (e.key === "Enter" && (e.metaKey || e.ctrlKey)) submit(e);
          }}
          rows={3}
          maxLength={2000}
          placeholder="What does the evidence get wrong?"
          className="block w-full resize-y rounded-lg bg-cloud-25 px-3.5 py-3 text-[14.5px] leading-relaxed text-navy-900 shadow-[inset_0_0_0_1px_var(--color-cloud-300)] outline-none transition-shadow placeholder:text-slate-400 focus:bg-white focus:shadow-[inset_0_0_0_1px_var(--color-metar-ink),0_0_0_3px_color-mix(in_srgb,var(--color-metar)_22%,transparent)]"
        />
        {examples.length ? (
          <div className="mt-2.5 flex min-w-0 flex-wrap items-center gap-1.5">
            <span className="mr-0.5 text-[12px] text-slate-400">Try</span>
            {examples.map((ex) => (
              <button
                key={ex}
                type="button"
                onClick={() => setText(ex)}
                className="max-w-full truncate rounded-full px-2.5 py-1 text-left text-[12.5px] text-slate-600 shadow-[inset_0_0_0_1px_var(--color-cloud-300)] transition-colors hover:bg-cloud-50 hover:text-navy-900"
              >
                {ex}
              </button>
            ))}
          </div>
        ) : null}
        <div className="mt-4 flex justify-end">
          <button
            type="submit"
            disabled={!text.trim() || challenge.isPending}
            className="inline-flex h-9 shrink-0 items-center justify-center gap-2 rounded-lg bg-navy-900 px-4 text-[13.5px] font-semibold text-cloud-50 transition-colors hover:bg-navy-800 disabled:cursor-not-allowed disabled:opacity-45"
          >
            {challenge.isPending ? <Loader2 className="size-3.5 animate-spin" aria-hidden="true" /> : null}
            {challenge.isPending ? "Checking the evidence" : "Submit challenge"}
          </button>
        </div>
        {challenge.isError ? <ErrorNote error={challenge.error} className="mt-4" onRetry={() => challenge.mutate(text.trim())} /> : null}
      </form>

      <div aria-live="polite">
        <AnimatePresence mode="wait">
          {challenge.data ? (
            <motion.div key={challenge.submittedAt} initial={{ opacity: 0, y: 8 }} animate={{ opacity: 1, y: 0 }} exit={{ opacity: 0 }} transition={{ duration: 0.3, ease: [0.16, 1, 0.3, 1] }}>
              <ChallengeResult result={challenge.data} asked={challenge.variables ?? ""} />
            </motion.div>
          ) : null}
        </AnimatePresence>
      </div>
    </section>
  );
}

/** "Decision stands. …" → the lead sentence, set apart, and the rest. */
function splitLead(text: string) {
  const m = text.trim().match(/^(.+?[.!?])(\s+[\s\S]*)?$/);
  return m ? { lead: m[1], rest: (m[2] ?? "").trim() } : { lead: text, rest: "" };
}

function ChallengeResult({ result, asked }: { result: ChallengeResponse; asked: string }) {
  const { lead, rest } = splitLead(result.reply.text);
  return (
    <div className="border-t border-cloud-100 bg-cloud-25 px-5 pb-5 pt-4" data-testid="challenge-result">
      <div className="flex flex-wrap items-center gap-2">
        <StatusChip tone={CLASS_TONE[result.classification]}>{result.classification.replace(/_/g, "-")}</StatusChip>
        <span className="text-[12.5px] text-slate-500">
          for &ldquo;<span className="text-slate-600">{asked}</span>&rdquo;
        </span>
      </div>
      <p className={cn("mt-3 text-navy-900", result.decision_stands ? "display-tight text-[22px] leading-snug" : "text-[15px] font-semibold")}>{lead}</p>
      {rest ? <p className="mt-1.5 max-w-[72ch] whitespace-pre-line text-[14px] leading-relaxed text-slate-600">{rest}</p> : null}
      {result.reply.template_fallback ? <p className="mt-2 font-mono text-[11px] text-slate-400">template wording · a drafted number didn&rsquo;t match the evidence</p> : null}

      {result.question ? <RoutedQuestion question={result.question} /> : null}

      {result.cited.length ? (
        <div className="mt-4">
          <MicroLabel>Cited</MicroLabel>
          <div className="mt-1.5 rounded-lg bg-card px-4 shadow-[0_0_0_1px_var(--color-cloud-200)]">
            <EvidenceList evidence={result.cited} compact />
          </div>
        </div>
      ) : null}
    </div>
  );
}

function RoutedQuestion({ question }: { question: Question }) {
  const role = useSession((s) => s.role);
  const { viewAs, busy } = useViewAs();
  const navigate = useNavigate();
  const mine = role === question.routed_to;
  return (
    <div className="mt-4 rounded-lg bg-card p-4 shadow-[0_0_0_1px_var(--color-cloud-200),inset_3px_0_0_var(--color-held)]">
      <MicroLabel tone="held">New question</MicroLabel>
      <p className="mt-1.5 text-[14.5px] font-semibold leading-snug text-navy-900">{question.title}</p>
      <div className="mt-2 flex flex-col gap-1.5">
        <RoutedTo role={question.routed_to} holdsCents={question.holds_cents} />
        <ConfidenceLine confidence={question.confidence} reason={question.reason_tag.replace(/-/g, " ")} />
      </div>
      <div className="mt-3">
        {mine ? (
          <button type="button" onClick={() => navigate("/questions")} className="rounded-lg bg-navy-900 px-3.5 py-2 text-[13px] font-semibold text-cloud-50 hover:bg-navy-800">
            Answer it in Questions
          </button>
        ) : (
          <button
            type="button"
            disabled={!!busy}
            onClick={async () => {
              if (await viewAs(question.routed_to)) navigate("/questions");
            }}
            className="inline-flex items-center gap-2 rounded-lg px-3.5 py-2 text-[13px] font-semibold text-navy-900 shadow-[inset_0_0_0_1px_var(--color-cloud-300)] hover:bg-cloud-50 disabled:opacity-50"
          >
            {busy ? <Loader2 className="size-3.5 animate-spin" aria-hidden="true" /> : null}
            View as {ROLE_LABEL[question.routed_to]} to answer
          </button>
        )}
      </div>
    </div>
  );
}
