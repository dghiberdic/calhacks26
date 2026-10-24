"use client";

import { useCallback, useEffect, useState } from "react";
import { AnimatePresence, motion } from "motion/react";
import { useDialog } from "@/lib/useDialog";
import { useApp } from "@/lib/store";
import { NS31, FLIGHTS, STORM, tier } from "@/data/scenario";
import { receiptHref } from "@/data/app";
import { Money } from "./ui";
import { cn } from "@/lib/cn";

type Step = { label: string; value: React.ReactNode; note?: React.ReactNode; tone?: "owed" | "weather"; mono?: boolean };

/** "Why this €?" — a receipt that walks an amount back to the evidence (Trace Precedents for CFOs). */
export function WhyDrawer() {
  const { why, openWhy } = useApp();
  const close = useCallback(() => openWhy(null), [openWhy]);
  const dialogRef = useDialog<HTMLElement>(!!why, close);
  const [copied, setCopied] = useState<"idle" | "done" | "failed">("idle");
  useEffect(() => {
    if (copied === "idle") return;
    const t = window.setTimeout(() => setCopied("idle"), 2200);
    return () => window.clearTimeout(t);
  }, [copied]);
  const copyLink = () => {
    if (!why) return;
    const url = receiptHref(location.origin, why);
    if (!navigator.clipboard) return setCopied("failed");
    navigator.clipboard.writeText(url).then(
      () => setCopied("done"),
      () => setCopied("failed"),
    );
  };
  const f = FLIGHTS.find((x) => x.id === why?.flight) ?? NS31.flight;
  const per = tier(f.km);

  const steps: Step[] = why
    ? [
        ...(why.kind === "provision"
          ? [
              { label: "Provision", value: <Money value={NS31.provision} />, note: "EU261 claims provision for NS31, drafted 09:00Z.", tone: "owed" as const },
              { label: "Exposure × claim rate", value: <span className="figure">€127,200 × 35%</span>, note: "Claim rate learned from 18 storms and two years of claims (R-6 v4)." },
            ]
          : [{ label: "Payout", value: <Money value={why.amount} />, note: `${why.passenger ?? "Passenger"} on ${f.id}.`, tone: "owed" as const }]),
        { label: "Passengers × tier", value: <span className="figure">{f.pax} × €{per}</span>, note: `Dublin to ${f.city} is ${f.km.toLocaleString("en-IE")} km. Art. 7(1) tier (R-4 v1).` },
        { label: "Cause", value: "Technical fault", note: "Not an extraordinary circumstance: CJEU C-549/07 Wallentin-Hermann (R-3 v2)." },
        { label: "Tech log", value: <span className="font-mono">07:55Z · ATA 29-11</span>, note: <span className="font-mono text-[12.5px]">{NS31.techLog.entry}</span>, mono: true },
        { label: "Weather", value: <span className="font-mono">{STORM.windowStart}–{STORM.windowEnd}Z</span>, note: `Storm window from METAR, gusts at or above ${STORM.limitKt} kt. NS31 was due at 21:30, after it.`, tone: "weather" as const },
        { label: "Who ruled", value: "Legal, 12 Mar 2025", note: "Asked once in R-3’s history. Applied 14 times since." },
      ]
    : [];

  return (
    <AnimatePresence>
      {why && (
        <>
          <motion.div key="w-scrim" className="fixed inset-0 z-[60] bg-ink/20" initial={{ opacity: 0 }} animate={{ opacity: 1 }} exit={{ opacity: 0 }} onClick={() => openWhy(null)} />
          <motion.aside
            key="w"
            ref={dialogRef}
            tabIndex={-1}
            role="dialog"
            aria-modal="true"
            aria-label="Why this amount"
            initial={{ y: 30, opacity: 0 }}
            animate={{ y: 0, opacity: 1 }}
            exit={{ y: 20, opacity: 0 }}
            transition={{ type: "spring", stiffness: 360, damping: 34 }}
            className="fixed inset-x-3 bottom-3 z-[60] mx-auto max-h-[86svh] max-w-[560px] overflow-y-auto rounded-2xl bg-paper shadow-[0_0_0_1px_#e6e6e0,0_30px_80px_rgba(18,20,23,0.25)] md:bottom-auto md:top-[8svh]"
            data-lenis-prevent
          >
            <header className="flex items-center justify-between px-6 pt-5">
              <h2 className="text-[15px] font-semibold">Why this €?</h2>
              <button type="button" onClick={() => openWhy(null)} className="rounded-lg px-2 py-1 text-[13px] text-graphite hover:bg-fog">
                Close
              </button>
            </header>
            <ol className="relative px-6 pb-6 pt-4">
              <span className="absolute bottom-10 left-[31px] top-8 w-px bg-ink/80" aria-hidden="true" />
              {steps.map((s, i) => (
                <motion.li
                  key={i}
                  initial={{ opacity: 0, x: -8 }}
                  animate={{ opacity: 1, x: 0 }}
                  transition={{ delay: 0.06 * i + 0.1, duration: 0.35, ease: [0.16, 1, 0.3, 1] }}
                  className="relative grid grid-cols-[16px_1fr] gap-x-4 pb-5 last:pb-0"
                >
                  <span className={cn("relative z-10 mt-1.5 h-[13px] w-[13px] rounded-full border-2 bg-paper", s.tone === "owed" ? "border-owed bg-owed" : s.tone === "weather" ? "border-weather" : "border-ink")} />
                  <div>
                    <div className="flex items-baseline justify-between gap-4">
                      <span className="text-[13px] text-graphite">{s.label}</span>
                      <span className={cn("text-right text-[16px] font-medium", s.tone === "owed" && "text-owed-ink", s.tone === "weather" && "text-weather-ink")}>{s.value}</span>
                    </div>
                    {s.note && <p className="mt-1 text-[13.5px] leading-relaxed text-ink/80">{s.note}</p>}
                  </div>
                </motion.li>
              ))}
            </ol>
            <footer className="flex items-center justify-between gap-3 border-t border-[#ecece7] px-6 py-4">
              <p className="font-mono text-[12px] text-graphite">JE-2041 · decision d-7f3a19</p>
              <button type="button" className="min-w-[180px] rounded-lg bg-ink px-3.5 py-2 text-[13px] font-medium text-chart" onClick={copyLink} aria-live="polite">
                {copied === "done" ? "Link copied" : copied === "failed" ? "Couldn’t copy. Try again" : "Copy link for the auditor"}
              </button>
            </footer>
          </motion.aside>
        </>
      )}
    </AnimatePresence>
  );
}
