"use client";

import { useState } from "react";
import { motion } from "motion/react";
import { FLIGHTS, NS31, OPERATED, totals } from "@/data/scenario";
import { QUESTIONS } from "@/data/app";
import { useApp } from "@/lib/store";
import { Card, Chip, Money } from "@/components/app/ui";
import { CauseTimeline } from "@/components/app/CauseTimeline";
import { RouteMap } from "@/components/app/RouteMap";
import { RollingNumber } from "@/components/motion/RollingNumber";
import { cn } from "@/lib/cn";

type Filter = "all" | "owed" | "weather";

export default function Overview() {
  const { openSheet, answered, setRun } = useApp();
  const [filter, setFilter] = useState<Filter>("all");
  const [hover, setHover] = useState<string | null>(null);
  const t = totals();
  const waiting = QUESTIONS.filter((q) => !answered[q.id]).length;
  const rows = [...FLIGHTS]
    .filter((f) => filter === "all" || (filter === "owed" ? f.verdict === "technical" : f.verdict === "weather"))
    .sort((a, b) => (a.verdict === "technical" ? -1 : b.verdict === "technical" ? 1 : b.sched.localeCompare(a.sched)));

  const kpis = [
    { label: "Passengers sorted", value: <RollingNumber value={t.pax} trigger={null} /> },
    { label: "Exposure if all claim", value: <RollingNumber value={NS31.exposure} prefix="€" trigger={null} /> },
    { label: "Provision drafted", value: <RollingNumber value={NS31.provision} prefix="€" trigger={null} className="text-owed-ink" /> },
    { label: "Waiting on people", value: <span>{waiting}</span>, sub: waiting === 1 ? "question" : "questions" },
  ];

  return (
    <div className="mx-auto max-w-[1280px]">
      <div className="flex flex-wrap items-end justify-between gap-4">
        <div>
          <h1 className="display-tight text-[30px]">Storm night</h1>
          <p className="mt-1 max-w-[60ch] text-[15px] text-graphite">
            Ops cancelled {t.cancelled} departures and coded every one as weather. StormCheck re-checked each against METAR and the aircraft&rsquo;s logs.
          </p>
        </div>
        <button type="button" onClick={() => setRun(true)} className="rounded-lg bg-white px-3.5 py-2 text-[14px] shadow-[0_0_0_1px_#e2e2dc] transition-shadow hover:shadow-[0_0_0_1px_#b9b9b2]">
          Replay the 09:00Z run
        </button>
      </div>

      <div className="mt-6 grid grid-cols-2 gap-3 lg:grid-cols-4">
        {kpis.map((k, i) => (
          <motion.div key={k.label} initial={{ opacity: 0, y: 8 }} animate={{ opacity: 1, y: 0 }} transition={{ delay: i * 0.05, duration: 0.4, ease: [0.16, 1, 0.3, 1] }}>
            <Card className="px-4 py-3.5">
              <p className="text-[13.5px] text-graphite">{k.label}</p>
              <p className="display-tight mt-1.5 text-[26px]">
                {k.value} {k.sub && <span className="text-[14px] font-normal tracking-normal text-graphite">{k.sub}</span>}
              </p>
            </Card>
          </motion.div>
        ))}
      </div>

      <div className="mt-3 grid grid-cols-1 gap-3 lg:grid-cols-[minmax(0,1.6fr)_minmax(0,1fr)]">
        <Card className="p-5">
          <div className="mb-1 flex items-baseline justify-between">
            <h2 className="text-[15px] font-semibold">The day at Dublin</h2>
            <span className="text-[13px] text-graphite">Gusts from METAR, knots</span>
          </div>
          <CauseTimeline
            height={168}
            marks={[
              { t: NS31.techLog.time, kind: "fault", label: "07:55 NS31 fault" },
              ...FLIGHTS.filter((f) => f.verdict !== "technical").map((f) => ({ t: f.sched, kind: "weather" as const })),
              ...OPERATED.map((o) => ({ t: o.sched, kind: "operated" as const })),
              { t: NS31.flight.sched, kind: "departure", label: "NS31" },
            ]}
          />
          <div className="mt-3 flex flex-wrap gap-x-5 gap-y-2 text-[13px] text-graphite">
            <span className="flex items-center gap-2">
              <span className="h-2.5 w-2.5 rounded-full bg-weather" /> Cancelled in the window
            </span>
            <span className="flex items-center gap-2">
              <span className="h-2.5 w-2.5 rounded-full bg-settled" /> Operated after it
            </span>
            <span className="flex items-center gap-2">
              <span className="h-2.5 w-2.5 rounded-full bg-owed" /> Cancelled after it, owed
            </span>
          </div>
        </Card>
        <Card className="relative overflow-hidden">
          <div className="absolute left-5 top-4 z-10">
            <h2 className="text-[15px] font-semibold">Routes</h2>
            <p className="text-[13px] text-graphite">9 transatlantic, 3 European</p>
          </div>
          <div className="h-[240px] pt-10 lg:h-full">
            <RouteMap active={hover} onHover={setHover} />
          </div>
        </Card>
      </div>

      <Card className="mt-3 overflow-hidden">
        <div className="flex flex-wrap items-center justify-between gap-3 px-5 py-3.5">
          <h2 className="text-[15px] font-semibold">Cancellations</h2>
          <div className="flex gap-1 rounded-lg bg-chart p-1 text-[13.5px]" role="tablist" aria-label="Filter flights">
            {(
              [
                ["all", `All ${t.cancelled}`],
                ["owed", `Owed ${t.owedFlights}`],
                ["weather", `Weather ${t.weather}`],
              ] as [Filter, string][]
            ).map(([k, l]) => (
              <button key={k} role="tab" aria-selected={filter === k} type="button" onClick={() => setFilter(k)} className={cn("rounded-md px-3 py-1.5 transition-colors", filter === k ? "bg-white font-medium shadow-[0_0_0_1px_#e6e6e0]" : "text-graphite hover:text-ink")}>
                {l}
              </button>
            ))}
          </div>
        </div>
        {/* Phones: what StormCheck decided and what's owed, per flight, without a sideways table. */}
        <ul className="md:hidden" aria-label="Cancellations">
          {rows.map((f) => {
            const tech = f.verdict === "technical";
            return (
              <li key={f.id} className={cn("border-t border-[#f0f0eb]", tech && "bg-[#fff6f3]")}>
                <button type="button" onClick={() => openSheet(f.id)} className="flex w-full items-center justify-between gap-3 px-5 py-3 text-left">
                  <span className="min-w-0">
                    <span className={cn("font-mono text-[14px]", tech && "font-bold")}>{f.id}</span>
                    <span className="ml-2 text-[14px]">{f.city}</span>
                    <span className="tabular mt-0.5 block text-[12.5px] text-graphite">
                      {f.sched}Z · {f.pax} pax · ops <span className={cn(tech && "line-through decoration-owed")}>71</span>
                      {tech && <span className="text-owed-ink"> → 41</span>}
                    </span>
                  </span>
                  <span className="flex shrink-0 flex-col items-end gap-1">
                    <Chip kind={f.verdict}>
                      {tech ? "Technical" : "Weather"} · {f.confidence}%
                    </Chip>
                    {tech ? <Money value={f.pax * 600} className="text-[14px] text-owed-ink" /> : <Money value={0} className="text-[14px] text-graphite" />}
                  </span>
                </button>
              </li>
            );
          })}
        </ul>
        <div className="hidden overflow-x-auto md:block" data-lenis-prevent-horizontal>
          <table className="w-full min-w-[760px] border-collapse text-[14px]">
            <thead>
              <tr className="text-left text-[13px] text-graphite">
                <th scope="col" className="px-5 pb-2.5 font-medium">Due</th>
                <th scope="col" className="px-2 pb-2.5 font-medium">Flight</th>
                <th scope="col" className="px-2 pb-2.5 font-medium">To</th>
                <th scope="col" className="px-2 pb-2.5 text-right font-medium">Pax</th>
                <th scope="col" className="px-2 pb-2.5 font-medium">Ops code</th>
                <th scope="col" className="px-2 pb-2.5 font-medium">StormCheck</th>
                <th scope="col" className="px-5 pb-2.5 text-right font-medium">Owed</th>
              </tr>
            </thead>
            <tbody>
              {rows.map((f) => {
                const tech = f.verdict === "technical";
                return (
                  <tr
                    key={f.id}
                    onClick={() => openSheet(f.id)}
                    onMouseEnter={() => setHover(f.id)}
                    onMouseLeave={() => setHover(null)}
                    className={cn("cursor-pointer border-t border-[#f0f0eb] transition-colors hover:bg-chart", tech && "bg-[#fff6f3] hover:bg-[#ffefe9]")}
                  >
                    <td className="tabular px-5 py-3 text-graphite">{f.sched}</td>
                    <td className={cn("px-2 py-3 font-mono", tech && "font-bold")}>
                      <button type="button" className="text-left underline-offset-4 hover:underline" onClick={(e) => (e.stopPropagation(), openSheet(f.id))}>
                        {f.id}
                      </button>
                    </td>
                    <td className="px-2 py-3">{f.city}</td>
                    <td className="px-2 py-3 text-right font-mono">{f.pax}</td>
                    <td className="px-2 py-3 font-mono text-graphite">
                      <span className={cn(tech && "line-through decoration-owed")}>71 WX</span>
                      {tech && <span className="ml-2 text-owed-ink no-underline">41 TECH</span>}
                    </td>
                    <td className="px-2 py-3">
                      <Chip kind={f.verdict}>
                        {tech ? "Technical" : "Weather"} · {f.confidence}%
                      </Chip>
                    </td>
                    <td className="px-5 py-3 text-right">{tech ? <Money value={f.pax * 600} className="text-owed-ink" /> : <Money value={0} className="text-graphite" />}</td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        </div>
      </Card>
    </div>
  );
}
