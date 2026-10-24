"use client";

import { useEffect, useState } from "react";
import { AnimatePresence, motion } from "motion/react";
import { useDialog } from "@/lib/useDialog";
import { FLIGHTS, METAR, NS31, STORM, totals } from "@/data/scenario";
import { cn } from "@/lib/cn";

type Step = { title: string; detail: string; lines: string[]; ms: number; tone?: "owed" | "review" };

const t = totals();
const STEPS: Step[] = [
  {
    title: `Pulled ${METAR.length} METAR reports for ${STORM.station}`,
    detail: `Gusts at or above ${STORM.limitKt} kt from ${STORM.windowStart} to ${STORM.windowEnd}Z. Peak ${STORM.peak.gust} kt at ${STORM.peak.t}Z.`,
    lines: [METAR.find((m) => m.t === "13:30")?.raw ?? "", METAR.find((m) => m.t === STORM.peak.t)?.raw ?? "", METAR.find((m) => m.t === "19:00")?.raw ?? ""],
    ms: 1400,
  },
  {
    title: `Read ${t.cancelled} cancellations from Ops`,
    detail: "Every one coded 71, weather.",
    lines: FLIGHTS.slice(0, 4).map((f) => `${f.sched}Z ${f.id.padEnd(6)} DUB-${f.dest} CNL 71 WX`),
    ms: 1100,
  },
  {
    title: `Read ${t.cancelled} aircraft tech logs`,
    detail: `One open item before the storm: ${NS31.flight.reg}, ATA ${NS31.techLog.ata}, ${NS31.techLog.time}Z.`,
    lines: [`${NS31.techLog.time}Z ${NS31.flight.reg} ${NS31.techLog.entry}`],
    ms: 1200,
    tone: "owed",
  },
  {
    title: "Set each flight’s real cause",
    detail: `${t.weather} weather, 1 technical fault (NS31, 91%). Rules R-1 v2, R-2 v1, R-3 v2.`,
    lines: [`NS31 cause 71 WX → 41 TECH  conf 0.91  runner-up WX 0.09`, `NS81 cause 71 WX → 71 WX    conf 0.90`],
    ms: 1300,
    tone: "owed",
  },
  {
    title: "Drafted payouts and the provision",
    detail: `${NS31.flight.pax} × €600 = €127,200 exposure. Provision €44,520 at the learned 35% claim rate.`,
    lines: ["JE-2041 Dr 6410 Passenger compensation 44,520.00", "        Cr 2350 EU261 claims provision    44,520.00"],
    ms: 1300,
  },
  {
    title: "Asked one question",
    detail: "Claims Lead: offset a gate voucher? 39%, sources disagree. €600 held.",
    lines: ["Q-12 → claims-lead  reason: sources disagree  held €600"],
    ms: 900,
    tone: "review",
  },
];

/** The 09:00Z morning re-check, replayed step by step. */
export function AgentRun({ open, onClose }: { open: boolean; onClose: () => void }) {
  const [done, setDone] = useState(0);
  const dialogRef = useDialog<HTMLElement>(open, onClose);

  useEffect(() => {
    if (!open) return;
    // eslint-disable-next-line react-hooks/set-state-in-effect -- restart the replay each time it opens
    setDone(0);
    let i = 0;
    let timer = 0;
    const next = () => {
      i += 1;
      setDone(i);
      if (i < STEPS.length) timer = window.setTimeout(next, STEPS[i].ms);
    };
    timer = window.setTimeout(next, STEPS[0].ms);
    return () => {
      window.clearTimeout(timer);
    };
  }, [open]);

  return (
    <AnimatePresence>
      {open && (
        <>
          <motion.div key="ar-s" className="fixed inset-0 z-[60] bg-ink/25" initial={{ opacity: 0 }} animate={{ opacity: 1 }} exit={{ opacity: 0 }} onClick={onClose} />
          <motion.section
            key="ar"
            ref={dialogRef}
            tabIndex={-1}
            role="dialog"
            aria-modal="true"
            aria-label="The 09:00Z re-check"
            initial={{ opacity: 0, y: 16, scale: 0.98 }}
            animate={{ opacity: 1, y: 0, scale: 1 }}
            exit={{ opacity: 0, y: 10 }}
            transition={{ type: "spring", stiffness: 340, damping: 32 }}
            className="fixed inset-x-3 top-[7svh] z-[60] mx-auto max-h-[86svh] max-w-[720px] overflow-y-auto rounded-2xl bg-[#0d1117] text-[#eef1f4] shadow-[0_30px_90px_rgba(0,0,0,0.45)]"
            data-lenis-prevent
          >
            <header className="flex items-center justify-between px-6 pt-5">
              <div>
                <h2 className="text-[16px] font-semibold">The 09:00Z re-check, 10 Dec</h2>
                <p className="text-[13px] text-mist">What StormCheck did before anyone was in the office.</p>
              </div>
              <button type="button" onClick={onClose} className="rounded-lg px-2.5 py-1.5 text-[13px] text-mist hover:bg-white/10">
                Close
              </button>
            </header>
            <ol className="px-6 pb-6 pt-4">
              {STEPS.map((s, i) => {
                const state = i < done ? "done" : i === done ? "running" : "waiting";
                return (
                  <li key={s.title} className={cn("grid grid-cols-[22px_1fr] gap-x-4 pb-5 transition-opacity duration-500 last:pb-0", state === "waiting" && "opacity-30")}>
                    <span className="mt-[3px] flex h-[18px] w-[18px] items-center justify-center">
                      {state === "done" ? (
                        <svg width="18" height="18" viewBox="0 0 18 18" aria-hidden="true">
                          <circle cx="9" cy="9" r="8" fill={s.tone === "owed" ? "#e04a2f" : s.tone === "review" ? "#e89a00" : "#2f7d5b"} />
                          <path d="M5 9.4 L7.8 12 L13 6.5" fill="none" stroke="white" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round" className="ink-path" pathLength={1} />
                        </svg>
                      ) : state === "running" ? (
                        <span className="h-3.5 w-3.5 animate-spin rounded-full border-2 border-white/25 border-t-white" />
                      ) : (
                        <span className="h-2 w-2 rounded-full bg-white/30" />
                      )}
                    </span>
                    <div>
                      <p className="text-[15px] font-medium">{s.title}</p>
                      {state !== "waiting" && <p className="mt-0.5 text-[13.5px] text-haze">{s.detail}</p>}
                      {state === "done" && (
                        <motion.pre initial={{ opacity: 0, height: 0 }} animate={{ opacity: 1, height: "auto" }} transition={{ duration: 0.35 }} className="mt-2 overflow-x-auto whitespace-pre rounded-lg bg-white/5 p-3 font-mono text-[11.5px] leading-relaxed text-[#cfd8e2]">
                          {s.lines.join("\n")}
                        </motion.pre>
                      )}
                    </div>
                  </li>
                );
              })}
            </ol>
            <footer className="flex items-center justify-between border-t border-white/10 px-6 py-4 text-[13px] text-mist">
              <span>{done >= STEPS.length ? "Finished 09:00:41Z. 2,910 passengers sorted." : "Running…"}</span>
              <span className="font-mono">run r-0910-0900</span>
            </footer>
          </motion.section>
        </>
      )}
    </AnimatePresence>
  );
}
