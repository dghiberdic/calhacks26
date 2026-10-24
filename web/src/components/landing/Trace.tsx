"use client";

import { useRef } from "react";
import { gsap, useGSAP } from "@/components/motion/gsap";
import { cn } from "@/lib/cn";
import { STORM } from "@/data/scenario";

type Node = { value: string; mono?: boolean; title: string; detail: React.ReactNode; tone?: "owed" | "ink" | "weather" };

const NODES: Node[] = [
  { value: "€44,520", title: "EU261 claims provision, NS31", detail: "Drafted 09:00Z. Waiting for the Claims Lead.", tone: "owed" },
  { value: "€127,200 × 35%", title: "Exposure at the learned claim rate", detail: "Rate learned from 18 storms and 2 years of Northstar claims." },
  { value: "212 × €600", title: "Passengers × Article 7 tier", detail: "Dublin to Boston is 4,802 km, over the 3,500 km tier." },
  { value: "Technical fault", title: "Cause, set by rule R-3 v2", detail: "Technical problems are not extraordinary circumstances. CJEU C-549/07, Wallentin-Hermann." },
  {
    value: "07:55Z",
    mono: true,
    title: "Technical log, EI-NSA, ATA 29-11",
    detail: <span className="font-mono text-[13px]">HYD G RSVR LO LVL. LEAK FOUND AT ENG 1 EDP CASE DRAIN LINE.</span>,
  },
  {
    value: `${STORM.windowStart}–${STORM.windowEnd}Z`,
    mono: true,
    title: "Storm window, from METAR",
    detail: `Gusts at or above ${STORM.limitKt} kt, peaking at ${STORM.peak.gust} kt at ${STORM.peak.t}Z. NS31 was due at 21:30, after the window closed. Three evening flights left on time.`,
    tone: "weather",
  },
  { value: "Legal", title: "Ruled 12 Mar 2026", detail: "Asked once. Applied 14 times since, never asked again." },
];

export function Trace() {
  const root = useRef<HTMLDivElement>(null);

  useGSAP(
    () => {
      gsap.from(".tr-line", {
        scaleY: 0,
        transformOrigin: "top center",
        ease: "none",
        scrollTrigger: { trigger: ".tr-list", start: "top 70%", end: "bottom 60%", scrub: 0.6 },
      });
      gsap.utils.toArray<HTMLElement>(".tr-node").forEach((el) => {
        gsap.from(el, {
          opacity: 0.12,
          x: -10,
          duration: 0.6,
          ease: "power3.out",
          scrollTrigger: { trigger: el, start: "top 72%", toggleActions: "play none none reverse" },
        });
      });
    },
    { scope: root },
  );

  return (
    <div ref={root} className="mx-auto grid max-w-[1400px] grid-cols-1 gap-16 lg:grid-cols-[minmax(0,5fr)_minmax(0,7fr)]">
      <div className="lg:sticky lg:top-32 lg:self-start">
        <h2 className="display text-[clamp(44px,6vw,104px)] text-ink">Every euro, traced.</h2>
        <p className="mt-6 max-w-[38ch] text-[17px] leading-relaxed text-graphite md:text-[19px]">
          Click any amount and StormCheck walks it back to the log line, the weather hour, the rule and the person who ruled. Your auditor can follow the same thread.
        </p>
      </div>

      <ol className="tr-list relative">
        <span className="tr-line absolute bottom-6 left-[7px] top-6 w-px bg-ink" aria-hidden="true" />
        {NODES.map((n, i) => (
          <li key={i} className="tr-node relative grid grid-cols-[16px_minmax(0,1fr)] gap-x-6 pb-12 last:pb-0">
            <span
              className={cn(
                "relative z-10 mt-[0.62em] h-[15px] w-[15px] rounded-full border-2 bg-chart",
                n.tone === "owed" ? "border-owed bg-owed" : n.tone === "weather" ? "border-weather" : "border-ink",
              )}
              aria-hidden="true"
            />
            <div>
              <p
                className={cn(
                  "display-tight text-[clamp(26px,2.6vw,40px)] leading-tight",
                  n.mono && "font-mono text-[clamp(22px,2.2vw,34px)] font-normal tracking-normal",
                  n.tone === "owed" && "text-owed-ink",
                  n.tone === "weather" && "text-weather-ink",
                )}
              >
                {n.value}
              </p>
              <p className="mt-2 text-[16px] font-medium text-ink">{n.title}</p>
              <p className="mt-1 max-w-[52ch] text-[15px] leading-relaxed text-graphite">{n.detail}</p>
            </div>
          </li>
        ))}
      </ol>
    </div>
  );
}
