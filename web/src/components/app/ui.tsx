"use client";

import { cn } from "@/lib/cn";
import type { Verdict } from "@/data/scenario";

const VERDICT: Record<Verdict | "asked" | "drafted" | "settled", { label: string; dot: string; chip: string }> = {
  weather: { label: "Weather", dot: "bg-weather", chip: "bg-weather-wash text-[#3f4955]" },
  technical: { label: "Technical", dot: "bg-owed", chip: "bg-owed-wash text-[#a32e19]" },
  review: { label: "Sources disagree", dot: "bg-review", chip: "bg-review-wash text-[#7a4f00]" },
  operated: { label: "Operated", dot: "bg-settled", chip: "bg-settled-wash text-settled-ink" },
  asked: { label: "Asked", dot: "bg-review", chip: "bg-review-wash text-[#7a4f00]" },
  drafted: { label: "Drafted", dot: "bg-ink", chip: "bg-fog text-ink" },
  settled: { label: "Settled", dot: "bg-settled", chip: "bg-settled-wash text-settled-ink" },
};

export function Chip({ kind, children, className }: { kind: keyof typeof VERDICT; children?: React.ReactNode; className?: string }) {
  const v = VERDICT[kind];
  return (
    <span className={cn("inline-flex items-center gap-1.5 whitespace-nowrap rounded-full px-2.5 py-[3px] text-[13px] font-medium", v.chip, className)}>
      <span className={cn("h-1.5 w-1.5 rounded-full", v.dot)} aria-hidden="true" />
      {children ?? v.label}
    </span>
  );
}

/** Confidence: a word, a bar, the auto-draft threshold tick, and the runner-up share. */
export function Confidence({ value, threshold = 80, tone = "ink", runnerUp }: { value: number; threshold?: number; tone?: "ink" | "owed" | "weather" | "review"; runnerUp?: string }) {
  const word = value >= 90 ? "Sure" : value >= threshold ? "Confident" : value >= 50 ? "Unsure" : "Not sure";
  const fill = { ink: "bg-ink", owed: "bg-owed", weather: "bg-weather", review: "bg-review" }[tone];
  return (
    <div>
      <div className="flex items-baseline justify-between text-[13px]">
        <span className="font-medium">{word}</span>
        <span className="tabular font-mono">{value}%</span>
      </div>
      <div className="relative mt-1.5 h-[6px] overflow-hidden rounded-full bg-fog">
        <span className={cn("absolute inset-y-0 left-0 rounded-full", fill)} style={{ width: `${value}%` }} />
      </div>
      <div className="relative h-0">
        <span className="absolute -top-[10px] h-[14px] w-px bg-graphite/60" style={{ left: `${threshold}%` }} title={`Drafts automatically above ${threshold}%`} />
      </div>
      {runnerUp && <p className="mt-2 text-[12.5px] text-graphite">{runnerUp}</p>}
    </div>
  );
}

export function Kbd({ children }: { children: React.ReactNode }) {
  return <kbd className="rounded-[4px] bg-fog px-1.5 py-[1px] font-mono text-[11px] text-graphite">{children}</kbd>;
}

export function Card({ className, children }: { className?: string; children: React.ReactNode }) {
  return <div className={cn("rounded-xl bg-white shadow-[0_0_0_1px_#e6e6e0]", className)}>{children}</div>;
}

export function Money({ value, className }: { value: number; className?: string }) {
  return <span className={cn("tabular font-mono", className)}>€{Math.round(value).toLocaleString("en-IE")}</span>;
}
