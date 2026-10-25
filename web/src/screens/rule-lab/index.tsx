import { Link } from "react-router";
import { ArrowUpRight } from "lucide-react";
import { MicroLabel } from "@/components/chips";
import { PageHeader } from "@/components/kit";
import { RuleLab } from "@/features/rule-lab/RuleLab";

export default function RuleLabScreen() {
  return <div className="mx-auto max-w-[1280px]">
    <PageHeader className="mb-6" eyebrow={<MicroLabel>Before a rule becomes routine</MicroLabel>} title="Rule Lab">
      Replay the original voucher ruling against cases it should resolve and cases it must protect.
    </PageHeader>
    <RuleLab />
    <Link to="/story" className="mt-5 inline-flex items-center gap-2 text-[13px] text-slate-500 hover:text-navy-900">See it in the animated story <ArrowUpRight size={14} aria-hidden="true" /></Link>
  </div>;
}
