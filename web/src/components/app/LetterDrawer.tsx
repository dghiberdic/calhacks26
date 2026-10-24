"use client";

import { AnimatePresence, motion } from "motion/react";
import { useApp } from "@/lib/store";
import { FLIGHTS, NS31, tier } from "@/data/scenario";

/** The Drafter's output: the plain-language EU261 letter a passenger would receive. Drafted, never sent. */
export function LetterDrawer() {
  const { letter, openLetter, role, answered } = useApp();
  const f = FLIGHTS.find((x) => x.id === letter?.flight) ?? NS31.flight;
  const amount = letter?.amount ?? tier(f.km);
  const waiting = letter?.name === "Aoife Byrne" && !answered["Q-12"];
  const first = letter?.name.split(" ")[0] ?? "";

  return (
    <AnimatePresence>
      {letter && (
        <>
          <motion.div key="l-s" className="fixed inset-0 z-[60] bg-ink/20" initial={{ opacity: 0 }} animate={{ opacity: 1 }} exit={{ opacity: 0 }} onClick={() => openLetter(null)} />
          <motion.aside
            key="l"
            role="dialog"
            aria-modal="true"
            aria-label={`Letter to ${letter.name}`}
            initial={{ y: 24, opacity: 0 }}
            animate={{ y: 0, opacity: 1 }}
            exit={{ y: 16, opacity: 0 }}
            transition={{ type: "spring", stiffness: 360, damping: 34 }}
            className="fixed inset-x-3 top-[6svh] z-[60] mx-auto max-h-[88svh] max-w-[620px] overflow-y-auto rounded-2xl bg-white shadow-[0_0_0_1px_#e6e6e0,0_30px_80px_rgba(18,20,23,0.25)]"
            data-lenis-prevent
          >
            <header className="flex items-center justify-between border-b border-[#f0f0eb] px-6 py-4">
              <div>
                <p className="text-[15px] font-semibold">Drafted letter</p>
                <p className="text-[13px] text-graphite">Written by StormCheck from the decision. Not sent.</p>
              </div>
              <button type="button" onClick={() => openLetter(null)} className="rounded-lg px-2.5 py-1.5 text-[13px] text-graphite hover:bg-fog">
                Close
              </button>
            </header>

            <article className="px-8 py-7 text-[15.5px] leading-[1.7] text-ink">
              <p className="text-[13px] text-graphite">Northstar Air · Passenger claims · Dublin</p>
              <p className="mt-6">Dear {first},</p>
              <p className="mt-4">
                Your flight <span className="font-mono">{f.id}</span> from Dublin to {f.city} on 9 December 2025, due to leave at {f.sched}, was cancelled. We&rsquo;re sorry.
              </p>
              <p className="mt-4">
                The cancellation was caused by a technical fault on the aircraft, found at 07:55 that morning, hours before the storm reached Dublin. Under EU Regulation 261/2004, a technical fault is not an
                extraordinary circumstance, so you are owed compensation of <strong className="font-semibold">€{amount}</strong> (Article 7(1)(c), flights over 3,500&nbsp;km).
              </p>
              <p className="mt-4">This is on top of the refund or rebooking you have already been offered. You don&rsquo;t need to fill in a claim form.</p>
              {waiting ? (
                <p className="mt-4 rounded-lg bg-review-wash px-4 py-3 text-[14px] text-[#7a4f00]">
                  Held: our records show a €300 voucher at the gate without a signed acceptance. The Claims Lead decides whether it counts before this letter can go out.
                </p>
              ) : (
                <p className="mt-4">We&rsquo;ll pay it to your original payment card within 7 days of approval.</p>
              )}
              <p className="mt-6">The Northstar claims team</p>
            </article>

            <footer className="flex flex-wrap items-center justify-between gap-3 border-t border-[#f0f0eb] px-6 py-4">
              <p className="font-mono text-[12px] text-graphite">d-7f3a19 · R-3 v2 · R-4 v1 · reading age 12</p>
              <button
                type="button"
                disabled={role !== "claims-lead" || waiting}
                title={role !== "claims-lead" ? "Only the Claims Lead approves letters" : waiting ? "Waiting on Q-12" : undefined}
                className="rounded-lg bg-ink px-3.5 py-2 text-[13.5px] font-semibold text-chart disabled:cursor-not-allowed disabled:opacity-40"
              >
                Approve and queue
              </button>
            </footer>
          </motion.aside>
        </>
      )}
    </AnimatePresence>
  );
}
