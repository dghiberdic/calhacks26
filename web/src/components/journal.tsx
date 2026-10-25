import type { ReactNode } from "react";
import { Link } from "react-router";
import { Check, Lock } from "lucide-react";
import type { JournalEntry, ReplayDiff, Role } from "@/api/types";
import { eur, longDate, periodLabel, ROLE_LABEL, shortId } from "@/lib/format";
import { plainMemo } from "@/lib/plain";
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

/** Status as a controller reads it: drafts and approvals are parked (SAP-style), only source-system entries are posted. */
export const STATUS_WORD: Record<string, string> = { draft: "draft · parked", approved: "approved · parked", posted: "posted", rejected: "rejected" };

/** Who must approve: payouts and claim approvals need the Claims Lead; every other kind the Controller (books SoD). */
function approverSeat(kind: JournalEntry["kind"]): Role {
  return kind === "claim_approved" || kind === "claim_paid" ? "claims_lead" : "controller";
}

/** "agent.engine" → "Engine"; seats by their name; anything else as given. */
const principalName = (p: string | null | undefined) => (p ? ((ROLE_LABEL as Record<string, string>)[p] ?? (p === "system.pss" ? "PSS / revenue accounting" : p)) : "—");

/** "2140" → GL 2140; "register:NS113@2025-01-24" → the obligation register for NS113. */
function tieLabel(t: string) {
  const [kind, ref] = t.includes(":") ? [t.slice(0, t.indexOf(":")), t.slice(t.indexOf(":") + 1)] : ["gl", t];
  return kind === "gl" ? { account: t, text: null } : { account: null, text: `ties to ${kind} ${shortId(ref)}` };
}

/** A journal draft with Dr/Cr lines, the IAS 8 class, ties, the SoD and period-lock controls and an actions slot ([Edit][Approve]). */
export function JournalCard({ entry, actions, className, dense, periodLocked }: { entry: JournalEntry; actions?: ReactNode; className?: string; dense?: boolean; periodLocked?: boolean | null }) {
  const dr = entry.lines.reduce((s, l) => s + (l.dr_cents ?? 0), 0);
  const cr = entry.lines.reduce((s, l) => s + (l.cr_cents ?? 0), 0);
  const seat = approverSeat(entry.kind);
  const sod = entry.approver ? entry.approver !== entry.preparer : null;
  return (
    <article className={cn("rounded-xl bg-card shadow-[0_0_0_1px_var(--color-cloud-200)]", className)}>
      <header className="flex flex-wrap items-start justify-between gap-3 px-5 pt-4">
        <div className="min-w-0">
          <MicroLabel tone={entry.status === "draft" ? "slate" : "metar"}>{statusLabel(entry)}</MicroLabel>
          <h3 className="mt-1 text-[14.5px] font-semibold text-navy-900">
            <span className="font-mono text-[12.5px] font-normal text-slate-500">{entry.id}</span> · {KIND_LABEL[entry.kind] ?? entry.kind}
          </h3>
          {!dense ? <p className="mt-1 max-w-[60ch] text-[13px] leading-relaxed text-slate-500" title={entry.memo}>{plainMemo(entry.memo)}</p> : null}
        </div>
        <div className="flex flex-wrap items-center gap-1.5">
          {entry.ias8_class && entry.ias8_class !== "none" ? (
            <StatusChip tone="outline" dot={false}>
              {entry.ias8_class === "change_in_estimate" ? "change in estimate · IAS 8.36" : "prior-period error · corrected in current period"}
            </StatusChip>
          ) : null}
          {(entry.ties_to ?? []).map((t) => {
            const tie = tieLabel(t);
            return tie.account ? (
              <TiesChip key={t} account={tie.account} />
            ) : (
              <StatusChip key={t} tone="outline" dot={false} className="font-mono text-[10.5px]">
                {tie.text}
              </StatusChip>
            );
          })}
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
      {dense ? null : <dl className="grid grid-cols-2 gap-x-4 gap-y-2 border-t border-cloud-100 px-5 py-3 text-[12.5px] sm:grid-cols-4" data-testid="je-controls">
        <div>
          <dt className="micro text-slate-400">Status</dt>
          <dd className="mt-0.5 text-navy-900">{STATUS_WORD[entry.status] ?? entry.status}</dd>
        </div>
        <div>
          <dt className="micro text-slate-400">Preparer</dt>
          <dd className="mt-0.5 text-navy-900" title={entry.preparer}>
            {principalName(entry.preparer)}
          </dd>
        </div>
        <div>
          <dt className="micro text-slate-400">Approver</dt>
          <dd className="mt-0.5 text-navy-900" title={entry.approver ?? undefined}>
            {entry.approver ? principalName(entry.approver) : <span className="text-slate-500">pending · {ROLE_LABEL[seat]}</span>}
          </dd>
        </div>
        <div>
          <dt className="micro text-slate-400">Period {periodLabel(entry.period)}</dt>
          <dd className="mt-0.5 inline-flex items-center gap-1 text-navy-900">
            {periodLocked ? <Lock className="size-3 text-slate-500" aria-hidden="true" /> : null}
            {periodLocked === undefined || periodLocked === null ? <span className="text-slate-500">lock state on Close</span> : periodLocked ? "locked · never written again" : "open"}
          </dd>
        </div>
        <div className="col-span-2 flex items-center gap-1.5 text-slate-500 sm:col-span-4">
          {sod ? <Check className="size-3.5 text-tie" aria-hidden="true" /> : null}
          {entry.status === "posted" && !entry.approver ? (
            `Posted in the source system (${principalName(entry.preparer)}); recorded by StormCheck, never posted by it.`
          ) : sod === false ? (
            "Control breach: the preparer approved their own entry"
          ) : (
            <span>
              Control: preparer <span className="font-mono">≠</span> approver
              {sod ? ` ✓ (${principalName(entry.preparer)} → ${principalName(entry.approver)})` : `. ${principalName(entry.preparer)} can't approve its own entry; the ${ROLE_LABEL[seat]} approves.`}
            </span>
          )}
        </div>
      </dl>}
      <footer className="flex flex-wrap items-center justify-between gap-3 border-t border-cloud-100 px-5 py-3 text-[12.5px] text-slate-500">
        <span className="inline-flex flex-wrap items-center gap-x-3 gap-y-1">
          <span>
            Event {longDate(entry.event_date)}
            {dense ? ` · period ${periodLabel(entry.period)}` : ""} · prepared by <span className="font-mono">{entry.preparer}</span>
          </span>
          <Link to={`/trace?target=${encodeURIComponent(entry.id)}`} className="font-medium text-metar-ink hover:underline">
            Why? Blame {entry.id}
          </Link>
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
