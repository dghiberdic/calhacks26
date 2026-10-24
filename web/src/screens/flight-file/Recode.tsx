import { motion, useReducedMotion } from "motion/react";
import { cn } from "@/lib/utils";

/**
 * The recode, "71 → 41": the code OCC typed, struck, and the code the evidence supports.
 * `lg` is the Flight File's departure-board pill; the strike draws once on load.
 */
export function Recode({ from, to, size = "sm", className }: { from: string | null; to: string; size?: "sm" | "lg"; className?: string }) {
  const reduce = useReducedMotion();
  const label = from ? `Recoded from ${from} to ${to}` : `Code ${to}`;

  if (size === "sm") {
    return (
      <span className={cn("inline-flex items-center gap-1 font-mono tabular-nums", className)} aria-label={label}>
        {from ? (
          <>
            <del className="text-slate-400 decoration-slate-500 decoration-[1.5px]" aria-hidden="true">
              {from}
            </del>
            <span className="text-slate-400" aria-hidden="true">
              →
            </span>
          </>
        ) : null}
        <ins className="font-bold text-navy-900 no-underline" aria-hidden="true">
          {to}
        </ins>
      </span>
    );
  }

  return (
    <span
      className={cn("inline-flex h-9 items-center gap-2.5 rounded-lg bg-navy-900 pl-3 pr-3.5 font-mono text-cloud-50 shadow-[0_1px_2px_rgba(13,21,36,0.18)]", className)}
      role="img"
      aria-label={label}
    >
      <span className="text-[10px] tracking-[0.12em] text-cloud-500">RSN</span>
      {from ? (
        <>
          <span className="relative text-[17px] text-cloud-500">
            {from}
            <motion.span
              aria-hidden="true"
              className="absolute inset-x-[-3px] top-1/2 h-[2px] -translate-y-1/2 rounded-full bg-cloud-200"
              style={{ originX: 0 }}
              initial={reduce ? false : { scaleX: 0 }}
              animate={{ scaleX: 1 }}
              transition={{ delay: 0.35, duration: 0.45, ease: [0.16, 1, 0.3, 1] }}
            />
          </span>
          <span className="text-[13px] text-cloud-500">→</span>
        </>
      ) : null}
      <motion.span
        className="text-[17px] font-bold text-white"
        initial={reduce ? false : { opacity: 0, y: 6 }}
        animate={{ opacity: 1, y: 0 }}
        transition={{ delay: 0.7, duration: 0.4, ease: [0.16, 1, 0.3, 1] }}
      >
        {to}
      </motion.span>
    </span>
  );
}
