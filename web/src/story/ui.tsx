import { Component, type ReactNode } from "react";
import type { Cents } from "@/api/types";
import { count, eur } from "@/lib/format";
import { cn } from "@/lib/utils";

/** A quiet placeholder the width of the value it stands in for, while the API answers. */
export function Pending({ ch = 4, className, tone = "dark" }: { ch?: number; className?: string; tone?: "dark" | "light" }) {
  return (
    <span
      aria-hidden="true"
      className={cn("inline-block h-[0.72em] translate-y-[0.06em] animate-pulse rounded-[0.18em] align-baseline", tone === "dark" ? "bg-white/12" : "bg-navy-900/10", className)}
      style={{ width: `${ch}ch` }}
    />
  );
}

/** Integer cents as euros (lib/format), or a placeholder until they arrive. */
export function Euros({ cents, ch = 6, tone, className }: { cents: Cents | null | undefined; ch?: number; tone?: "dark" | "light"; className?: string }) {
  if (cents === null || cents === undefined) return <Pending ch={ch} tone={tone} className={className} />;
  return <span className={cn("figure whitespace-nowrap", className)}>{eur(cents)}</span>;
}

/** A count (5,292), or a placeholder. */
export function Count({ n, ch = 3, tone, className }: { n: number | null | undefined; ch?: number; tone?: "dark" | "light"; className?: string }) {
  if (n === null || n === undefined) return <Pending ch={ch} tone={tone} className={className} />;
  return <span className={cn("figure", className)}>{count(n)}</span>;
}

/**
 * Contains a failure to one part of the story: if the 3D model can't load (a flaky venue network, a
 * GPU that drops its context) that beat carries on with `fallback` and the rest of the page is untouched.
 */
export class Contained extends Component<{ fallback: ReactNode; children: ReactNode }, { failed: boolean }> {
  state = { failed: false };

  static getDerivedStateFromError() {
    return { failed: true };
  }

  componentDidCatch(error: unknown) {
    console.warn("StormCheck story: a section fell back after an error", error);
  }

  render() {
    return this.state.failed ? this.props.fallback : this.props.children;
  }
}
