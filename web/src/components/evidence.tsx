import { Fragment } from "react";
import { Check, Minus, X } from "lucide-react";
import type { Evidence } from "@/api/types";
import { eur, zulu } from "@/lib/format";
import { cn } from "@/lib/utils";
import { Details } from "./kit";

/** Trust tiers (CONTRACTS Source.trust_tier). Lower number wins. */
export const TIER_NAME: Record<number, string> = {
  1: "tech log · METAR · MCC",
  2: "schedule · manifest · PSS · BSP",
  3: "OCC batch code · CRM",
  4: "passenger · agency · challenge",
};

/** Source kinds in plain words, matched against the source id ("SRC-TECHLOG-EI-NSB-…", "src:tech_log:…", "SRC-METAR-EIDW@…"). */
const SOURCE_NAME: [RegExp, string][] = [
  [/tech_?log/, "Tech log"],
  [/mcc/, "Maintenance control (MCC)"],
  [/occ/, "Ops control (OCC) batch code"],
  [/metar/, "METAR weather report"],
  [/spares/, "Spare aircraft log"],
  [/manifest/, "Passenger manifest"],
  [/schedule/, "Schedule"],
  [/pss/, "Reservations (PSS)"],
  [/bsp/, "Ticket settlement (BSP)"],
  [/crm/, "CRM"],
  [/claim/, "Passenger claim"],
  [/email/, "Email"],
  [/regulation/, "Regulation"],
  [/ruling/, "Ruling"],
  [/manufacturer/, "Manufacturer notice"],
  [/challenge/, "Challenge"],
  [/event|entso|grid/, "Grid operator notice"],
];

/** Name the source's kind from its id, for the label; never used for logic. */
export function sourceKind(sourceId: string): string {
  const s = sourceId.toLowerCase();
  return SOURCE_NAME.find(([re]) => re.test(s))?.[1] ?? sourceId.split(":")[0] ?? sourceId;
}

const MACHINE = /tech log|mcc|occ|metar|spare|bsp/i;

/** "voucher.signed" → "Signed", for a value shown without a quote. */
const fieldName = (field: string) => {
  const last = (field.split(".").pop() ?? field).replace(/_cents$/, "").replace(/_/g, " ");
  return last.charAt(0).toUpperCase() + last.slice(1);
};

/** A value with no verbatim quote, in words: "Signed: no", "Amount: €300", a window as its times. */
function display(value: unknown, field: string) {
  if (value === null || value === undefined) return "—";
  if (typeof value === "string") return value;
  if (typeof value === "boolean") return `${fieldName(field)}: ${value ? "yes" : "no"}`;
  if (typeof value === "number") return field.endsWith("_cents") ? `${fieldName(field)}: ${eur(value)}` : `${fieldName(field)}: ${value}`;
  // A computed window: "02:30Z–15:00Z · peak gust 56 kt".
  const w = value as { start?: unknown; end?: unknown; peak_gust_kt?: unknown };
  if (typeof w.start === "string" && typeof w.end === "string") return `${zulu(w.start)}–${zulu(w.end)}${typeof w.peak_gust_kt === "number" && w.peak_gust_kt > 0 ? ` · peak gust ${w.peak_gust_kt} kt` : ""}`;
  return JSON.stringify(value);
}

const ROLE_WORD: Record<Evidence["role"], string> = { supports: "supports", contradicts: "contradicts", context: "context" };

const MASK = /\[redacted\]/gi;

/** Text with the server's PII masks shown as a quiet mark instead of a raw "[redacted]". */
export function MaskedText({ text }: { text: string }) {
  const parts = text.split(MASK);
  if (parts.length === 1) return <>{text}</>;
  return (
    <>
      {parts.map((part, i) => (
        <Fragment key={i}>
          {part}
          {i < parts.length - 1 ? (
            <span className="mx-0.5 inline-flex h-[1.35em] items-center rounded bg-cloud-100 px-1.5 align-baseline font-mono text-[10.5px] font-normal not-italic text-slate-500 no-underline" title="Personal data, hidden for this role">
              hidden
            </span>
          ) : null}
        </Fragment>
      ))}
    </>
  );
}

/**
 * Evidence ranked by trust tier, verbatim quotes, the losing source struck through (Flight File, Questions).
 * With `foldContext`, rows that are only context fold behind "Details", so the rows that decide lead.
 */
export function EvidenceList({ evidence, className, compact, foldContext }: { evidence: Evidence[]; className?: string; compact?: boolean; foldContext?: boolean }) {
  const ranked = [...evidence].sort((a, b) => a.trust_tier - b.trust_tier || Number(a.struck ?? false) - Number(b.struck ?? false));
  const lead = foldContext ? ranked.filter((e) => e.role !== "context" || e.struck) : ranked;
  const context = foldContext ? ranked.filter((e) => !lead.includes(e)) : [];
  const rows = (list: Evidence[]) => list.map((e, i) => <EvidenceRow key={`${e.fact_id}-${i}`} e={e} compact={compact} />);
  return (
    <>
      <ol className={cn("flex flex-col", className)}>{rows(lead.length ? lead : context)}</ol>
      {lead.length && context.length ? (
        <Details summary={`${context.length} more for context`} className="mt-1 border-t border-cloud-100 pt-2.5">
          <ol className="flex flex-col">{rows(context)}</ol>
        </Details>
      ) : null}
    </>
  );
}

function EvidenceRow({ e, compact }: { e: Evidence; compact?: boolean }) {
  const kind = sourceKind(e.source_id);
  const machine = MACHINE.test(kind);
  const RoleIcon = e.role === "supports" ? Check : e.role === "contradicts" ? X : Minus;
  return (
    <li className={cn("grid grid-cols-[44px_minmax(0,1fr)] gap-3 border-t border-cloud-100 py-3 first:border-t-0", compact && "py-2")}>
      <div className="flex flex-col items-start gap-1 pt-0.5">
        <span className={cn("inline-flex h-5 items-center rounded px-1.5 font-mono text-[10px] font-bold", e.trust_tier === 1 ? "bg-navy-900 text-cloud-50" : "bg-cloud-100 text-slate-600")} title={`Trust tier ${e.trust_tier}: ${TIER_NAME[e.trust_tier] ?? ""}`}>
          T{e.trust_tier}
        </span>
      </div>
      <div className="min-w-0">
        <div className="flex flex-wrap items-center gap-x-2 gap-y-1 text-[12px] text-slate-500" title={`${e.source_id} · ${e.field}`}>
          <span className="font-medium text-slate-600">{kind}</span>
          <span className={cn("inline-flex items-center gap-1", e.role === "contradicts" ? "text-slate-600" : "text-slate-500")}>
            <RoleIcon className="size-3" aria-hidden="true" />
            {ROLE_WORD[e.role]}
          </span>
          {e.struck ? <span className="micro text-slate-400">outranked · not used</span> : null}
        </div>
        <div
          className={cn(
            "mt-1 break-words",
            machine ? "font-mono text-[12.5px] leading-relaxed" : "text-[14px] leading-relaxed",
            e.struck ? "text-slate-400 line-through decoration-slate-400" : "text-navy-900",
          )}
        >
          {e.quote ? <MaskedText text={e.quote} /> : display(e.value, e.field)}
        </div>
      </div>
    </li>
  );
}
