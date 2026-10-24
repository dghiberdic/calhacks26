"use client";

import { useRef } from "react";
import { gsap, PLOTTED, UNPLOTTED, useGSAP } from "@/components/motion/gsap";
import { metarAt } from "@/data/scenario";
import { HERO_LINES } from "@/data/geo/lineart";

/**
 * Drawing → photograph, Belgrade Arbor style but with our own renders: Blender line art plots itself
 * stroke by stroke, then the Cycles render from the very same camera washes in from the nose.
 */
export function Interlude() {
  const root = useRef<HTMLElement>(null);
  useGSAP(
    () => {
      const mm = gsap.matchMedia();
      mm.add("(prefers-reduced-motion: no-preference)", () => {
        const tl = gsap.timeline({
          defaults: { ease: "none" },
          scrollTrigger: { trigger: root.current, start: "top top", end: "+=150%", scrub: 0.8, pin: true, anticipatePin: 1 },
        });
        tl.from(".il-line", { ...UNPLOTTED, duration: 0.5, stagger: { amount: 3.2 }, ease: "plotter" }, 0)
          .fromTo(".il-img", { "--r": "0%" }, { "--r": "175%", duration: 3.2, ease: "power1.inOut" }, 3.0)
          .to(".il-lines", { opacity: 0.12, duration: 1.6 }, 4.4)
          .fromTo(".il-rain", { opacity: 0 }, { opacity: 0.38, duration: 1.2 }, 5.2)
          .fromTo(".il-copy > *", { opacity: 0, y: 18 }, { opacity: 1, y: 0, duration: 0.8, stagger: 0.25, ease: "power3.out" }, 5.4)
          .fromTo(".il-img", { scale: 1.06 }, { scale: 1, duration: 4, ease: "power1.out" }, 3.0)
          .to({}, { duration: 0.8 });
      });
      gsap.to(".il-rain", { backgroundPositionY: "+=1400px", duration: 1.4, ease: "none", repeat: -1 });
    },
    { scope: root },
  );

  return (
    <section ref={root} aria-label="EI-NSA on stand at Dublin, 21:30Z" className="relative h-svh overflow-hidden bg-night">
      {/* the render, revealed by a soft radial wash centred on the nose */}
      {/* eslint-disable-next-line @next/next/no-img-element */}
      <img
        src="/renders/ns31-hero-render.webp"
        alt="Rendering of Northstar A321neo EI-NSA parked on a wet stand at Dublin at night"
        className="il-img absolute inset-0 h-full w-full object-cover"
        style={{
          ["--r" as string]: "175%",
          maskImage: "radial-gradient(circle at 22% 46%, #000 calc(var(--r) - 22%), transparent var(--r))",
          WebkitMaskImage: "radial-gradient(circle at 22% 46%, #000 calc(var(--r) - 22%), transparent var(--r))",
        }}
      />
      <svg className="il-lines pointer-events-none absolute inset-0 h-full w-full" viewBox="0 0 2560 1440" preserveAspectRatio="xMidYMid slice" aria-hidden="true">
        {HERO_LINES.map((d, i) => (
          <path key={i} className="il-line" d={d} fill="none" stroke="#e9edf2" strokeWidth={2.2} strokeLinecap="round" strokeLinejoin="round" {...PLOTTED} />
        ))}
      </svg>
      <div
        className="il-rain pointer-events-none absolute inset-0 opacity-0 mix-blend-screen"
        style={{ backgroundImage: "url(/renders/ns31-side-rain.webp)", backgroundSize: "cover", backgroundRepeat: "repeat-y" }}
        aria-hidden="true"
      />
      <div className="pointer-events-none absolute inset-0 bg-gradient-to-t from-night via-night/5 to-night/50" />
      <div className="il-copy absolute inset-x-0 bottom-0 px-5 pb-16 md:px-16 md:pb-24">
        <p className="font-mono text-[14px] text-haze">{metarAt("21:30").raw}</p>
        <h2 className="display mt-5 max-w-[16ch] text-[clamp(40px,6vw,104px)] text-[#f4f6f8]">21:30Z. Still on stand.</h2>
        <p className="mt-5 max-w-[44ch] text-[17px] leading-relaxed text-haze md:text-[19px]">
          The storm has passed and the evening flights have left. EI-NSA is waiting for a hydraulic part. Its 212 passengers are owed €127,200.
        </p>
      </div>
    </section>
  );
}
