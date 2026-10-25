import { Link } from "react-router";
import type { LearningStep, Rule } from "@/api/types";
import { count } from "@/lib/format";
import { cn } from "@/lib/utils";
import { learningLead } from "./model";

/** "R-CL-1@1" → the rule's own title, from GET /rules; the ref itself when the rule isn't listed. */
function titleOf(ref: string, rules: Rule[] | undefined): string {
  const [id, version] = ref.split("@");
  const family = (rules ?? []).filter((r) => r.id === id);
  const hit = family.find((r) => String(r.version) === version) ?? family[family.length - 1];
  return hit?.title ?? ref;
}

const chip = "inline-flex h-6 max-w-full items-center gap-1.5 rounded-md px-2 text-[12px] leading-none transition-colors";

/**
 * "Learned and reused", top of Policies: one row per storm or event, in the order the clock reached them,
 * with the questions it asked, the cases reused rules settled without asking, and the server's own note.
 * Each rule is a chip that jumps to its card.
 */
export function LearnedAndReused({ steps, rules }: { steps: LearningStep[]; rules?: Rule[] }) {
  if (!steps.length) return null;
  return (
    <section aria-labelledby="learning-title" data-testid="learned-and-reused" className="mt-6 rounded-xl bg-card px-5 py-4 shadow-[0_0_0_1px_var(--color-cloud-200),0_1px_2px_rgba(13,21,36,0.04)]">
      <h2 id="learning-title" className="text-[14.5px] font-semibold text-navy-900">
        Learned and reused
      </h2>
      <p className="mt-1 max-w-[86ch] text-[13.5px] leading-relaxed text-slate-600" data-testid="learning-lead">
        {learningLead(steps)}
      </p>
      <ol className="mt-3 flex flex-col">
        {steps.map((s, i) => (
          <li key={s.run_id} data-testid="learning-step" className="relative grid gap-x-6 gap-y-1.5 pb-4 pl-6 last:pb-0 md:grid-cols-[230px_minmax(0,1fr)]">
            {/* the timeline rail: a dot per step, a line to the next */}
            <span aria-hidden="true" className={cn("absolute left-[3px] top-[7px] size-2 rounded-full", i === 0 ? "bg-navy-800" : "bg-metar")} />
            {i < steps.length - 1 ? <span aria-hidden="true" className="absolute bottom-0 left-[6.5px] top-[19px] w-px bg-cloud-200" /> : null}
            <div className="min-w-0">
              <p className="text-[13.5px] font-medium leading-snug text-navy-900">{s.name}</p>
              <p className="mt-0.5 text-[12.5px] text-slate-500">
                <span className="whitespace-nowrap">
                  <span className="figure font-semibold text-navy-900">{count(s.questions_asked)}</span> {s.questions_asked === 1 ? "question" : "questions"} asked
                </span>
                <span className="text-slate-400"> · </span>
                <span className="whitespace-nowrap">
                  <span className="figure font-semibold text-navy-900">{count(s.cases_settled_by_reused_rules)}</span> settled without asking
                </span>
              </p>
            </div>
            <div className="min-w-0">
              <p className="text-[13px] leading-relaxed text-slate-600">{s.note}</p>
              {s.reused.length || s.new_rules.length ? (
                <ul className="mt-1.5 flex flex-wrap gap-1.5" aria-label={`Rules on ${s.name}`}>
                  {s.reused.map((r) => (
                    <li key={`reused-${r.rule_ref}`} className="max-w-full">
                      <Link to={`/policies#${r.rule_ref}`} title={`${r.rule_ref}, learned from ${r.learned_from}`} className={cn(chip, "bg-cloud-100 text-slate-700 hover:bg-cloud-200")}>
                        <span aria-hidden="true" className="font-mono text-slate-400">
                          ↻
                        </span>
                        <span className="truncate">{r.title}</span>{" "}
                        <span className="figure shrink-0 text-slate-500">· {count(r.cases)}</span>
                      </Link>
                    </li>
                  ))}
                  {s.new_rules.map((ref) => (
                    <li key={`new-${ref}`} className="max-w-full">
                      <Link to={`/policies#${ref}`} title={`${ref}, first confirmed here`} className={cn(chip, "text-slate-600 shadow-[inset_0_0_0_1px_var(--color-cloud-300)] hover:bg-cloud-50")}>
                        <span className="shrink-0 text-slate-400">new</span>{" "}
                        <span className="truncate">{titleOf(ref, rules)}</span>
                      </Link>
                    </li>
                  ))}
                </ul>
              ) : null}
            </div>
          </li>
        ))}
      </ol>
    </section>
  );
}
