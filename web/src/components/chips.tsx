import type { ReactNode } from "react";
import type { TraceChip as TraceChipKind } from "@/api/types";
import { cn } from "@/lib/utils";

/**
 * Tones carry meaning and nothing else (THREAD_JUSTIN "Visual language"):
 * weather grey · notweather red (only "Not weather") · held amber · metar cool blue ·
 * tie green (only ties to GL / invariant ok) · slate for everything neutral · ink for denials.
 */
export type Tone = "weather" | "notweather" | "held" | "metar" | "tie" | "slate" | "ink" | "outline";

const TONE: Record<Tone, string> = {
  weather: "bg-weather-wash text-weather-ink",
  notweather: "bg-notweather-wash text-notweather-ink",
  held: "bg-held-wash text-held-ink",
  metar: "bg-metar-wash text-metar-ink",
  tie: "bg-tie-wash text-tie-ink",
  slate: "bg-cloud-100 text-slate-600",
  ink: "bg-navy-900 text-cloud-50",
  outline: "bg-transparent text-slate-600 shadow-[inset_0_0_0_1px_var(--color-cloud-300)]",
};

const DOT: Partial<Record<Tone, string>> = {
  weather: "bg-weather",
  notweather: "bg-notweather",
  held: "bg-held",
  metar: "bg-metar",
  tie: "bg-tie",
};

/** Mono kebab-case status chip: `weather · no-compensation`, `technical · owed`, `needs-ruling`, `shadow`, `locked`. */
export function StatusChip({ tone = "slate", dot = true, children, className, title }: { tone?: Tone; dot?: boolean; children: ReactNode; className?: string; title?: string }) {
  return (
    <span title={title} className={cn("inline-flex h-6 items-center gap-1.5 whitespace-nowrap rounded-md px-2 font-mono text-[11.5px] leading-none", TONE[tone], className)}>
      {dot && DOT[tone] && <span className={cn("size-1.5 shrink-0 rounded-full", DOT[tone])} aria-hidden="true" />}
      {children}
    </span>
  );
}

const CHIP_TONE: Record<TraceChipKind, Tone> = {
  APPLIED: "slate",
  DRAFTED: "metar",
  HELD: "held",
  ASKED: "held",
  DENIED: "ink",
  RULED: "ink",
  LEARNED: "outline",
  CITED: "outline",
  LOCKED: "slate",
  INFO: "outline",
};

/** Feed chip: `APPLIED`, `DRAFTED`, `HELD`, `DENIED`, ... */
export function TraceChip({ chip, className }: { chip: TraceChipKind; className?: string }) {
  return (
    <span className={cn("inline-flex h-5 items-center rounded px-1.5 font-mono text-[10px] font-bold uppercase tracking-[0.06em]", TONE[CHIP_TONE[chip]], className)}>
      {chip}
    </span>
  );
}

/** Micro-label: "NOT YET POSTED · BUILT FROM 3 SOURCES", "TIES TO GL 2140". */
export function MicroLabel({ children, tone = "slate", className }: { children: ReactNode; tone?: "slate" | "tie" | "held" | "metar" | "light"; className?: string }) {
  const color = { slate: "text-slate-500", tie: "text-tie-ink", held: "text-held-ink", metar: "text-metar-ink", light: "text-cloud-400" }[tone];
  return <span className={cn("micro", color, className)}>{children}</span>;
}

/** "TIES TO GL 2140" with the one green the palette allows. */
export function TiesChip({ account = "2140", ok = true }: { account?: string; ok?: boolean }) {
  return ok ? (
    <StatusChip tone="tie" className="font-bold uppercase tracking-[0.06em] text-[10.5px]">
      ties to GL {account}
    </StatusChip>
  ) : (
    <StatusChip tone="held" className="font-bold uppercase tracking-[0.06em] text-[10.5px]">
      doesn't tie to GL {account}
    </StatusChip>
  );
}
