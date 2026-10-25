import { useId, useState } from "react";
import { AnimatePresence, motion } from "motion/react";
import { ChevronDown } from "lucide-react";
import type { JournalEntry } from "@/api/types";
import { MicroLabel } from "@/components/chips";
import { Explain } from "@/components/explain";
import { JournalCard, statusLabel } from "@/components/journal";
import { Money } from "@/components/kit";
import { count } from "@/lib/format";
import { cn } from "@/lib/utils";
import { featureLabel } from "./lib";

/** Short names for journal kinds on the one-line rows (the full card names them itself). */
const KIND: Partial<Record<JournalEntry["kind"], string>> = {
  compensation_estimate: "EU261 compensation liability",
  refund: "Refund",
  voucher: "Refund voucher",
  reroute_fim: "Partner reroute (FIM)",
  voucher_in_lieu: "Service-desk voucher in lieu",
  care_accrual: "Care accrual",
  claim_approved: "Claim approved",
  change_in_estimate: "Change in estimate",
  recode: "Recode",
};

const total = (je: JournalEntry) => je.lines.reduce((s, l) => s + (l.dr_cents ?? 0), 0);

/**
 * The flight's journal entries, one line each (what, status, amount); a row opens into the full card with its
 * Dr/Cr lines. StormCheck drafts and parks them: a person approves, and it never posts on its own.
 */
export function JournalDrafts({ entries }: { entries: JournalEntry[] }) {
  return (
    <section aria-labelledby="journals-title">
      <div className="mb-2.5 px-1">
        <h2 id="journals-title" className="text-[14.5px] font-semibold text-navy-900">
          Journal entries <span className="figure font-normal text-slate-400">{count(entries.length)}</span>
        </h2>
        <p className="mt-0.5 text-[12.5px] text-slate-500">
          The bookkeeping behind this flight. Drafts are parked for approval: StormCheck never posts. Open a row for its <Explain term="dr-cr">Dr / Cr</Explain> lines.
        </p>
      </div>
      <ul className="overflow-hidden rounded-xl bg-card shadow-[0_0_0_1px_var(--color-cloud-200),0_1px_2px_rgba(13,21,36,0.04)]">
        {entries.map((je) => (
          <DraftRow key={je.id} entry={je} />
        ))}
      </ul>
    </section>
  );
}

function DraftRow({ entry }: { entry: JournalEntry }) {
  const [open, setOpen] = useState(false);
  const id = useId();
  return (
    <li className="border-t border-cloud-100 first:border-t-0">
      <button
        type="button"
        aria-expanded={open}
        aria-controls={id}
        onClick={() => setOpen((v) => !v)}
        className="grid w-full grid-cols-[minmax(0,1fr)_auto_16px] items-center gap-x-4 gap-y-0.5 px-5 py-3 text-left transition-colors hover:bg-cloud-25 sm:grid-cols-[96px_minmax(0,1fr)_auto_auto_16px]"
      >
        <span className="hidden font-mono text-[12px] text-slate-500 sm:block">{entry.id}</span>
        <span className="min-w-0 truncate text-[13.5px] text-navy-900">{KIND[entry.kind] ?? featureLabel(entry.kind)}</span>
        <MicroLabel className="hidden text-[10px] text-slate-400 md:block">{statusLabel(entry)}</MicroLabel>
        <Money cents={total(entry)} className="text-right text-[13.5px] text-navy-900" />
        <ChevronDown className={cn("size-4 text-slate-400 transition-transform", open && "rotate-180")} aria-hidden="true" />
      </button>
      <AnimatePresence initial={false}>
        {open ? (
          <motion.div id={id} key="je" initial={{ height: 0, opacity: 0 }} animate={{ height: "auto", opacity: 1 }} exit={{ height: 0, opacity: 0 }} transition={{ duration: 0.25, ease: [0.25, 1, 0.5, 1] }} className="overflow-hidden">
            <JournalCard entry={entry} className="rounded-none shadow-none [&>header]:pt-1" />
          </motion.div>
        ) : null}
      </AnimatePresence>
    </li>
  );
}
