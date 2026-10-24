"use client";

import { useEffect, useMemo } from "react";
import { AnimatePresence, motion } from "motion/react";
import Link from "next/link";
import { useApp } from "@/lib/store";
import { FLIGHTS, NS31, OPERATED, STORM, tier, metarNear } from "@/data/scenario";
import { sideView } from "@/lib/drawings/aircraft";
import { CauseTimeline } from "./CauseTimeline";
import { Chip, Confidence, Money } from "./ui";
import { cn } from "@/lib/cn";

/** Evidence inks the drawing: pencil until the sources agree, then ink (red where the fault is). */
function InkedAircraft({ technical }: { technical: boolean }) {
  const strokes = useMemo(() => sideView(), []);
  return (
    <svg viewBox="-1 -12.6 47 13.6" className="w-full" aria-hidden="true">
      {strokes.map((s, i) => {
        const isEngine = s.id === "nacelle" || s.id === "inlet" || s.id === "pylon";
        return (
          <path
            key={i}
            d={s.d}
            fill="none"
            pathLength={1}
            className="ink-path"
            style={{ animationDelay: `${i * 0.04}s` }}
            stroke={technical && isEngine ? "#e04a2f" : "#121417"}
            strokeOpacity={s.kind === "outline" ? 0.9 : 0.45}
            strokeWidth={s.kind === "outline" ? 0.09 : 0.05}
            strokeLinejoin="round"
          />
        );
      })}
      {technical && <circle cx="17.4" cy="-1.75" r="1.6" fill="none" stroke="#e04a2f" strokeWidth="0.08" strokeDasharray="0.3 0.2" />}
    </svg>
  );
}

