import { useEffect, useRef, useState } from "react";
import { count, zulu } from "@/lib/format";
import { asset } from "../data/assets";
import { HERO_LINES } from "../data/lineart";
import { nearestObs } from "../data/model";
import { useStory } from "../data/context";
import { gsap, MEDIA, PLOTTED, prefersReducedMotion, UNPLOTTED, useGSAP } from "../motion/gsap";
import { PIN_PRIORITY } from "../motion/useAutoRefresh";
import { Pending } from "../ui";
import { Rain } from "./Rain";

/**
 * Drawing → photograph, belgradearbor-style but with our own render: the Blender line art plots itself
 * stroke by stroke, then the Cycles render from the very same camera washes in from the nose. Rain falls
 * on a canvas over it and the camera drifts slowly while the section is on screen. The clock, the METAR
 * and the counts are the API's.
 */
export function Interlude() {
  const story = useStory();
  const root = useRef<HTMLElement>(null);
  const rainRef = useRef<HTMLCanvasElement>(null);
  const f = story.focus?.flight;
  const std = f?.sched_dep ?? null;
  const obs = std ? nearestObs(story.run?.metar, std) : null;
  const operated = story.run?.counters.operated;
  const win = story.window;
  // A portrait phone shows a slice of the 16:9 render: keep the nose (left), and the line art with it.
  const [narrow, setNarrow] = useState(() => window.matchMedia("(max-aspect-ratio: 1/1)").matches);
  useEffect(() => {
    const mq = window.matchMedia("(max-aspect-ratio: 1/1)");
    const on = () => setNarrow(mq.matches);
    mq.addEventListener("change", on);
    return () => mq.removeEventListener("change", on);
  }, []);

  // Rain runs only while the section is on screen; under reduced motion it is one still frame.
  useEffect(() => {
    const el = root.current;
    const canvas = rainRef.current;
    if (!el || !canvas) return;
    const rain = new Rain(canvas);
    const still = prefersReducedMotion();
    const size = () => {
      rain.setSize(el.clientWidth, el.clientHeight);
      if (still) rain.frame(0);
    };
    size();
    const ro = new ResizeObserver(size);
    ro.observe(el);
    const io = new IntersectionObserver(([e]) => (e.isIntersecting && !still ? rain.start() : rain.stop()));
    io.observe(el);
    return () => {
      rain.stop();
      ro.disconnect();
      io.disconnect();
    };
  }, []);

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
          // rain is already falling across the drawing, heavier once the render is in
          .fromTo(".il-rain", { opacity: 0 }, { opacity: 0.5, duration: 0.8 }, 0.2)
          .to(".il-rain", { opacity: 1, duration: 1.2 }, 4.6)
          .fromTo(".il-copy > *", { opacity: 0, y: 18 }, { opacity: 1, y: 0, duration: 0.8, stagger: 0.25, ease: "power3.out" }, 5.4)
          .to({}, { duration: 0.8 });
      });
    },
    { scope: root },
  );

  return (
    <section ref={root} aria-label={`${f?.aircraft ?? "The aircraft"} on stand at Dublin`} data-section="interlude" className="relative h-svh overflow-hidden bg-navy-950">
      {/* the render and its line art drift together, slowly, like a held camera */}
      <div className="story-drift absolute inset-0">
        {/* the render, revealed by a soft radial wash centred on the nose */}
        <img
          src={asset("ns31-render-2560.webp")}
          srcSet={`${asset("ns31-render-1280.webp")} 1280w, ${asset("ns31-render-2560.webp")} 2560w, ${asset("ns31-render.webp")} 3840w`}
          sizes="(max-aspect-ratio: 16/9) 178vh, 100vw"
          loading="lazy"
          decoding="async"
          alt={`Rendering of Northstar\u2019s A321 ${f?.aircraft ?? ""} parked on a wet stand at Dublin, in the rain`}
          className="il-img absolute inset-0 h-full w-full object-cover [@media(max-aspect-ratio:1/1)]:object-left"
          style={{
            ["--r" as string]: "175%",
            maskImage: "radial-gradient(circle at 22% 46%, #000 calc(var(--r) - 22%), transparent var(--r))",
            WebkitMaskImage: "radial-gradient(circle at 22% 46%, #000 calc(var(--r) - 22%), transparent var(--r))",
          }}
        />
        <svg className="il-lines pointer-events-none absolute inset-0 h-full w-full motion-reduce:opacity-[0.12]" viewBox="0 0 2560 1440" preserveAspectRatio={narrow ? "xMinYMid slice" : "xMidYMid slice"} aria-hidden="true">
          {HERO_LINES.map((d, i) => (
            <path key={i} className="il-line" d={d} fill="none" stroke="#e9edf2" strokeWidth={2.2} strokeLinecap="round" strokeLinejoin="round" {...PLOTTED} />
          ))}
        </svg>
      </div>
      <canvas ref={rainRef} className="il-rain pointer-events-none absolute inset-0 h-full w-full opacity-0 mix-blend-screen motion-reduce:opacity-80" aria-hidden="true" />
      <div className="pointer-events-none absolute inset-0 bg-gradient-to-t from-navy-950 via-navy-950/5 to-navy-950/50" />
      <div className="il-copy absolute inset-x-0 bottom-0 px-5 pb-16 md:px-16 md:pb-24">
        <p className="font-mono text-[12px] text-cloud-400 md:text-[13.5px]">{obs ? obs.raw : <Pending ch={36} />}</p>
        <h2 className="text-balance display mt-5 max-w-[18ch] text-[clamp(38px,5.2vw,92px)] text-cloud-50">
          At {std ? zulu(std) : <Pending ch={5} />}, {f?.aircraft ?? "the aircraft"} was still on stand.
        </h2>
        <p className="mt-5 max-w-[50ch] text-[16.5px] leading-relaxed text-cloud-300 md:text-[19px]">
          The storm window had closed at {win ? zulu(win.end) : <Pending ch={5} />}, and {operated !== undefined ? count(operated) : <Pending ch={2} />} Northstar departures flew after it. {f?.aircraft ?? "The aircraft"} needed a new pump, so {f?.number ?? "the flight"} was cancelled and its {f ? count(f.pax) : <Pending ch={3} />} passengers are owed compensation.
        </p>
      </div>
    </section>
  );
}
