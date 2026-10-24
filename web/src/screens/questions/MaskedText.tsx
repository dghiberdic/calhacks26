import { Fragment } from "react";
import { cn } from "@/lib/utils";
import { MASK_RE } from "./lib";

/**
 * Text as the server sent it for this role. PII the server masked (e.g. for Ops) shows as a quiet
 * "hidden" mark with a tooltip, instead of a run of block characters.
 */
export function MaskedText({ text, className }: { text: string; className?: string }) {
  const parts = text.split(MASK_RE);
  if (parts.length === 1) return <span className={className}>{text}</span>;
  return (
    <span className={className}>
      {parts.map((p, i) =>
        i % 2 === 1 ? (
          <span
            key={i}
            title="Passenger data: visible to the Claims Lead only"
            className={cn("inline-flex h-[1.35em] translate-y-[0.1em] items-center rounded bg-cloud-100 px-1.5 align-baseline font-mono text-[0.72em] uppercase tracking-[0.08em] text-slate-500")}
          >
            hidden
          </span>
        ) : (
          <Fragment key={i}>{p}</Fragment>
        ),
      )}
    </span>
  );
}
