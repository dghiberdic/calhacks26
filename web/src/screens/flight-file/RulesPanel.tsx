import { Link } from "react-router";
import { ArrowUpRight } from "lucide-react";
import { useRules } from "@/api/queries";
import type { FlightDecision, Rule } from "@/api/types";
import { MicroLabel } from "@/components/chips";
import { actionText, TIER_LABEL } from "@/components/rule-sentence";
import { count } from "@/lib/format";
import { legalGloss } from "./lib";

function parseRef(ref: string) {
  const [id, v] = ref.split("@");
  return { id, version: v ? Number(v) : null };
}

function findRule(rules: Rule[] | undefined, ref: string) {
  const { id, version } = parseRef(ref);
  const same = (rules ?? []).filter((r) => r.id === id);
  return same.find((r) => r.version === version) ?? same.sort((a, b) => b.version - a.version)[0] ?? null;
}

/** Rules the decision cites (linked to Policies) and the law it rests on. */
export function RulesPanel({ decision }: { decision: FlightDecision }) {
  const rules = useRules();
  const cited = decision.rules_applied ?? [];
  const law = decision.legal_basis ?? [];
  if (!cited.length && !law.length) return null;
  return (
    <section aria-labelledby="rules-title" className="rounded-xl bg-card shadow-[0_0_0_1px_var(--color-cloud-200),0_1px_2px_rgba(13,21,36,0.04)]">
      <header className="px-5 pt-4">
        <h2 id="rules-title" className="text-[14.5px] font-semibold text-navy-900">
          Rules and law
        </h2>
      </header>
      <div className="grid gap-x-8 gap-y-5 px-5 pb-5 pt-3 md:grid-cols-2">
        {cited.length ? (
          <div className="min-w-0">
            <MicroLabel>Rules cited · {count(cited.length)}</MicroLabel>
            <ul className="mt-2 flex flex-col">
              {cited.map((ref) => {
                const rule = findRule(rules.data, ref);
                const { id } = parseRef(ref);
                return (
                  <li key={ref} className="border-t border-cloud-100 first:border-t-0">
                    <Link to={`/policies#${encodeURIComponent(id)}`} className="group grid grid-cols-[minmax(0,1fr)_14px] items-start gap-2 py-2.5">
                      <span className="min-w-0">
                        <span className="flex flex-wrap items-baseline gap-x-2">
                          <span className="font-mono text-[12.5px] font-bold text-navy-900 group-hover:underline">{ref}</span>
                          {rule ? <span className="text-[12px] text-slate-500">{TIER_LABEL[rule.tier]}{rule.support ? ` · ${rule.support}` : ""}</span> : null}
                        </span>
                        {rule ? <span className="mt-0.5 block text-[13px] leading-snug text-slate-600">{capital(actionText(rule))}</span> : null}
                      </span>
                      <ArrowUpRight className="mt-0.5 size-3.5 text-slate-400 group-hover:text-navy-900" aria-hidden="true" />
                    </Link>
                  </li>
                );
              })}
            </ul>
          </div>
        ) : null}
        {law.length ? (
          <div className="min-w-0">
            <MicroLabel>Legal basis</MicroLabel>
            <ul className="mt-2 flex flex-col">
              {law.map((c) => {
                const gloss = legalGloss(c);
                return (
                  <li key={c} className="border-t border-cloud-100 py-2.5 first:border-t-0">
                    <span className="block text-[13px] font-medium text-navy-900">{c}</span>
                    {gloss ? <span className="mt-0.5 block text-[13px] leading-snug text-slate-500">{gloss}</span> : null}
                  </li>
                );
              })}
            </ul>
          </div>
        ) : null}
      </div>
    </section>
  );
}

const capital = (s: string) => s.charAt(0).toUpperCase() + s.slice(1);
