import { useId, useState } from "react";
import { Link } from "react-router";
import { AnimatePresence, motion } from "motion/react";
import { BellRing, ChevronDown, Lock, LockOpen } from "lucide-react";
import type { Question, Role } from "@/api/types";
import { MicroLabel, StatusChip } from "@/components/chips";
import { EvidenceList } from "@/components/evidence";
import { ConfidenceLine, RoutedTo } from "@/components/kit";
import { count, ROLE_LABEL, zuluDay } from "@/lib/format";
import { cn } from "@/lib/utils";
import { AnswerFlow, type Flow } from "./AnswerFlow";
import { caseCount, caseHref, caseKind, caseLabel, reasonText, reminderText } from "./lib";
import { MaskedText } from "./MaskedText";

/**
 * One question per pattern: what it found, why it flagged it, what it recommends, the evidence, and
 * (for the routed seat only) the ruling pad on the right.
 */
export function QuestionCard({ question, role, flow, onFlow }: { question: Question; role: Role; flow: Flow; onFlow: (f: Flow) => void }) {
  const titleId = useId();
  const canAnswer = role === question.routed_to;
  const reminder = reminderText(question);
  const passengerLevel = question.case_refs.some((r) => caseKind(r) === "passenger");
  const resolved = flow.step === "saved" || flow.step === "recorded";

  return (
    <article
      aria-labelledby={titleId}
      data-testid={`question-${question.id}`}
      className={cn(
        "overflow-hidden rounded-2xl bg-card shadow-[0_0_0_1px_var(--color-cloud-200),0_1px_2px_rgba(13,21,36,0.04),0_8px_24px_-12px_rgba(13,21,36,0.08)]",
        resolved && "shadow-[0_0_0_1px_var(--color-cloud-200),0_1px_2px_rgba(13,21,36,0.04)]",
      )}
    >
      <div className="grid lg:grid-cols-[minmax(0,1fr)_400px] xl:grid-cols-[minmax(0,1fr)_440px]">
        <div className="min-w-0 p-5 md:p-6">
          <div className="flex flex-wrap items-center justify-between gap-x-4 gap-y-2">
            <RoutedTo role={question.routed_to} holdsCents={resolved ? null : question.holds_cents} />
            {reminder && !resolved ? (
              <StatusChip tone="held" dot={false} className="h-auto min-h-6 items-start gap-1.5 whitespace-normal py-1 leading-snug">
                <BellRing className="mt-px size-3 shrink-0" aria-hidden="true" />
                <span>{reminder}</span>
              </StatusChip>
            ) : null}
          </div>

          <h2 id={titleId} className="display-tight mt-3 text-[21px] leading-snug text-navy-900 md:text-[23px]">
            <MaskedText text={question.title} />
          </h2>

          <div className="mt-2.5 flex flex-wrap items-center gap-x-3 gap-y-2">
            <ConfidenceLine confidence={question.confidence} reason={reasonText(question.reason_tag)} />
          </div>

          <div className="mt-3 flex flex-wrap items-center gap-1.5">
            <span className="mr-1 text-[12.5px] text-slate-500">{caseCount(question.case_refs)}</span>
            {question.case_refs.map((ref) => {
              const href = caseHref(ref);
              const chip = (
                <StatusChip tone="outline" dot={false} className="h-6 text-[11.5px]">
                  {caseLabel(ref)}
                </StatusChip>
              );
              return href ? (
                <Link key={ref} to={href} className="rounded-md hover:bg-cloud-50" title={ref}>
                  {chip}
                </Link>
              ) : (
                <span key={ref}>{chip}</span>
              );
            })}
            {passengerLevel ? <PiiChip role={role} /> : null}
            <span className="ml-auto text-[12px] tabular-nums text-slate-400">asked {zuluDay(question.asked_at)}</span>
          </div>

          <dl className="mt-6 flex flex-col gap-4">
            <Block label="What it found" text={question.found} />
            <Block label="Why it flagged it" text={question.why_flagged} />
            <Block label="What it recommends" text={question.recommends} emphasis />
          </dl>

          {question.evidence.length ? <EvidenceDisclosure question={question} /> : null}
        </div>

        <div className="border-t border-cloud-100 bg-cloud-25 p-5 md:p-6 lg:border-l lg:border-t-0">
          <AnswerFlow question={question} flow={flow} onFlow={onFlow} canAnswer={canAnswer} />
        </div>
      </div>
    </article>
  );
}

function Block({ label, text, emphasis }: { label: string; text: string; emphasis?: boolean }) {
  return (
    <div className={cn("grid gap-1 md:grid-cols-[148px_minmax(0,1fr)] md:gap-4", emphasis && "rounded-lg bg-cloud-25 py-2.5 pr-3 shadow-[inset_0_0_0_1px_var(--color-cloud-100)] md:-ml-3 md:pl-3")}>
      <dt className="micro pt-[3px] text-slate-500">{label}</dt>
      <dd className={cn("max-w-[68ch] text-[14.5px] leading-relaxed", emphasis ? "font-medium text-navy-900" : "text-slate-600")}>
        <MaskedText text={text} />
      </dd>
    </div>
  );
}

/** Passenger-level questions carry PII: the Claims Lead sees it, every other seat gets it masked by the server. */
function PiiChip({ role }: { role: Role }) {
  const visible = role === "claims_lead";
  return (
    <StatusChip tone={visible ? "slate" : "outline"} dot={false} className="h-6 gap-1 text-[11px]" title={visible ? "Passenger data is visible to the Claims Lead" : "The server masks passenger data for this seat"}>
      {visible ? <LockOpen className="size-3" aria-hidden="true" /> : <Lock className="size-3" aria-hidden="true" />}
      {visible ? "PII visible to this role" : `PII masked for ${ROLE_LABEL[role]}`}
    </StatusChip>
  );
}

function EvidenceDisclosure({ question }: { question: Question }) {
  const [open, setOpen] = useState(true);
  const id = useId();
  const struck = question.evidence.filter((e) => e.struck).length;
  return (
    <div className="mt-6 border-t border-cloud-100 pt-4">
      <button type="button" aria-expanded={open} aria-controls={id} onClick={() => setOpen((v) => !v)} className="flex w-full items-center justify-between gap-3 rounded-md text-left">
        <span className="flex items-baseline gap-2">
          <MicroLabel>Evidence · {count(question.evidence.length)}</MicroLabel>
          <span className="text-[12px] text-slate-400">ranked by trust tier{struck ? ", the losing source struck" : ""}</span>
        </span>
        <ChevronDown className={cn("size-4 text-slate-400 transition-transform", open && "rotate-180")} aria-hidden="true" />
      </button>
      <AnimatePresence initial={false}>
        {open ? (
          <motion.div id={id} key="ev" initial={{ height: 0, opacity: 0 }} animate={{ height: "auto", opacity: 1 }} exit={{ height: 0, opacity: 0 }} transition={{ duration: 0.25, ease: [0.25, 1, 0.5, 1] }} className="overflow-hidden">
            <EvidenceList evidence={question.evidence} compact className="mt-1" />
          </motion.div>
        ) : null}
      </AnimatePresence>
    </div>
  );
}
