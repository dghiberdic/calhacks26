import { lazy, Suspense, useEffect, useRef, useState } from "react";
import { zulu, zuluDay } from "@/lib/format";
import { cn } from "@/lib/utils";
import { asset } from "../data/assets";
import { SIDE_LINES, SIDE_VIEW, TOP_LINES, TOP_VIEW } from "../data/lineart";
import { useStory } from "../data/context";
import { gsap, MEDIA, PLOTTED, prefersReducedMotion, UNPLOTTED, useGSAP } from "../motion/gsap";
import { PIN_PRIORITY } from "../motion/useAutoRefresh";
import { Contained, Pending } from "../ui";
import type { AircraftProgress } from "./AircraftScene";
import { A321, HYDRAULICS, LEAK, type HydSystem } from "./hydraulics";

const AircraftScene = lazy(() => import("./AircraftScene"));
const INK = "#e8f0fa";
const MONTHS = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"];
const stamp = (d: Date) => `${d.getUTCDate()} ${MONTHS[d.getUTCMonth()]} ${String(d.getUTCHours()).padStart(2, "0")}:${String(d.getUTCMinutes()).padStart(2, "0")}Z`;
const HYD_COLOR: Record<HydSystem, string> = { green: "var(--hyd-green)", blue: "var(--hyd-blue)", yellow: "var(--hyd-yellow)" };

/** "At 21:40Z on 23 Jan, EI-NSB's engine-2 pump …" (time and tail from the API). */
function Copy({ log, reg }: { log: ReturnType<typeof useStory>["log"]; reg: string | null }) {
  return (
    <>
      {log?.at ? (
        <>
          At <span className="figure">{zulu(log.at.toISOString())}</span> on {zuluDay(log.at.toISOString()).split(" ").slice(0, 2).join(" ")},{" "}
        </>
      ) : null}
      {reg ?? "the aircraft"}&rsquo;s engine-2 pump was leaking yellow-system fluid beyond the maintenance manual&rsquo;s limit. With no MEL relief, it could not fly. Under EU261, a technical fault is not an extraordinary circumstance.
    </>
  );
}

/**
 * The aircraft as evidence. A cyanotype drawing plots itself, the three hydraulic systems trace in,
 * and the yellow system's engine-2 pump pulses next to the tech-log entry from the night before.
 * Then the drawing hands over to the real-time model from the same camera: it inks in and the camera
 * walks around the nose to the leaking engine. If the 3D can't load, the Cycles render stands in.
 */
