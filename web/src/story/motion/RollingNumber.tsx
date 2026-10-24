import { useRef } from "react";
import { cn } from "@/lib/utils";
import { gsap, prefersReducedMotion, useGSAP } from "./gsap";

/**
 * Odometer figures: each digit is a 0–9 drum that rolls into place when scrolled into view.
 * Non-digits (€ , . ×) sit still. Screen readers get the formatted value. `text` is already
 * formatted (lib/format), so the roll never changes what the number says.
 */
export function RollingNumber({ text, className, delay = 0, start = "top 85%" }: { text: string; className?: string; delay?: number; start?: string }) {
  const root = useRef<HTMLSpanElement>(null);

  useGSAP(
    () => {
      const drums = gsap.utils.toArray<HTMLElement>(".rn-drum", root.current);
      const final = (_: number, el: HTMLElement) => -Number(el.dataset.d) * 10;
      if (prefersReducedMotion()) return void gsap.set(drums, { yPercent: final });
      gsap.set(drums, { yPercent: 0 });
      gsap.to(drums, {
        yPercent: final,
        duration: 1.4,
        ease: "power3.inOut",
        stagger: { each: 0.06, from: "end" },
        delay,
        scrollTrigger: { trigger: root.current, start, toggleActions: "play none none reverse" },
      });
    },
    { scope: root, dependencies: [text], revertOnUpdate: true },
  );

  return (
    <span ref={root} className={cn("figure inline-flex overflow-hidden leading-[1.12em]", className)}>
      <span className="sr-only">{text}</span>
      {/* drums and separators are drawn by CSS (story.css), so the page's text reads the number once */}
      {Array.from(text).map((c, i) =>
        /\d/.test(c) ? (
          <span key={i} aria-hidden="true" className="relative inline-block h-[1.12em] overflow-hidden">
            <span className="rn-drum block leading-[1.12em]" data-d={c} />
          </span>
        ) : (
          <span key={i} aria-hidden="true" className="rn-glyph inline-block h-[1.12em] whitespace-pre leading-[1.12em]" data-c={c} />
        ),
      )}
    </span>
  );
}
