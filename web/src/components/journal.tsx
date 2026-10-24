import type { ReactNode } from "react";
import type { JournalEntry, ReplayDiff } from "@/api/types";
import { eur, longDate, periodLabel, shortId } from "@/lib/format";
import { cn } from "@/lib/utils";
import { MicroLabel, StatusChip, TiesChip } from "./chips";
import { Money } from "./kit";

export const KIND_LABEL: Record<JournalEntry["kind"], string> = {
  sale: "sale",
  refund: "refund",
  voucher: "refund voucher",
  reroute_fim: "partner reroute (FIM)",
  compensation_estimate: "EU261 compensation liability",
  claim_approved: "claim approved",
  claim_paid: "claim paid",
  change_in_estimate: "change in estimate",
  derecognition: "derecognition at limitation",
  care_accrual: "care accrual",
  care_invoice: "care invoices",
  recode: "recode",
  out_of_period_adjustment: "out-of-period adjustment",
  voucher_in_lieu: "service-desk voucher in lieu",
  voucher_void: "voucher voided",
};

/** "NOT YET POSTED · BUILT FROM 3 SOURCES": StormCheck parks journals, it never posts beyond approval. */
export function statusLabel(je: Pick<JournalEntry, "status" | "built_from">) {
  const built = je.built_from ? ` · built from ${je.built_from} source${je.built_from === 1 ? "" : "s"}` : "";
  if (je.status === "draft") return `not yet posted${built}`;
  if (je.status === "approved") return `approved · parked, not posted${built}`;
  return `posted${built}`;
}

/** A journal draft with Dr/Cr lines, the IAS 8 class, ties and an actions slot ([Edit][Approve]). */
export function JournalCard({ entry, actions, className, dense }: { entry: JournalEntry; actions?: ReactNode; className?: string; dense?: boolean }) {
  const dr = entry.lines.reduce((s, l) => s + (l.dr_cents ?? 0), 0);
  const cr = entry.lines.reduce((s, l) => s + (l.cr_cents ?? 0), 0);
  return (
    <article className={cn("rounded-xl bg-card shadow-[0_0_0_1px_var(--color-cloud-200)]", className)}>
      <header className="flex flex-wrap items-start justify-between gap-3 px-5 pt-4">
        <div className="min-w-0">
          <MicroLabel tone={entry.status === "draft" ? "slate" : "metar"}>{statusLabel(entry)}</MicroLabel>
          <h3 className="mt-1 text-[14.5px] font-semibold text-navy-900">
            <span className="font-mono text-[12.5px] font-normal text-slate-500">{entry.id}</span> · {KIND_LABEL[entry.kind] ?? entry.kind}
          </h3>
          {!dense ? <p className="mt-1 max-w-[60ch] text-[13px] leading-relaxed text-slate-500">{entry.memo}</p> : null}
        </div>
        <div className="flex flex-wrap items-center gap-1.5">
          {entry.ias8_class && entry.ias8_class !== "none" ? (
            <StatusChip tone="outline" dot={false}>
              {entry.ias8_class === "change_in_estimate" ? "change in estimate · IAS 8.36" : "prior-period error · corrected in current period"}
            </StatusChip>
          ) : null}
          {(entry.ties_to ?? []).map((t) => (
            <TiesChip key={t} account={t.replace(/\D/g, "") || t} />
          ))}
        </div>
      </header>
      <table className="mt-3 w-full text-[13px]">
        <thead>
          <tr className="micro text-slate-400">
            <th scope="col" className="w-10 px-5 pb-1.5 text-left font-normal" />
            <th scope="col" className="pb-1.5 text-left font-normal">Account</th>
            <th scope="col" className="pb-1.5 pr-3 text-right font-normal">Dr</th>
            <th scope="col" className="pb-1.5 pr-5 text-right font-normal">Cr</th>
          </tr>
        </thead>
        <tbody>
          {entry.lines.map((l, i) => (
            <tr key={i} className="border-t border-cloud-100">
              <td className="px-5 py-2 font-mono text-[11.5px] text-slate-400">{l.dr_cents ? "Dr" : "Cr"}</td>
              {/* Long account names wrap inside their cell; the amounts keep their own columns. */}
              <td className={cn("break-words py-2 pr-4 align-top", !l.dr_cents && "pl-5")}>
                <span className="font-mono text-[12px] text-slate-500">{l.account}</span> <span className="text-navy-900">{l.account_name}</span>
              </td>
              <td className="whitespace-nowrap py-2 pr-3 text-right align-top">{l.dr_cents ? <Money cents={l.dr_cents} withCents /> : null}</td>
              <td className="whitespace-nowrap py-2 pr-5 text-right align-top">{l.cr_cents ? <Money cents={l.cr_cents} withCents /> : null}</td>
            </tr>
          ))}
          <tr className="border-t border-cloud-200 text-slate-500">
            <td className="px-5 py-2" />
            <td className="py-2 text-[12px]">{dr === cr ? "Balanced" : "Out of balance"}</td>
            <td className="py-2 pr-3 text-right text-[12.5px]">
              <Money cents={dr} withCents />
            </td>
            <td className="py-2 pr-5 text-right text-[12.5px]">
              <Money cents={cr} withCents />
            </td>
          </tr>
        </tbody>
      </table>
      <footer className="flex flex-wrap items-center justify-between gap-3 border-t border-cloud-100 px-5 py-3 text-[12.5px] text-slate-500">
        <span>
          Event {longDate(entry.event_date)} · period {periodLabel(entry.period)} · prepared by <span className="font-mono">{entry.preparer}</span>
          {entry.approver ? (
            <>
              {" "}
              · approved by <span className="font-mono">{entry.approver}</span>
            </>
          ) : null}
        </span>
        {actions}
      </footer>
    </article>
  );
}