export function FlightSheet() {
  const { sheet, openSheet, openWhy, role } = useApp();
  const f = FLIGHTS.find((x) => x.id === sheet);

  useEffect(() => {
    const k = (e: KeyboardEvent) => e.key === "Escape" && openSheet(null);
    window.addEventListener("keydown", k);
    return () => window.removeEventListener("keydown", k);
  }, [openSheet]);

  const technical = f?.verdict === "technical";
  const amount = f ? tier(f.km) : 0;
  const atDep = f ? metarNear(f.sched) : null;

  return (
    <AnimatePresence>
      {f && (
        <>
          <motion.div
            key="scrim"
            className="fixed inset-0 z-50 bg-ink/10"
            initial={{ opacity: 0 }}
            animate={{ opacity: 1 }}
            exit={{ opacity: 0 }}
            onClick={() => openSheet(null)}
          />
          <motion.aside
            key="sheet"
            role="dialog"
            aria-modal="true"
            aria-label={`${f.id} to ${f.city}`}
            initial={{ x: 40, opacity: 0 }}
            animate={{ x: 0, opacity: 1 }}
            exit={{ x: 40, opacity: 0 }}
            transition={{ type: "spring", stiffness: 380, damping: 36 }}
            className="fixed bottom-0 right-0 top-0 z-50 flex w-full max-w-[480px] flex-col overflow-y-auto bg-white shadow-[-1px_0_0_#e6e6e0,-24px_0_60px_rgba(18,20,23,0.10)]"
            data-lenis-prevent
          >
            <div className="flex items-start justify-between gap-4 px-6 pb-2 pt-6">
              <div>
                <p className="font-mono text-[13px] text-graphite">
                  {f.id} &nbsp; {f.reg} &nbsp; {f.type === "A321" ? "A321neo" : f.type}
                </p>
                <h2 className="display-tight mt-1 text-[26px]">Dublin → {f.city}</h2>
                <p className="mt-1 text-[14px] text-graphite">
                  Due <span className="font-mono text-ink">{f.sched}Z</span>, {f.pax} passengers, {f.km.toLocaleString("en-IE")} km
                </p>
              </div>
              <button type="button" onClick={() => openSheet(null)} aria-label="Close" className="flex h-9 w-9 shrink-0 items-center justify-center rounded-lg bg-chart text-graphite transition-colors hover:bg-fog hover:text-ink">
                <svg width="12" height="12" viewBox="0 0 12 12" aria-hidden="true">
                  <path d="M2 2 L10 10 M10 2 L2 10" stroke="currentColor" strokeWidth="1.6" />
                </svg>
              </button>
            </div>

            <div className="px-6">
              <InkedAircraft technical={technical} />
            </div>

            <section className={cn("mx-6 mt-2 rounded-xl p-4", technical ? "bg-[#fff4f1]" : "bg-chart")}>
              <div className="flex items-center justify-between gap-3">
                <p className={cn("display-tight text-[19px]", technical ? "text-[#a32e19]" : "text-ink")}>{technical ? "Technical fault, not weather" : "Weather. Nothing owed."}</p>
                <Chip kind={f.verdict}>{f.verdict === "technical" ? "Owed" : "Weather"}</Chip>
              </div>
              <div className="mt-4">
                <Confidence
                  value={f.confidence}
                  tone={technical ? "owed" : "weather"}
                  runnerUp={technical ? "Runner-up: weather, 9%. Above the 80% line, so StormCheck drafts it." : `Departure fell inside the storm window. Runner-up: technical, ${100 - f.confidence}%.`}
                />
              </div>
            </section>

            <section className="px-6 pt-6">
              <h3 className="text-[14px] font-semibold">The day at Dublin</h3>
              <div className="mt-2">
                <CauseTimeline
                  marks={[
                    ...(technical ? [{ t: NS31.techLog.time, kind: "fault" as const, label: "07:55 fault" }] : []),
                    ...OPERATED.map((o) => ({ t: o.sched, kind: "operated" as const })),
                    { t: f.sched, kind: technical ? ("departure" as const) : ("weather" as const), label: f.id },
                  ]}
                />
              </div>
            </section>

            <section className="px-6 pt-5">
              <h3 className="text-[14px] font-semibold">Evidence, strongest first</h3>
              <ol className="mt-3 space-y-3 text-[14px]">
                {technical ? (
                  <>
                    <li className="grid grid-cols-[68px_1fr] gap-3">
                      <span className="font-mono text-owed-ink">07:55Z</span>
                      <span>
                        <span className="font-medium">Tech log, ATA {NS31.techLog.ata}.</span>{" "}
                        <span className="font-mono text-[12.5px]">{NS31.techLog.entry}</span>
                      </span>
                    </li>
                    <li className="grid grid-cols-[68px_1fr] gap-3">
                      <span className="font-mono text-graphite">08:12Z</span>
                      <span>
                        <span className="font-medium">Ops coded it 71, weather.</span> Overruled: the tech log ranks above a cause code (R-2).
                      </span>
                    </li>
                    <li className="grid grid-cols-[68px_1fr] gap-3">
                      <span className="font-mono text-graphite">{STORM.windowStart}–{STORM.windowEnd}Z</span>
                      <span>
                        <span className="font-medium">Storm window, from METAR.</span> Gusts peaked at {STORM.peak.gust}&nbsp;kt at {STORM.peak.t}Z. NS31 was due 2&nbsp;h&nbsp;30&nbsp;min after it closed.
                      </span>
                    </li>
                    <li className="grid grid-cols-[68px_1fr] gap-3">
                      <span className="font-mono text-graphite">19:45Z</span>
                      <span>
                        <span className="font-medium">{OPERATED.map((o) => o.id).join(", ")} left</span> after the window, on time.
                      </span>
                    </li>
                  </>
                ) : (
                  <>
                    <li className="grid grid-cols-[68px_1fr] gap-3">
                      <span className="font-mono text-graphite">{atDep?.t}Z</span>
                      <span>
                        <span className="font-medium">Strongest METAR within 30 min of departure.</span> <span className="font-mono text-[12.5px]">{atDep?.raw}</span>
                      </span>
                    </li>
                    <li className="grid grid-cols-[68px_1fr] gap-3">
                      <span className="font-mono text-graphite">—</span>
                      <span>
                        <span className="font-medium">No open tech-log items</span> for {f.reg} that day.
                      </span>
                    </li>
                  </>
                )}
              </ol>
            </section>

            <section className="mt-auto border-t border-[#f0f0eb] px-6 py-5">
              {technical ? (
                <dl className="grid grid-cols-[1fr_auto] gap-x-4 gap-y-1.5 text-[14px]">
                  <dt className="text-graphite">
                    {f.pax} payouts × €{amount}
                  </dt>
                  <dd>
                    <Money value={f.pax * amount} />
                  </dd>
                  <dt className="text-graphite">Provision at 35% claim rate</dt>
                  <dd>
                    <Money value={NS31.provision} className="text-owed-ink" />
                  </dd>
                </dl>
              ) : (
                <p className="text-[14px] text-graphite">Refunds and rebooking only (Art. 8). No Art. 7 compensation.</p>
              )}
              <div className="mt-4 flex gap-2">
                {role === "ops" ? (
                  <p className="flex-1 rounded-lg bg-chart px-3 py-2.5 text-[13px] text-graphite">Passenger details are hidden for Ops.</p>
                ) : (
                  <Link href={`/app/payouts?flight=${f.id}`} onClick={() => openSheet(null)} className="flex-1 rounded-lg bg-ink px-4 py-2.5 text-center text-[14px] font-semibold text-chart transition-colors hover:bg-[#2a2f36]">
                    Review {f.pax} {technical ? "payouts" : "refunds"}
                  </Link>
                )}
                {technical && (
                  <button type="button" onClick={() => openWhy({ kind: "provision", flight: f.id, amount: NS31.provision })} className="rounded-lg bg-chart px-4 py-2.5 text-[14px] transition-colors hover:bg-fog">
                    Why this €?
                  </button>
                )}
              </div>
            </section>
          </motion.aside>
        </>
      )}
    </AnimatePresence>
  );
}
