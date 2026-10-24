import { motion, useReducedMotion } from "motion/react";
import type { Rule, RuleStatus } from "@/api/types";
import { StatusChip, type Tone } from "@/components/chips";
import { RuleSentence, ruleRef } from "@/components/rule-sentence";
import { Popover, PopoverContent, PopoverTrigger } from "@/components/ui/popover";
import { cn } from "@/lib/utils";
import { parseSupport, stamp } from "./model";

// ---------- status ----------
const STATUS: Record<RuleStatus, { tone: Tone; hint: string }> = {
  proposed: { tone: "outline", hint: "Drafted and replayed; waiting for confirmation" },
  shadow: { tone: "outline", hint: "Runs beside the engine and records what it would change; applies nothing yet" },
  active: { tone: "slate", hint: "Applied to decisions" },
  suspect: { tone: "held", hint: "Flagged by a replay or a challenge; held for review" },
  retired: { tone: "outline", hint: "Superseded or reverted; kept for replay" },
};

/** `shadow` → `active` → `suspect` / `retired`, mono kebab-case. */
export function RuleStatusChip({ status, className }: { status: RuleStatus; className?: string }) {
  const s = STATUS[status] ?? STATUS.proposed;
  return (
    <StatusChip
      tone={s.tone}
      dot={status === "suspect"}
      title={s.hint}
      className={cn(status === "shadow" && "shadow-none outline-1 -outline-offset-1 outline-dashed outline-cloud-400", status === "retired" && "text-slate-400 line-through", className)}
    >
      {status === "active" ? <span className="size-1.5 shrink-0 rounded-full bg-navy-900" aria-hidden="true" /> : null}
      {status}
    </StatusChip>
  );
}

export function StatusLifecycle({ className }: { className?: string }) {
  return (
    <div className={cn("flex flex-wrap items-center gap-1.5 font-mono text-[11px] text-slate-400", className)} aria-label="Rule lifecycle: shadow, then active, then suspect or retired">
      <RuleStatusChip status="shadow" />
      <span aria-hidden="true">→</span>
      <RuleStatusChip status="active" />
      <span aria-hidden="true">→</span>
      <RuleStatusChip status="suspect" />
      <span aria-hidden="true">/</span>
      <RuleStatusChip status="retired" />
    </div>
  );
}

// ---------- mined support ----------
/**
 * "41 of 42": one tick per past decision, filled where the mined policy was applied. The count is the
 * API's `support`; the ticks only draw it.
 */
export function SupportTicks({ support, className }: { support: string | null | undefined; className?: string }) {
  const reduce = useReducedMotion();
  const parsed = parseSupport(support);
  if (!support) return null;
  if (!parsed) return <p className={cn("font-mono text-[12.5px] text-slate-600", className)}>support {support}</p>;
  const { hits, of } = parsed;
  const ticks = of <= 96;
  return (
    <figure className={cn("min-w-0", className)}>
      {ticks ? (
        <div className="flex flex-wrap gap-[3px]" role="img" aria-label={`${hits} of ${of} past decisions`}>
          {Array.from({ length: of }, (_, i) => (
            <motion.span
              key={i}
              initial={reduce ? false : { scaleY: 0.2, opacity: 0 }}
              animate={{ scaleY: 1, opacity: 1 }}
              transition={{ delay: 0.15 + i * 0.012, duration: 0.3, ease: [0.16, 1, 0.3, 1] }}
              className={cn("h-4 w-[4px] origin-bottom rounded-[1px]", i < hits ? "bg-navy-800" : "bg-transparent shadow-[inset_0_0_0_1px_var(--color-cloud-400)]")}
            />
          ))}
        </div>
      ) : (
        <div className="h-2 w-full max-w-[320px] overflow-hidden rounded-full bg-cloud-200" role="img" aria-label={`${hits} of ${of} past decisions`}>
          <div className="h-full rounded-full bg-navy-800" style={{ width: `${(hits / of) * 100}%` }} />
        </div>
      )}
      <figcaption className="mt-2 text-[13px] text-slate-500">
        <span className="figure font-semibold text-navy-900">{support}</span> past decisions agreed
      </figcaption>
    </figure>
  );
}

// ---------- versions ----------
/** v1 → v2, each version openable: its sentence, status and when it was recorded. */
export function VersionTrail({ versions, current }: { versions: Rule[]; current: Rule }) {
  return (
    <ol className="flex flex-wrap items-center gap-1" aria-label="Versions">
      {versions.map((v, i) => {
        const isCurrent = v.version === current.version;
        return (
          <li key={v.version} className="flex items-center gap-1">
            {i > 0 ? (
              <span className="text-[11px] text-slate-400" aria-hidden="true">
                →
              </span>
            ) : null}
            <Popover>
              <PopoverTrigger
                className={cn(
                  "inline-flex h-6 items-center rounded-md px-1.5 font-mono text-[11.5px] transition-colors",
                  isCurrent ? "bg-navy-900 text-cloud-50" : "text-slate-500 shadow-[inset_0_0_0_1px_var(--color-cloud-300)] hover:bg-cloud-50",
                  v.status === "retired" && !isCurrent && "line-through decoration-slate-400",
                )}
                aria-label={`${ruleRef(v)}, ${v.status}${isCurrent ? ", in force" : ""}`}
              >
                v{v.version}
              </PopoverTrigger>
              <PopoverContent align="start" className="w-[min(420px,calc(100vw-2rem))] p-4">
                <div className="flex items-center justify-between gap-3">
                  <span className="font-mono text-[12px] text-slate-500">{ruleRef(v)}</span>
                  <RuleStatusChip status={v.status} />
                </div>
                <RuleSentence rule={v} className="mt-2 text-[13.5px]" />
                <p className="figure mt-3 text-[12px] text-slate-400">
                  recorded {stamp(v.recorded_at)}
                  {v.supersedes ? ` · supersedes ${v.supersedes}` : ""}
                </p>
              </PopoverContent>
            </Popover>
          </li>
        );
      })}
    </ol>
  );
}
