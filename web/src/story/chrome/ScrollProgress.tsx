import { useRef } from "react";
import { ScrollTrigger, useGSAP } from "../motion/gsap";

/** A thin "you are here" rail on the right edge; difference-blended so it reads on night and paper. */
export function ScrollProgress() {
  const bar = useRef<HTMLSpanElement>(null);
  useGSAP(() => {
    const st = ScrollTrigger.create({
      start: 0,
      end: "max",
      onUpdate: (self) => {
        if (bar.current) bar.current.style.transform = `scaleY(${self.progress})`;
      },
    });
    return () => st.kill();
  });
  return (
    <div aria-hidden="true" className="pointer-events-none fixed right-4 top-1/2 z-40 hidden h-28 w-[3px] -translate-y-1/2 overflow-hidden rounded-full bg-white/25 mix-blend-difference md:block">
      <span ref={bar} className="block h-full w-full origin-top scale-y-0 rounded-full bg-white" />
    </div>
  );
}
