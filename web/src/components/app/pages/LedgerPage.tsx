"use client";

import { useState } from "react";
import { motion, AnimatePresence } from "motion/react";
import { useApp } from "@/lib/store";
import { JOURNAL, type Journal } from "@/data/app";
import { NS31 } from "@/data/scenario";
import { Card, Chip, Money } from "@/components/app/ui";
import { RollingNumber } from "@/components/motion/RollingNumber";
import { ClaimCurve } from "./ClaimCurve";
import { cn } from "@/lib/cn";

const ease = [0.16, 1, 0.3, 1] as const;

function JournalCard({ entry, posted, onWhy }: { entry: Journal; posted: boolean; onWhy?: () => void }) {
  const status = posted ? "posted" : entry.status;
  const sources = entry.source.split(" · ");
  return (
    <motion.div initial={false} animate={{ backgroundColor: posted ? "#f6fbf8" : "#ffffff" }} transition={{ duration: 0.5, ease }}>
      <Card className="p-5">
        <div className="flex flex-wrap items-start justify-between gap-3">
          <div>
            <p className="font-mono text-[13px] text-graphite">
              {entry.id} · {entry.when}
            </p>
            <p className="mt-1 max-w-[56ch] text-[14.5px] leading-snug">{entry.memo}</p>
          </div>
          <div className="flex shrink-0 items-center gap-2">
            {status === "held" && <Chip kind="technical">Held</Chip>}
            {status === "drafted" && <Chip kind="drafted" />}
            {status === "posted" && <Chip kind="settled">Posted</Chip>}
            {onWhy && (
              <button type="button" onClick={onWhy} className="text-[13px] text-front underline-offset-4 hover:underline">
                Why this €?
              </button>
            )}
          </div>
        </div>
        <dl className="mt-4 border-t border-[#f0f0eb]">
          {entry.lines.map((line, i) => (
            <div key={i} className={cn("flex items-baseline justify-between gap-4 border-b border-[#f6f6f2] py-2 font-mono text-[13.5px]", line.cr !== undefined && "pl-6")}>
              <dt className="text-graphite">
                {line.dr !== undefined ? "Dr" : "Cr"} {line.account}
              </dt>
              <dd className="tabular text-right text-ink">
                <Money value={line.dr !== undefined ? line.dr : line.cr ?? 0} />
              </dd>
            </div>
          ))}
        </dl>
        <div className="mt-3 flex flex-wrap items-center gap-2 text-[13px] text-graphite">
          <span>Source</span>
          {sources.map((s) => (
            <span key={s} className="rounded-full bg-fog px-2 py-[2px] font-mono text-[12px] text-graphite">
              {s}
            </span>
          ))}
        </div>
      </Card>
    </motion.div>
  );
}