export function Blueprint() {
  const story = useStory();
  const root = useRef<HTMLElement>(null);
  const column = useRef<HTMLDivElement>(null);
  const sideRef = useRef<SVGSVGElement>(null);
  const progress = useRef<AircraftProgress>({ sweep: 0, orbit: 0, lines: 1, leak: 0, show: 0 });
  const [near, setNear] = useState(false);
  const still = prefersReducedMotion();
  const log = story.log;
  const reg = story.focus?.flight.aircraft ?? story.file?.flight.aircraft ?? null;
  // What the leak is, in the tech log's own terms: engine 2's driven pump, yellow system, case drain port.
  const leak = { title: `${LEAK.label} · case drain leak`, detail: `Yellow system${log?.at ? ` · logged ${stamp(log.at)}` : ""}` };

  // Mount the WebGL scene only when the section is close (and never with reduced motion).
  useEffect(() => {
    const el = root.current;
    if (!el || still) return;
    const io = new IntersectionObserver(([e]) => e.isIntersecting && setNear(true), { rootMargin: "120% 0px" });
    io.observe(el);
    return () => io.disconnect();
  }, [still]);

  useGSAP(
    () => {
      const mm = gsap.matchMedia();
      mm.add({ motion: MEDIA.motion, narrow: MEDIA.narrow }, (ctx) => {
        if (!ctx.conditions?.motion) return;
        const tl = gsap.timeline({
          defaults: { ease: "plotter" },
          scrollTrigger: { trigger: root.current, start: "top top", end: "+=280%", scrub: 0.7, pin: true, anticipatePin: 1, invalidateOnRefresh: true, refreshPriority: PIN_PRIORITY.blueprint },
        });
        tl.from(".bp-frame", { ...UNPLOTTED, duration: 0.5, ease: "power1.inOut" })
          .from(".bp-side-line", { ...UNPLOTTED, duration: 0.7, stagger: { amount: 1.5 } }, 0.2)
          .from(".bp-dim", { opacity: 0, duration: 0.4, stagger: 0.1 }, 1.4)
          .from(".bp-plan-line", { ...UNPLOTTED, duration: 0.6, stagger: { amount: 1.1 } }, 1.6)
          .from(".bp-hyd-blue", { ...UNPLOTTED, duration: 0.8 }, 2.6)
          .from(".bp-hyd-green", { ...UNPLOTTED, duration: 0.8 }, 2.75)
          .from(".bp-hyd-yellow", { ...UNPLOTTED, duration: 0.8 }, 2.9)
          .from(".bp-legend", { opacity: 0, y: 8, duration: 0.4 }, 3.1)
          .from(".bp-flows", { opacity: 0, duration: 0.5 }, 3.2)
          .to(".bp-hyd-blue, .bp-hyd-green", { opacity: 0.22, duration: 0.4 }, 3.6)
          .from(".bp-leak", { scale: 0, opacity: 0, transformOrigin: "50% 50%", duration: 0.4, ease: "back.out(3)" }, 3.7)
          .from(".bp-log", { opacity: 0, x: -16, duration: 0.5, ease: "power3.out" }, 3.9)
          .from(".bp-log-line", { opacity: 0, duration: 0.25, stagger: 0.12 }, 4.0);

        // The drawing hands over to the real aircraft: same camera, then it inks in and turns.
        const centre = () => {
          const col = column.current;
          const svg = sideRef.current;
          if (!col || !svg) return 0;
          return col.clientHeight / 2 - (svg.getBoundingClientRect().top - col.getBoundingClientRect().top + svg.clientHeight / 2);
        };
        const p = progress.current;
        tl.addLabel("three", 5.0)
          .to(".bp-plan, .bp-evidence", { opacity: 0, duration: 0.5, ease: "power1.out" }, "three")
          .to(".bp-side", { y: centre, duration: 0.8, ease: "power2.inOut" }, "three")
          .to(".bp-canvas", { opacity: 1, duration: 0.4, ease: "none" }, "three+=0.7")
          .to(p, { show: 1, duration: 0.4, ease: "none" }, "three+=0.7")
          .to(".bp-side", { opacity: 0, duration: 0.4, ease: "none" }, "three+=1.0")
          .to(p, { sweep: 1, duration: 2.4, ease: "power1.inOut" }, "three+=1.2")
          .to(p, { orbit: 1, duration: 2.6, ease: "power2.inOut" }, "three+=1.6")
          .to(root.current, { backgroundColor: "#080d17", duration: 1.8, ease: "none" }, "three+=1.3")
          .to(".bp-grid, .bp-grain", { opacity: 0, duration: 1.2, ease: "none" }, "three+=1.3")
          .to(p, { lines: 0, duration: 0.6, ease: "none" }, "three+=3.4")
          .to(p, { leak: 1, duration: 0.3, ease: "none" }, "three+=3.7")
          .fromTo(".bp-caption-3d", { opacity: 0, y: 8 }, { opacity: 1, y: 0, duration: 0.4 }, "three+=3.8")
          .to({}, { duration: 0.6 });
        if (ctx.conditions.narrow) {
          // One slot on a phone: the copy gives way to the log, returns with the 3D, then to the caption.
          tl.to(".bp-copy", { opacity: 0, duration: 0.3 }, 3.8)
            .to(".bp-copy", { opacity: 1, duration: 0.4 }, "three+=0.4")
            .to(".bp-copy", { opacity: 0, duration: 0.3 }, "three+=3.5");
        }
      });
      if (!prefersReducedMotion()) gsap.to(".bp-leak-pulse", { scale: 2.6, opacity: 0, transformOrigin: "50% 50%", duration: 1.6, repeat: -1, ease: "power2.out" });
    },
    { scope: root },
  );

  return (
    <section
      ref={root}
      aria-label={`${reg ?? "The aircraft"} and its tech log`} data-section="blueprint"
      className="relative flex min-h-svh flex-col justify-center overflow-hidden bg-[var(--story-cyan)] py-12 text-[var(--story-ink)] max-lg:py-6 [@media(max-height:760px)]:py-6"
    >
      {/* the light table: the drafting grid slides one square diagonally, slowly, forever (motion only) */}
      <div className="bp-grid story-grid story-grid-drift pointer-events-none absolute -inset-[120px] opacity-[0.22]" aria-hidden="true" />
      <svg className="bp-grain story-grain pointer-events-none absolute -inset-[6%] h-[112%] w-[112%] opacity-[0.2] mix-blend-overlay" aria-hidden="true">
        <filter id="bp-grain">
          <feTurbulence type="fractalNoise" baseFrequency="0.8" numOctaves="2" stitchTiles="stitch" />
          <feColorMatrix values="0 0 0 0 1  0 0 0 0 1  0 0 0 0 1  0 0 0 0.6 0" />
        </filter>
        <rect width="100%" height="100%" filter="url(#bp-grain)" />
      </svg>

      <div className="relative mx-auto grid w-full max-w-[1500px] grid-cols-1 gap-10 px-5 max-lg:gap-5 md:px-12 lg:grid-cols-[minmax(0,1fr)_380px]">
        <div ref={column} className="relative">
          <div className="bp-canvas pointer-events-none absolute inset-0 opacity-0">
            {near ? (
              <Contained
                fallback={
                  <div className="absolute inset-0 grid place-items-center">
                    <img src={asset("ns31-render-2560.webp")} alt="Rendering of EI-NSB on a wet stand at Dublin" className="aspect-video w-full rounded-xl object-cover shadow-[0_30px_80px_-30px_rgba(0,0,0,0.8)]" />
                  </div>
                }
              >
                <Suspense fallback={null}>
                  <AircraftScene progress={progress} leak={leak} fallback={asset("ns31-render-2560.webp")} className="absolute inset-0" />
                </Suspense>
              </Contained>
            ) : null}
          </div>

          {/* port elevation */}
          <svg ref={sideRef} viewBox="-3 -13.4 53 15.6" className="bp-side relative w-full" role="img" aria-label={`Port elevation of the Airbus A321 ${reg ?? ""}, ${A321.length.toFixed(2)} metres long and ${A321.height.toFixed(2)} metres tall.`}>
            <path className="bp-frame" d="M-2.6,-13.1 H49.6 V1.9 H-2.6 Z" fill="none" stroke={INK} strokeOpacity="0.5" strokeWidth="0.04" {...PLOTTED} />
            <g transform={`scale(${SIDE_VIEW.mpp}) translate(${-SIDE_VIEW.noseX} ${-SIDE_VIEW.groundY})`}>
              {SIDE_LINES.map((d, i) => (
                <path key={i} className="bp-side-line" d={d} fill="none" stroke={INK} strokeWidth={2.4} strokeLinejoin="round" strokeLinecap="round" {...PLOTTED} />
              ))}
            </g>
            <g className="bp-dim" stroke={INK} strokeWidth="0.03" fill="none" opacity="0.8">
              <path d={`M0,0.6 L0,1.7 M${A321.length},0.6 L${A321.length},1.7 M0,1.35 L${A321.length},1.35`} />
              <path d={`M-0.25,1.6 L0.25,1.1 M${A321.length - 0.25},1.6 L${A321.length + 0.25},1.1`} />
            </g>
            <text className="bp-dim font-mono" x={A321.length / 2} y="2.05" textAnchor="middle" fill={INK} style={{ fontSize: 0.62 }}>
              {A321.length.toFixed(2)} m
            </text>
            <g className="bp-dim" stroke={INK} strokeWidth="0.03" fill="none" opacity="0.8">
              <path d={`M45.4,0 L46.9,0 M43.2,-${A321.height} L46.9,-${A321.height} M46.5,0 L46.5,-${A321.height}`} />
            </g>
            <text className="bp-dim font-mono" x="47.1" y="-5.7" fill={INK} style={{ fontSize: 0.62 }}>
              {A321.height.toFixed(2)} m
            </text>
            <text className="bp-dim font-mono" x="-2.2" y="-12.2" fill={INK} fillOpacity="0.7" style={{ fontSize: 0.5, letterSpacing: "0.08em" }}>
              PORT ELEVATION{story.aircraftType ? ` · ${story.aircraftType}` : ""}{reg ? ` · ${reg}` : ""}
            </text>
            <path d="M-2.4,0 L49.4,0" stroke={INK} strokeOpacity="0.4" strokeWidth="0.03" strokeDasharray="0.5 0.3" className="bp-dim" />
          </svg>

          {/* plan view with the hydraulic systems */}
          <svg viewBox="-2 -19.4 49 38.8" className="bp-plan mx-auto mt-4 max-h-[46svh] w-[76%] max-lg:max-h-[25svh]" role="img" aria-label="Plan view with the three hydraulic systems. The yellow system's engine-2 driven pump, on the starboard engine, is marked as the leak.">
            <g transform={`scale(${TOP_VIEW.mpp}) translate(${-TOP_VIEW.noseX} ${-TOP_VIEW.centreY})`}>
              {TOP_LINES.map((d, i) => (
                <path key={i} className="bp-plan-line" d={d} fill="none" stroke={INK} strokeOpacity={0.9} strokeWidth={2.6} strokeLinejoin="round" {...PLOTTED} />
              ))}
            </g>
            {(["blue", "green", "yellow"] as const).map((s) => (
              <path key={s} className={`bp-hyd-${s}`} d={HYDRAULICS[s].d} fill="none" stroke={HYD_COLOR[s]} strokeWidth={s === LEAK.system ? 0.22 : 0.17} strokeLinecap="round" strokeLinejoin="round" {...PLOTTED} />
            ))}
            {/* fluid moving through each system; the leaking yellow system runs weak (motion only) */}
            <g className="bp-flows motion-reduce:hidden" aria-hidden="true">
              {(["blue", "green", "yellow"] as const).map((s) => (
                <path key={s} className={s === LEAK.system ? "bp-flow bp-flow-weak" : "bp-flow"} d={HYDRAULICS[s].d} fill="none" stroke={HYD_COLOR[s]} strokeWidth={0.34} strokeLinecap="round" strokeDasharray="0.01 1.9" />
              ))}
            </g>
            <g className="bp-leak">
              <circle className="bp-leak-pulse" cx={LEAK.x} cy={LEAK.y} r="0.9" fill="none" stroke="var(--color-notweather)" strokeWidth="0.12" />
              <circle cx={LEAK.x} cy={LEAK.y} r="0.55" fill="var(--color-notweather)" />
              <path d={`M${LEAK.x - 1.1},${LEAK.y - 0.6} L${LEAK.x - 2.6},${LEAK.y - 2.2} L${LEAK.x - 5.4},${LEAK.y - 2.2}`} fill="none" stroke="#ffb3a1" strokeWidth="0.06" />
              <text x={LEAK.x - 5.7} y={LEAK.y - 1.95} textAnchor="end" fill="#ffb3a1" className="font-mono" style={{ fontSize: 0.9 }}>
                {LEAK.label}
                <tspan x={LEAK.x - 5.7} dy="1.15" fill="#ffb3a1" fillOpacity="0.75" style={{ fontSize: 0.72 }}>
                  CASE DRAIN LEAK
                </tspan>
              </text>
            </g>
            <text className="bp-dim font-mono" x="-1.6" y="-17.9" fill={INK} fillOpacity="0.7" style={{ fontSize: 0.85, letterSpacing: "0.08em" }}>
              PLAN · HYDRAULIC SYSTEMS
            </text>
            <text className="bp-dim font-mono" x="27.6" y="-18.2" fill={INK} fillOpacity="0.5" style={{ fontSize: 0.75 }}>
              STBD
            </text>
            <text className="bp-dim font-mono" x="27.6" y="19.0" fill={INK} fillOpacity="0.5" style={{ fontSize: 0.75 }}>
              PORT
            </text>
          </svg>
        </div>

        <aside className="flex flex-col justify-center gap-8">
          <div>
            <h2 className="text-balance display text-[clamp(36px,3.9vw,64px)] text-white">
              A hydraulic leak grounded <span className="whitespace-nowrap">{reg ?? "the aircraft"}</span>.
            </h2>
            <p className="bp-copy mt-5 max-w-[36ch] text-[16.5px] leading-relaxed text-[var(--story-ink-soft)] max-lg:motion-safe:hidden">
              <Copy log={log} reg={reg} />
            </p>
            {/* The log and the 3D caption share one slot and take turns; on a phone the copy joins them, so the pinned section fits. */}
            <div className="mt-7 grid max-lg:mt-4">
              <p className="bp-copy max-w-[36ch] text-[15.5px] leading-relaxed text-[var(--story-ink-soft)] [grid-area:1/1] lg:hidden motion-reduce:hidden">
                <Copy log={log} reg={reg} />
              </p>
              <div className="bp-evidence flex flex-col gap-6 self-start [grid-area:1/1] max-lg:gap-3">
                <div className="bp-legend flex flex-wrap gap-x-5 gap-y-1 text-[13px] text-[var(--story-ink-soft)] max-lg:motion-safe:hidden">
                  {(["yellow", "green", "blue"] as const).map((s) => (
                    <span key={s} className={cn("flex items-center gap-2", s !== LEAK.system && "opacity-70")}>
                      <span className="h-[3px] w-5 rounded-full" style={{ background: HYD_COLOR[s] }} />
                      {HYDRAULICS[s].label}
                      {s === LEAK.system ? <span className="font-mono text-[11px] text-[#ffb3a1]">{HYDRAULICS[s].pump}</span> : null}
                    </span>
                  ))}
                </div>
                <figure className="bp-log rounded-md border border-[#e8f0fa]/25 bg-[var(--story-cyan-deep)]/85 p-5 backdrop-blur-sm max-lg:p-3.5 [@media(max-height:760px)]:p-4">
                  <figcaption className="mb-3 flex justify-between gap-3 text-[13px] text-[var(--story-ink-soft)] max-lg:mb-2">
                    <span>Technical log{reg ? `, ${reg}` : ""}</span>
                    {log?.ata ? <span className="font-mono">ATA {log.ata}</span> : null}
                  </figcaption>
                  <div className="font-mono text-[13px] leading-[1.6] text-white max-lg:text-[11.5px] [@media(max-height:760px)]:text-[12px]">
                    {log?.lines.length ? (
                      log.lines.map((l, i) => (
                        <p key={i} className={cn("bp-log-line", i === 0 && "text-[#ffb3a1]", /ENG 2|HYD Y/.test(l) && i > 0 && "text-[var(--hyd-yellow)]")}>
                          {l}
                        </p>
                      ))
                    ) : (
                      <p className="bp-log-line">
                        <Pending ch={28} />
                      </p>
                    )}
                  </div>
                </figure>
              </div>
              <p className="bp-caption-3d max-w-[34ch] self-start text-[15px] leading-relaxed text-[var(--story-ink-soft)] opacity-0 [grid-area:1/1] motion-reduce:hidden">
                The same A321 in 3D. The leak is at the engine-2 driven pump, low on the starboard engine.
              </p>
            </div>
          </div>
        </aside>
      </div>
    </section>
  );
}
