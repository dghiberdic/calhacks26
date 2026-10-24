import { motion, useReducedMotion } from "motion/react";
import { Lock } from "lucide-react";
import type { Rule } from "@/api/types";
import { MicroLabel } from "@/components/chips";
import { RoleAvatar } from "@/components/kit";
import { RuleSentence, actionText, ruleRef } from "@/components/rule-sentence";
import { ROLE_LABEL, longDate } from "@/lib/format";
import { cn } from "@/lib/utils";
import { staticCardFacts, type RuleFamily } from "./model";
import { RuleStatusChip } from "./parts";

/**
 * Reg (EU) 2026/2202: a future-dated version of the law, shown so nobody is surprised by it, with no
 * engine logic behind it. Every date on the card is the rule's own.
 */
export function StaticRegulationCard({ rule, highlighted, index = 0 }: { rule: Rule; highlighted?: boolean; index?: number }) {
  const reduce = useReducedMotion();
  const f = staticCardFacts(rule);
  const facts = [f.inForce ? `in force ${longDate(f.inForce)}` : null, f.appliesFrom ? `applies from ${longDate(f.appliesFrom)}` : null, f.claimWindowMonths ? `${f.claimWindowMonths}-month claim window` : null].filter(
    (x): x is string => !!x,
  );
  return (
    <motion.article
      id={ruleRef(rule)}
      data-family={rule.id}
      data-testid="static-regulation-card"
      initial={reduce ? false : { opacity: 0, y: 10 }}
      animate={{ opacity: 1, y: 0 }}
      transition={{ delay: Math.min(index, 6) * 0.05, duration: 0.45, ease: [0.16, 1, 0.3, 1] }}
      className={cn(
        "relative scroll-mt-24 overflow-hidden rounded-xl bg-cloud-25 p-5 outline-1 -outline-offset-1 outline-dashed outline-cloud-400 transition-shadow duration-700 md:p-6",
        highlighted && "shadow-[0_0_0_2px_var(--color-navy-800),0_8px_28px_rgba(13,21,36,0.12)]",
      )}
      aria-label={[f.title, ...facts].join(" · ")}
    >
      <div className="flex flex-wrap items-center gap-2">
        <MicroLabel>Display only · no engine logic</MicroLabel>
        <span className="ml-auto flex items-center gap-2">
          <span className="font-mono text-[11.5px] text-slate-400">{ruleRef(rule)}</span>
          <RuleStatusChip status={rule.status} />
        </span>
      </div>
      <h3 className="display-tight mt-3 text-[22px] leading-tight text-navy-900 md:text-[24px]">{f.title}</h3>
      <p className="mt-1.5 font-mono text-[12.5px] text-slate-600">{facts.join(" · ")}</p>

      {f.inForce && f.appliesFrom ? (
        <div className="mt-6 max-w-[620px]" aria-hidden="true">
          <div className="relative h-3">
            <span className="absolute inset-x-[6px] top-1/2 h-0 -translate-y-1/2 border-t border-dashed border-cloud-400" />
            <span className="absolute left-0 top-0 size-3 rounded-full bg-navy-900" />
            <span className="absolute right-0 top-0 size-3 rounded-full bg-cloud-25 shadow-[inset_0_0_0_2px_var(--color-navy-900)]" />
          </div>
          <div className="mt-2 flex justify-between gap-4 text-[12px]">
            <span>
              <span className="micro block text-slate-400">in force</span>
              <span className="figure text-navy-900">{longDate(f.inForce)}</span>
            </span>
            <span className="text-right">
              <span className="micro block text-slate-400">applies from</span>
              <span className="figure text-navy-900">{longDate(f.appliesFrom)}</span>
            </span>
          </div>
        </div>
      ) : null}
      <p className="mt-5 text-[13px] text-slate-500">Display only. Each flight is decided under the regulation in force on its date.</p>
    </motion.article>
  );
}

/** Hard controls are code: listed quietly, with nothing to widen or revert. */
export function HardControls({ families }: { families: RuleFamily[] }) {
  return (
    <ul className="grid gap-px overflow-hidden rounded-xl bg-cloud-200 shadow-[0_0_0_1px_var(--color-cloud-200)] md:grid-cols-2">
      {families.map(({ current: rule }) => (
        <li key={rule.id} id={ruleRef(rule)} data-family={rule.id} className="flex scroll-mt-24 items-start gap-3 bg-card px-5 py-4">
          <Lock className="mt-0.5 size-3.5 shrink-0 text-slate-400" aria-hidden="true" />
          <div className="min-w-0 flex-1">
            <HardControlText rule={rule} />
            <p className="mt-1.5 flex flex-wrap items-center gap-x-2 gap-y-1 font-mono text-[11px] text-slate-400">
              <span>{ruleRef(rule)}</span>
              <span aria-hidden="true">·</span>
              <span className="inline-flex items-center gap-1">
                <span aria-hidden="true" className="inline-flex">
                  <RoleAvatar role={rule.authority_required} size="sm" className="size-4 text-[7px]" />
                </span>
                {ROLE_LABEL[rule.authority_required]}
              </span>
              {rule.times_cited ? (
                <>
                  <span aria-hidden="true">·</span>
                  <span>enforced {rule.times_cited}×</span>
                </>
              ) : null}
            </p>
          </div>
        </li>
      ))}
    </ul>
  );
}

/** A hard control's own sentence when it carries one, else its condition as a sentence. */
function HardControlText({ rule }: { rule: Rule }) {
  if (rule.title) return <p className="text-[14px] leading-snug text-navy-900">{rule.title}</p>;
  if (rule.origin_example) return <p className="text-[14px] leading-snug text-navy-900">{rule.origin_example}</p>;
  const hasCondition = Object.keys(rule.condition ?? {}).length > 0 || Object.keys(rule.scope ?? {}).length > 0;
  if (!hasCondition) return <p className="text-[14px] leading-snug text-navy-900">Always: {actionText(rule)}.</p>;
  return <RuleSentence rule={rule} className="text-[14px] leading-snug" />;
}
