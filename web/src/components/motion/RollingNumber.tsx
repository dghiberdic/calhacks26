"use client";

import { useRef } from "react";
import { gsap, useGSAP } from "./gsap";
import { cn } from "@/lib/cn";

/**
 * Odometer digits: each numeral is a 0–9 drum that rolls into place when scrolled into view.
 * Non-digits (€ , .) render static. Screen readers get the formatted value.
 */
export function RollingNumber({
  value,
  format = (n) => n.toLocaleString("en-IE"),
  prefix = "",
  className,
  delay = 0,
  trigger = "top 85%",
}: {
  value: number;
  format?: (n: number) => string;
  prefix?: string;
  className?: string;
  delay?: number;
  trigger?: string;
}) {
  const root = useRef<HTMLSpanElement>(null);
  const text = prefix + format(value);

  useGSAP(
    () => {
      const drums = gsap.utils.toArray<HTMLElement>(".rn-drum", root.current);
      gsap.set(drums, { yPercent: 0 });
      gsap.to(drums, {
        yPercent: (i: number, el: HTMLElement) => -Number(el.dataset.d) * 10,
        duration: 1.4,
        ease: "power3.inOut",
        stagger: { each: 0.06, from: "end" },
        delay,
        scrollTrigger: { trigger: root.current, start: trigger, toggleActions: "play none none reverse" },
      });
    },
    { scope: root, dependencies: [text] },
  );

  return (
    <span ref={root} className={cn("tabular inline-flex overflow-hidden leading-[1.12em]", className)} aria-label={text} role="text">
      {Array.from(text).map((c, i) =>
        /\d/.test(c) ? (
          <span key={i} aria-hidden="true" className="relative inline-block h-[1.12em] overflow-hidden">
            <span className="rn-drum flex flex-col" data-d={c}>
              {Array.from({ length: 10 }, (_, k) => (
                <span key={k} className="block h-[1.12em] leading-[1.12em]">
                  {k}
                </span>
              ))}
            </span>
          </span>
        ) : (
          <span key={i} aria-hidden="true" className="inline-block h-[1.12em] leading-[1.12em]">
            {c}
          </span>
        ),
      )}
    </span>
  );
}
