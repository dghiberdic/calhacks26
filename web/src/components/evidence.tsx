import { Fragment } from "react";
import { Check, Minus, X } from "lucide-react";
import type { Evidence } from "@/api/types";
import { cn } from "@/lib/utils";

/** Trust tiers (CONTRACTS Source.trust_tier). Lower number wins. */
export const TIER_NAME: Record<number, string> = {
  1: "tech log · METAR · MCC",
  2: "schedule · manifest · PSS · BSP",
  3: "OCC batch code · CRM",
  4: "passenger · agency · challenge",
};

/** Guess the source's kind from its id ("src:tech_log:…", "metar:EIDW@…") for the label; never used for logic. */
export function sourceKind(sourceId: string): string {
  const s = sourceId.toLowerCase();
  for (const k of ["tech_log", "mcc_log", "occ_log", "metar", "spares", "manifest", "schedule", "pss", "bsp", "crm", "claim", "email", "regulation", "ruling", "manufacturer", "challenge"]) {
    if (s.includes(k)) return k.replace("_log", " log").replace("_", " ");
  }
  return sourceId.split(":")[0] ?? sourceId;
}

const MACHINE = /tech log|mcc|occ|metar|spares|bsp/;

function display(value: unknown) {
  if (value === null || value === undefined) return "—";
  if (typeof value === "string") return value;
  if (typeof value === "number" || typeof value === "boolean") return String(value);
  return JSON.stringify(value);
}

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

/** Evidence ranked by trust tier, verbatim quotes, the losing source struck through (Flight File, Questions). */
export function EvidenceList({ evidence, className, compact }: { evidence: Evidence[]; className?: string; compact?: boolean }) {
  const ranked = [...evidence].sort((a, b) => a.trust_tier - b.trust_tier || Number(a.struck ?? false) - Number(b.struck ?? false));
  return (
    <ol className={cn("flex flex-col", className)}>
      {ranked.map((e, i) => {
        const kind = sourceKind(e.source_id);
        const machine = MACHINE.test(kind);
        const RoleIcon = e.role === "supports" ? Check : e.role === "contradicts" ? X : Minus;
        return (
          <li key={`${e.fact_id}-${i}`} className={cn("grid grid-cols-[44px_minmax(0,1fr)] gap-3 border-t border-cloud-100 py-3 first:border-t-0", compact && "py-2")}>
            <div className="flex flex-col items-start gap-1 pt-0.5">
              <span className={cn("inline-flex h-5 items-center rounded px-1.5 font-mono text-[10px] font-bold", e.trust_tier === 1 ? "bg-navy-900 text-cloud-50" : "bg-cloud-100 text-slate-600")} title={TIER_NAME[e.trust_tier]}>
                T{e.trust_tier}
              </span>
            </div>
            <div className="min-w-0">
              <div className="flex flex-wrap items-center gap-x-2 gap-y-1 text-[12px] text-slate-500">
                <span className="font-medium capitalize text-slate-600">{kind}</span>
                <span className="font-mono text-[11px] text-slate-400">{e.field}</span>
                <span className={cn("inline-flex items-center gap-1", e.role === "contradicts" ? "text-slate-600" : "text-slate-500")}>
                  <RoleIcon className="size-3" aria-hidden="true" />
                  {e.role}
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
                {e.quote ? <MaskedText text={e.quote} /> : display(e.value)}
              </div>
            </div>
          </li>
        );
      })}
    </ol>
  );
}
