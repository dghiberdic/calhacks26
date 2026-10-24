"use client";

import { useRef, useState } from "react";
import { FLIGHTS } from "@/data/scenario";
import { FlapText } from "./SplitFlap";
import { gsap, ScrollTrigger, useGSAP } from "@/components/motion/gsap";
import { cn, eur } from "@/lib/cn";

type Phase = "blank" | "coded" | "checked";

/**
 * The 14 cancellations, all coded "weather". Scroll further and StormCheck re-checks
 * them: 13 settle as weather (dim), NS31 flaps to TECH with its exposure.
 */
export function DepartureBoard() {
  const root = useRef<HTMLDivElement>(null);
  const [phase, setPhase] = useState<Phase>("blank");

  useGSAP(
    () => {
      ScrollTrigger.create({
        trigger: root.current,
        start: "top 70%",
        onEnter: () => setPhase((p) => (p === "blank" ? "coded" : p)),
      });
      ScrollTrigger.create({
        trigger: root.current,
        start: "center 45%",
        onEnter: () => setPhase("checked"),
        onLeaveBack: () => setPhase("coded"),
      });
      gsap.from(".board-row", {
        opacity: 0,
        y: 12,
        stagger: 0.03,
        duration: 0.6,
        scrollTrigger: { trigger: root.current, start: "top 75%" },
      });
    },
    { scope: root },
  );

  const owedTotal = phase === "checked" ? 212 * 600 : 0;

  return (
    <div ref={root} className="relative">
      <div className="mb-6 flex items-end justify-between gap-6 text-mist">
        <div className="label">Dublin · departures · {phase === "checked" ? "re-checked 09:00" : "storm night"}</div>
        <div className="flex items-baseline gap-3">
          <span className="label">Owed</span>
          <FlapText text={eur(owedTotal)} width={8} stagger={40} className="text-[22px] md:text-[28px]" cellClassName={owedTotal ? "!text-[#ff7a5c]" : undefined} />
        </div>
      </div>

      <div className="overflow-x-auto rounded-md bg-[#0d1117] p-3 md:p-5" data-lenis-prevent>
        <div className="min-w-[760px] text-[15px] md:text-[19px]">
          <div className="label mb-3 grid grid-cols-[5.2em_6.2em_11.8em_9.4em_4.6em_1fr] gap-x-[0.9em] px-1 text-[11px] text-mist">
            <span>Time</span>
            <span>Flight</span>
            <span>Destination</span>
            <span>Status</span>
            <span>Cause</span>
            <span className="text-right">Owed</span>
          </div>
          <div className="flex flex-col gap-[0.32em]">
            {FLIGHTS.map((f, i) => {
              const tech = f.verdict === "technical";
              const show = phase !== "blank";
              const checked = phase === "checked";
              const d = i * 90;
              return (
                <div
                  key={f.id}
                  className={cn(
                    "board-row grid grid-cols-[5.2em_6.2em_11.8em_9.4em_4.6em_1fr] items-center gap-x-[0.9em] rounded-sm px-1 py-[0.1em] transition-colors duration-700",
                    checked && !tech && "flap-dim",
                    checked && tech && "bg-[#2a1712]",
                  )}
                >
                  <FlapText text={show ? f.sched : ""} width={5} delay={d} />
                  <FlapText text={show ? f.id : ""} width={6} delay={d + 60} />
                  <FlapText text={show ? f.city : ""} width={12} delay={d + 120} />
                  <FlapText text={show ? "CANCELLED" : ""} width={9} delay={d + 180} />
                  <FlapText
                    text={show ? (checked && tech ? "TECH" : "WX") : ""}
                    width={4}
                    delay={checked ? 200 : d + 240}
                    className={cn(checked && tech && "flap-alert")}
                  />
                  <span className="flex justify-end">
                    <FlapText
                      text={show ? (checked && tech ? eur(f.pax * 600) : "€0") : ""}
                      width={8}
                      delay={checked ? 420 : d + 300}
                      className={cn(checked && tech && "flap-alert")}
                    />
                  </span>
                </div>
              );
            })}
          </div>
        </div>
      </div>
    </div>
  );
}
