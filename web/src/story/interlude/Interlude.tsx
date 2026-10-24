import { useRef } from "react";
import { count, zulu } from "@/lib/format";
import { asset } from "../data/assets";
import { HERO_LINES } from "../data/lineart";
import { nearestObs } from "../data/model";
import { useStory } from "../data/context";
import { gsap, MEDIA, PLOTTED, ScrollTrigger, UNPLOTTED, useGSAP } from "../motion/gsap";
import { PIN_PRIORITY } from "../motion/useAutoRefresh";
import { Pending } from "../ui";

/**
 * Drawing → photograph, belgradearbor-style but with our own render: the Blender line art plots itself
 * stroke by stroke, then the Cycles render from the very same camera washes in from the nose. The
 * clock, the METAR and the counts are the API's.
 */
export function Interlude() {
  const story = useStory();
  const root = useRef<HTMLElement>(null);
  const rain = useRef<HTMLDivElement>(null);
  const f = story.focus?.flight;
  const std = f?.sched_dep ?? null;
  const obs = std ? nearestObs(story.run?.metar, std) : null;
  const operated = story.run?.counters.operated;
  const win = story.window;

  useGSAP(
    () => {
      const mm = gsap.matchMedia();
      mm.add(MEDIA.motion, () => {
        const tl = gsap.timeline({
          defaults: { ease: "none" },
          scrollTrigger: { trigger: root.current, start: "top top", end: "+=150%", scrub: 0.8, pin: true, anticipatePin: 1, refreshPriority: PIN_PRIORITY.interlude },
        });
        tl.from(".il-line", { ...UNPLOTTED, duration: 0.5, stagger: { amount: 3.2 }, ease: "plotter" }, 0)
          .fromTo(".il-img", { "--r": "0%" }, { "--r": "175%", duration: 3.2, ease: "power1.inOut" }, 3.0)
          .fromTo(".il-img", { scale: 1.06 }, { scale: 1, duration: 4, ease: "power1.out" }, 3.0)
          .to(".il-lines", { opacity: 0.12, duration: 1.6 }, 4.4)
          .fromTo(".il-rain", { opacity: 0 }, { opacity: 0.36, duration: 1.2 }, 5.2)
          .fromTo(".il-copy > *", { opacity: 0, y: 18 }, { opacity: 1, y: 0, duration: 0.8, stagger: 0.25, ease: "power3.out" }, 5.4)
          .to({}, { duration: 0.8 });
        // The rain only moves while the section is on screen (it's a compositor animation either way).
        ScrollTrigger.create({ trigger: root.current, start: "top bottom", end: "bottom top", onToggle: (self) => rain.current?.setAttribute("data-on", String(self.isActive)) });
      });
    },
    { scope: root },
  );

  return (
    <section ref={root} aria-label={`${f?.aircraft ?? "The aircraft"} on stand at Dublin`} data-section="interlude" className="relative h-svh overflow-hidden bg-navy-950">
      {/* the render, revealed by a soft radial wash centred on the nose */}
      <img
        src={asset("ns31-render.webp")}
        srcSet={`${asset("ns31-render-1280.webp")} 1280w, ${asset("ns31-render.webp")} 2560w`}
        sizes="100vw"
        alt={`Rendering of Northstar's A321 ${f?.aircraft ?? ""} parked on a wet stand at Dublin`}
        className="il-img absolute inset-0 h-full w-full object-cover"
        style={{
          ["--r" as string]: "175%",
          maskImage: "radial-gradient(circle at 22% 46%, #000 calc(var(--r) - 22%), transparent var(--r))",
          WebkitMaskImage: "radial-gradient(circle at 22% 46%, #000 calc(var(--r) - 22%), transparent var(--r))",
        }}
      />
      <svg className="il-lines pointer-events-none absolute inset-0 h-full w-full motion-reduce:opacity-[0.12]" viewBox="0 0 2560 1440" preserveAspectRatio="xMidYMid slice" aria-hidden="true">
        {HERO_LINES.map((d, i) => (
          <path key={i} className="il-line" d={d} fill="none" stroke="#e9edf2" strokeWidth={2.2} strokeLinecap="round" strokeLinejoin="round" {...PLOTTED} />
        ))}
      </svg>
      <div className="pointer-events-none absolute inset-0 overflow-hidden" aria-hidden="true">
        <div ref={rain} className="il-rain story-rain absolute inset-x-0 top-0 h-[200%] opacity-0 mix-blend-screen" style={{ backgroundImage: `url(${asset("rain.webp")})` }} />
      </div>
      <div className="pointer-events-none absolute inset-0 bg-gradient-to-t from-navy-950 via-navy-950/5 to-navy-950/50" />
      <div className="il-copy absolute inset-x-0 bottom-0 px-5 pb-16 md:px-16 md:pb-24">
        <p className="font-mono text-[12px] text-cloud-400 md:text-[13.5px]">{obs ? obs.raw : <Pending ch={36} />}</p>
        <h2 className="display mt-5 max-w-[16ch] text-[clamp(40px,6vw,104px)] text-cloud-50">
          {std ? zulu(std) : <Pending ch={5} />}. Still on stand.
        </h2>
        <p className="mt-5 max-w-[46ch] text-[16.5px] leading-relaxed text-cloud-300 md:text-[19px]">
          The storm window closed at {win ? zulu(win.end) : <Pending ch={5} />} and {operated !== undefined ? count(operated) : <Pending ch={2} />} Northstar departures flew. {f?.aircraft ?? "The aircraft"} waited for a pump, with {f ? count(f.pax) : <Pending ch={3} />} passengers owed.
        </p>
      </div>
    </section>
  );
}
