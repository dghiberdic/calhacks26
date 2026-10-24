"use client";

import { useEffect, useState } from "react";
import { useRouter, useSearchParams } from "next/navigation";
import { AnimatePresence, motion } from "motion/react";
import { useApp } from "@/lib/store";
import { NS31 } from "@/data/scenario";
import { cn } from "@/lib/cn";

type Step = { title: string; say: string; go: () => void };

/**
 * Presenter's crib sheet for the judging table. Press G (or open /app?demo) to toggle.
 * Each step performs its own action so nobody hunts for buttons mid-pitch.
 */
export function DemoGuide() {
  const router = useRouter();
  const params = useSearchParams();
  const { openSheet, openWhy, setRun, setRole } = useApp();
  const [open, setOpen] = useState(false);
  const [done, setDone] = useState<number[]>([]);

  useEffect(() => {
    // eslint-disable-next-line react-hooks/set-state-in-effect -- ?demo opens the guide once on arrival
    if (params.has("demo")) setOpen(true);
  }, [params]);

  useEffect(() => {
    const on = (e: KeyboardEvent) => {
      const tag = (e.target as HTMLElement)?.tagName;
      if (tag === "INPUT" || tag === "TEXTAREA" || e.metaKey || e.ctrlKey) return;
      if (e.key.toLowerCase() === "g") setOpen((o) => !o);
    };
    window.addEventListener("keydown", on);
    return () => window.removeEventListener("keydown", on);
  }, []);

  const steps: Step[] = [
    { title: "Overview", say: "14 cancellations, every one coded 71 weather by Ops.", go: () => router.push("/app") },
    { title: "Open NS31", say: "Grounded 07:55 with a hydraulic leak, 5 h 35 min before the storm. 71 → 41.", go: () => (router.push("/app"), openSheet("NS31")) },
    { title: "Why this €?", say: "€44,520 walks back to the log line, the METAR hour, R-3 v2 and Legal.", go: () => openWhy({ kind: "provision", flight: "NS31", amount: NS31.provision }) },
    { title: "The 09:00Z run", say: "What it did before anyone was in: 48 METARs, 14 tech logs, one question.", go: () => (openSheet(null), openWhy(null), setRun(true)) },
    { title: "Rule on the voucher", say: "One question to the Claims Lead. The answer becomes R-7 v1 and settles 31 cases.", go: () => (setRun(false), setRole("claims-lead"), router.push("/app/inbox")) },
    { title: "Replay R-1", say: "Re-run the real METAR at 50 kt: 9 verdicts flip, €1.03M. That's why versions matter.", go: () => router.push("/app/rules#R-1") },
    { title: "Judge’s desk", say: "Pick your own airport and date. Live METAR; edit the tech log and watch the euros.", go: () => router.push("/app/desk") },
  ];

  return (
    <AnimatePresence>
      {open && (
        <motion.aside
          initial={{ opacity: 0, x: -12 }}
          animate={{ opacity: 1, x: 0 }}
          exit={{ opacity: 0, x: -12 }}
          transition={{ duration: 0.25, ease: [0.16, 1, 0.3, 1] }}
          aria-label="Demo guide"
          className="fixed bottom-4 left-4 z-[55] w-[330px] rounded-2xl bg-ink/95 p-4 text-chart shadow-[0_20px_60px_rgba(0,0,0,0.35)] backdrop-blur"
        >
          <div className="mb-3 flex items-center justify-between">
            <p className="text-[14px] font-semibold">Demo path · 3 min</p>
            <button type="button" onClick={() => setOpen(false)} className="rounded-md px-2 py-1 text-[12px] text-mist hover:bg-white/10">
              Hide (G)
            </button>
          </div>
          <ol className="space-y-1.5">
            {steps.map((s, i) => (
              <li key={s.title}>
                <button
                  type="button"
                  onClick={() => {
                    s.go();
                    setDone((d) => (d.includes(i) ? d : [...d, i]));
                  }}
                  className={cn("w-full rounded-lg px-3 py-2 text-left transition-colors hover:bg-white/10", done.includes(i) && "opacity-55")}
                >
                  <span className="flex items-baseline gap-2 text-[13.5px] font-medium">
                    <span className="font-mono text-[12px] text-mist">{i + 1}</span>
                    {s.title}
                  </span>
                  <span className="mt-0.5 block pl-5 text-[12.5px] leading-snug text-haze">{s.say}</span>
                </button>
              </li>
            ))}
          </ol>
        </motion.aside>
      )}
    </AnimatePresence>
  );
}
