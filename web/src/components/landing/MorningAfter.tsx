"use client";

import { useRef } from "react";
import { gsap, useGSAP } from "@/components/motion/gsap";

/** Night turns to chart paper; the line's ink follows so it never loses contrast. */
export function MorningAfter() {
  const root = useRef<HTMLElement>(null);
  useGSAP(
    () => {
      gsap.fromTo(
        ".ma-text",
        { color: "#f4f6f8" },
        { color: "#121417", ease: "none", scrollTrigger: { trigger: root.current, start: "35% top", end: "62% top", scrub: true } },
      );
      gsap.from(".ma-text", { opacity: 0, y: 30, duration: 1.2, ease: "power3.out", scrollTrigger: { trigger: root.current, start: "top 40%" } });
    },
    { scope: root },
  );
  return (
    <section
      ref={root}
      aria-label="The morning after"
      className="relative h-[170vh]"
      style={{ background: "linear-gradient(to bottom, var(--color-cyanotype) 0%, #0d1c2c 22%, #3b4652 50%, #c9ccc8 78%, var(--color-chart) 100%)" }}
    >
      <div className="sticky top-0 flex h-svh items-center justify-center px-5">
        <p className="ma-text display text-center text-[clamp(40px,6.4vw,112px)]">
          <span className="font-mono text-[0.62em] font-normal tracking-normal">09:00Z</span>
          <br />
          The morning after.
        </p>
      </div>
    </section>
  );
}