export function LedgerPage() {
  const { role, openWhy } = useApp();
  const [posted, setPosted] = useState<Set<string>>(new Set());
  const [confirming, setConfirming] = useState(false);
  const canApprove = role === "controller";
  const pendingCount = JOURNAL.filter((j) => !posted.has(j.id)).length;

  const confirmPost = () => {
    setPosted((prev) => {
      const next = new Set(prev);
      JOURNAL.forEach((j) => next.add(j.id));
      return next;
    });
    setConfirming(false);
  };

  return (
    <div className="mx-auto max-w-[1280px]">
      <h1 className="display-tight text-[30px]">Ledger</h1>
      <p className="mt-1 max-w-[62ch] text-[15px] text-graphite">What Storm Bram put on the books. Every line traces to a rule; nothing here moves cash by itself.</p>

      <div className="mt-6 grid grid-cols-1 gap-3 lg:grid-cols-[minmax(0,1fr)_minmax(0,1.3fr)]">
        <Card className="flex flex-col p-5">
          <p className="text-[13.5px] text-graphite">EU261 claims provision · NS31</p>
          <p className="display-tight mt-1.5 text-[32px] text-owed-ink">
            <RollingNumber value={NS31.provision} prefix="€" trigger={null} />
          </p>
          <div className="mt-3 flex gap-2">
            <Chip kind="drafted" />
            <Chip kind="technical">Held</Chip>
          </div>
          <p className="mt-4 text-[13.5px] leading-relaxed text-graphite">212 passengers × €600 exposure, provided at a 35% claim rate learned from two years of claims (R-6 v4).</p>
          <button
            type="button"
            onClick={() => openWhy({ kind: "provision", flight: "NS31", amount: NS31.provision })}
            className="mt-4 self-start rounded-lg bg-chart px-3.5 py-2 text-[13.5px] font-medium transition-colors hover:bg-fog"
          >
            Why this €?
          </button>
        </Card>
        <Card className="p-5">
          <div className="flex items-baseline justify-between">
            <h2 className="text-[15px] font-semibold">Claim curve</h2>
            <span className="text-[13px] text-graphite">Transatlantic routes · R-6 v4</span>
          </div>
          <div className="mt-2">
            <ClaimCurve />
          </div>
          <p className="mt-1 text-[13px] text-graphite">Cumulative claims modelled over 24 months, approaching the learned 35% rate. Dots are what was actually filed at each check-in.</p>
        </Card>
      </div>

      <Card className="mt-3 flex flex-wrap items-center justify-between gap-3 px-5 py-3.5">
        <div>
          <p className="text-[14px] font-semibold">Claims filed vs curve</p>
          <p className="text-[13px] text-graphite">Checked at each month-end close, transatlantic routes.</p>
        </div>
        <p className="font-mono text-[13.5px]">
          Month 18: 33% filed · 32% on the curve · <span className="text-settled-ink">1 point ahead</span>
        </p>
      </Card>

      <div className="mt-7 flex flex-wrap items-center justify-between gap-3">
        <h2 className="text-[18px] font-semibold">Journal</h2>
        <div className="min-h-[40px]">
          <AnimatePresence mode="wait" initial={false}>
            {confirming ? (
              <motion.div
                key="confirm"
                initial={{ opacity: 0, y: -4 }}
                animate={{ opacity: 1, y: 0 }}
                exit={{ opacity: 0, y: -4 }}
                transition={{ duration: 0.2, ease }}
                className="flex flex-wrap items-center gap-3 rounded-xl bg-white p-3 shadow-[0_0_0_1px_#e6e6e0]"
              >
                <p className="max-w-[34ch] text-[13.5px] text-graphite">Post {pendingCount} entries to the ledger. This is a bookkeeping step; no cash moves.</p>
                <div className="flex gap-2">
                  <button type="button" onClick={() => setConfirming(false)} className="rounded-lg px-3 py-2 text-[13.5px] text-graphite hover:bg-fog">
                    Cancel
                  </button>
                  <button type="button" onClick={confirmPost} className="rounded-lg bg-ink px-3.5 py-2 text-[13.5px] font-semibold text-chart">
                    Confirm
                  </button>
                </div>
              </motion.div>
            ) : (
              <motion.div key="btn" initial={{ opacity: 0 }} animate={{ opacity: 1 }} exit={{ opacity: 0 }} transition={{ duration: 0.15 }}>
                {canApprove ? (
                  <button
                    type="button"
                    disabled={pendingCount === 0}
                    onClick={() => setConfirming(true)}
                    className="rounded-lg bg-ink px-4 py-2.5 text-[14px] font-semibold text-chart disabled:cursor-not-allowed disabled:opacity-40"
                  >
                    {pendingCount === 0 ? "All entries posted" : `Approve ${pendingCount} entr${pendingCount === 1 ? "y" : "ies"}`}
                  </button>
                ) : (
                  <span title="Only the Controller approves journal entries">
                    <button type="button" disabled aria-disabled="true" className="cursor-not-allowed rounded-lg bg-ink px-4 py-2.5 text-[14px] font-semibold text-chart opacity-40">
                      Approve entries
                    </button>
                  </span>
                )}
              </motion.div>
            )}
          </AnimatePresence>
        </div>
      </div>

      <div className="mt-3 flex flex-col gap-3">
        {JOURNAL.map((j) => (
          <JournalCard key={j.id} entry={j} posted={posted.has(j.id)} onWhy={j.id === "JE-2041" ? () => openWhy({ kind: "provision", flight: "NS31", amount: NS31.provision }) : undefined} />
        ))}
      </div>
    </div>
  );
}
