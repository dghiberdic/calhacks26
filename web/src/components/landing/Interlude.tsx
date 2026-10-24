"use client";

import { useRef } from "react";
import { gsap, useGSAP } from "@/components/motion/gsap";
import { metarAt } from "@/data/scenario";

/** A held breath between the evidence and the money: the photoreal render, rain on the lens. */
export function Interlude() {
  const root = useRef<HTMLElement>(null);
  useGSAP(
    () => {
      gsap.fromTo(".il-img", { scale: 1.12, yPercent: -4 }, { scale: 1.0, yPercent: 4, ease: "none", scrollTrigger: { trigger: root.current, start: "top bottom", end: "bottom top", scrub: true } });
      gsap.fromTo(".il-rain", { yPercent: -10 }, { yPercent: 10, ease: "none", scrollTrigger: { trigger: root.current, start: "top bottom", end: "bottom top", scrub: true } });
      gsap.from(".il-copy > *", { opacity: 0, y: 18, stagger: 0.12, duration: 0.9, ease: "power3.out", scrollTrigger: { trigger: root.current, start: "top 45%" } });
    },
    { scope: root },
  );
  return (
    <section ref={root} aria-label="EI-NSA on stand at Dublin, 21:30Z" className="relative h-[115svh] overflow-hidden bg-night">
      {/* eslint-disable-next-line @next/next/no-img-element */}
      <img src="/renders/ns31-hero-render.webp" alt="Rendering of Northstar A321neo EI-NSA parked on a wet stand at Dublin at night" className="il-img absolute inset-0 h-full w-full object-cover" />
      {/* eslint-disable-next-line @next/next/no-img-element */}
      <img src="/renders/ns31-side-rain.webp" alt="" aria-hidden="true" className="il-rain pointer-events-none absolute inset-0 h-full w-full object-cover opacity-40 mix-blend-screen" />
      <div className="pointer-events-none absolute inset-0 bg-gradient-to-t from-night via-night/10 to-night/60" />
      <div className="il-copy absolute inset-x-0 bottom-0 px-5 pb-20 md:px-16 md:pb-28">
        <p className="font-mono text-[14px] text-haze">{metarAt("21:30").raw}</p>
        <h2 className="display mt-5 max-w-[16ch] text-[clamp(40px,6vw,104px)] text-[#f4f6f8]">21:30Z. Still on stand.</h2>
        <p className="mt-5 max-w-[44ch] text-[17px] leading-relaxed text-haze md:text-[19px]">
          The storm has passed and the evening flights have left. EI-NSA is waiting for a hydraulic part. Its 212 passengers are owed €127,200.
        </p>
      </div>
    </section>
  );
}
