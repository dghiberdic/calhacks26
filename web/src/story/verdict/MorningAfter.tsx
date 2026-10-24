import { useRef } from "react";
import { zuluDay } from "@/lib/format";
import { useStory } from "../data/context";
import { gsap, MEDIA, useGSAP } from "../motion/gsap";

/** Night turns to paper; the line's ink follows so it never loses contrast. The time is when the re-check ran. */
export function MorningAfter() {
  const story = useStory();
  const root = useRef<HTMLElement>(null);
  const knownAt = story.focus?.decision?.known_at ?? story.file?.decision.known_at ?? null;

  useGSAP(
    () => {
      const mm = gsap.matchMedia();
      mm.add(MEDIA.motion, () => {
        gsap.fromTo(".ma-text", { color: "#f4f6f9" }, { color: "#0d1524", ease: "none", scrollTrigger: { trigger: root.current, start: "35% top", end: "62% top", scrub: true } });
        gsap.from(".ma-text", { opacity: 0, y: 30, duration: 1.2, ease: "power3.out", scrollTrigger: { trigger: root.current, start: "top 40%" } });
      });
    },
    { scope: root },
  );

  return (
    <section
      ref={root}
      aria-label="The morning after" data-section="morning"
      className="relative h-[170vh] motion-reduce:h-[70vh]"
      style={{ background: "linear-gradient(to bottom, #080d17 0%, #0d1524 22%, #33445e 50%, #c8d0db 78%, #f4f6f9 100%)" }}
    >
      <div className="sticky top-0 flex h-svh items-center justify-center px-5 motion-reduce:static motion-reduce:h-full motion-reduce:items-end motion-reduce:pb-[6vh]">
        <p className="ma-text display text-center text-[clamp(40px,6.4vw,112px)] text-cloud-50 motion-reduce:text-navy-900">
          {knownAt ? (
            <>
              <span className="figure block text-[0.42em] font-medium tracking-normal">Re-checked {zuluDay(knownAt)}</span>
            </>
          ) : null}
          The morning after.
        </p>
      </div>
    </section>
  );
}