/** "flips 3 · (€47,496) · Jan locked, untouched" and the flips themselves. */
export function ReplaySummary({ diff, className }: { diff: ReplayDiff; className?: string }) {
  const locked = (diff.locked_periods_untouched ?? []).map(periodLabel).join(", ");
  return (
    <p className={cn("text-[13px] text-slate-600", className)}>
      flips <span className="figure font-semibold text-navy-900">{diff.flips.length}</span> · Δ <span className="figure font-semibold text-navy-900">{eur(diff.total_delta_cents, { signed: true })}</span>
      {locked ? ` · ${locked} locked, untouched` : ""}
    </p>
  );
}

function valueText(v: unknown) {
  if (v === null || v === undefined) return "—";
  return typeof v === "string" || typeof v === "number" || typeof v === "boolean" ? String(v) : JSON.stringify(v);
}

export function ReplayFlips({ diff, limit = 8, className }: { diff: ReplayDiff; limit?: number; className?: string }) {
  const shown = diff.flips.slice(0, limit);
  return (
    <div className={className}>
      <ul className="flex flex-col">
        {shown.map((f, i) => (
          <li key={`${f.entity_id}-${i}`} className="grid grid-cols-[minmax(0,1fr)_auto] gap-3 border-t border-cloud-100 py-2 text-[13px] first:border-t-0">
            {/* Wraps rather than truncates: the "after" value is the point of the row. */}
            <span className="min-w-0 break-words">
              <span className="font-mono text-[12px] text-navy-900">{shortId(f.entity_id)}</span> <span className="text-slate-400">{f.field}</span>{" "}
              <span className="font-mono text-[12px] text-slate-500 line-through decoration-slate-300">{valueText(f.before)}</span> <span className="text-slate-400">→</span>{" "}
              <span className="font-mono text-[12px] font-medium text-navy-900">{valueText(f.after)}</span>
            </span>
            {f.delta_cents ? <Money cents={f.delta_cents} signed className="text-[12.5px] text-slate-600" /> : <span />}
          </li>
        ))}
      </ul>
      {diff.flips.length > limit ? <p className="mt-1 text-[12px] text-slate-400">and {diff.flips.length - limit} more</p> : null}
    </div>
  );
}
