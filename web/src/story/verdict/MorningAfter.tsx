import { useRef } from "react";
import { count, zuluDay } from "@/lib/format";
import { asset } from "../data/assets";
import { useStory } from "../data/context";
import { gsap, MEDIA, useGSAP } from "../motion/gsap";
import { Pending } from "../ui";

/** Night turns to paper; the line's ink follows so it never loses contrast. The time is when the re-check ran, the count is the run's. */
export function MorningAfter() {
  const story = useStory();
  const root = useRef<HTMLElement>(null);
  const knownAt = story.focus?.decision?.known_at ?? story.file?.decision.known_at ?? null;
  const cancelled = story.run?.counters.cancelled;

  useGSAP(
    () => {
      const mm = gsap.matchMedia();
      mm.add(MEDIA.motion, () => {
        gsap.fromTo(".ma-text", { color: "#f4f6f9" }, { color: "#0d1524", ease: "none", scrollTrigger: { trigger: root.current, start: "35% top", end: "62% top", scrub: true } });
        // the storm clears and the sun comes up as you scroll
        gsap.fromTo(".ma-clouds", { opacity: 1 }, { opacity: 0.25, ease: "none", scrollTrigger: { trigger: root.current, start: "top top", end: "bottom bottom", scrub: true } });
        gsap.fromTo(".ma-glow", { opacity: 0, yPercent: 30 }, { opacity: 1, yPercent: 0, ease: "none", scrollTrigger: { trigger: root.current, start: "20% top", end: "bottom bottom", scrub: true } });
        gsap.from(".ma-text", { opacity: 0, y: 30, duration: 1.2, ease: "power3.out", scrollTrigger: { trigger: root.current, start: "top 40%" } });
      });
    },
    { scope: root },
  );

  return (
    <section
      ref={root}
      aria-label="The re-check, the next morning" data-section="morning"
      className="relative h-[170vh] overflow-x-clip motion-reduce:h-[70vh]"
      style={{ background: "linear-gradient(to bottom, #080d17 0%, #0d1524 22%, #33445e 50%, #c8d0db 78%, #f4f6f9 100%)" }}
    >
      <div className="sticky top-0 flex h-svh items-center justify-center overflow-hidden px-5 motion-reduce:static motion-reduce:h-full motion-reduce:items-end motion-reduce:pb-[6vh]">
        {/* the sun under the horizon, and what is left of the storm drifting off east */}
        <div className="ma-glow pointer-events-none absolute inset-x-0 bottom-0 h-[70%] opacity-0 motion-reduce:opacity-60" style={{ background: "radial-gradient(60% 70% at 50% 100%, rgba(255,214,170,0.55), rgba(255,226,196,0.18) 45%, transparent 75%)" }} aria-hidden="true" />
        <div className="ma-clouds pointer-events-none absolute inset-0" aria-hidden="true">
          <div className="story-clouds absolute left-0 top-[6%] h-[46%] w-[200%] opacity-[0.26]" style={{ backgroundImage: `url(${asset("clouds.webp")})` }} />
          <div className="story-clouds story-clouds-slow absolute left-0 top-[38%] h-[52%] w-[200%] opacity-[0.16] [transform:scaleX(-1)]" style={{ backgroundImage: `url(${asset("clouds.webp")})` }} />
        </div>
        <p className="ma-text text-balance display text-center text-[clamp(40px,6.4vw,112px)] text-cloud-50 motion-reduce:text-navy-900">
          {knownAt ? <span className="figure block text-[0.36em] font-medium tracking-normal">{zuluDay(knownAt)}, the next morning</span> : null}
          StormCheck <span className="whitespace-nowrap">re-checks</span> all {cancelled !== undefined ? count(cancelled) : <Pending ch={2} />}.
        </p>
      </div>
    </section>
  );
}
