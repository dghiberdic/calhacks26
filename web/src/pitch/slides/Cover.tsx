import { useEffect, useLayoutEffect, useRef, useState } from "react";
import { useReducedMotion } from "motion/react";
import { cn } from "@/lib/utils";
import { COVER_IMAGE_CREDIT, SEATS_LINE_PARTS } from "../copy";
import { Brand, Reveal, RevealGroup } from "../ui";
import { startCoverFlow, type FlowOptions } from "./coverFlow";

/**
 * Where Dublin (53.43°N, 6.27°W) falls on the cover. The image is a GIBS WMS export (equirectangular,
 * 48.5°W–8.4°E × 31.83°N–63.83°N, 3840×2160), laid on the 1920×1080 stage.
 */
const DUBLIN = { left: 1425, top: 351 };

/**
 * 3840 wide, so it stays sharp at DPR 2 and on a 4K projector. The grade (saturate 0.78, brightness 0.92) is
 * baked into the file, so no CSS filter; the left side, always under the navy, is softened to keep it ~1.2 MB.
 */
export const COVER_IMAGE = `${import.meta.env.BASE_URL}pitch/eowyn-2025-01-24.webp`;

/**
 * The camera, compositor only: it arrives pulled in and settles, then drifts between two framings for as long
 * as the cover is up. Scaled about the storm, so Dublin and the low stay in frame; every keyframe keeps the
 * image over the whole stage.
 */
const CAMERA_ORIGIN = "74% 26%";
const ARRIVE_FROM = "translate3d(0px, 0px, 0) scale(1.12)";
const DRIFT_A = "translate3d(0px, 0px, 0) scale(1.05)";
const DRIFT_B = "translate3d(-18px, 10px, 0) scale(1.09)";

/**
 * Éowyn's clouds turning about the low (north-west of Scotland in the frame), slowly: about 2 px a second
 * where the flow is fastest, at stage scale. Starts once the words have landed.
 */
const FLOW: FlowOptions = { center: [0.7734, 0.1991], r0: 0.11, spin: 0.01, drift: [0.0022, -0.0009], cycle: 5, easeIn: 3 };
const FLOW_AFTER_MS = 1900;

/** The moment, over the real storm: Éowyn on the morning it shut Dublin, from NASA's Terra satellite. */
export function Cover() {
  const reduce = useReducedMotion();
  const camera = useRef<HTMLDivElement>(null);
  const img = useRef<HTMLImageElement>(null);
  const canvas = useRef<HTMLCanvasElement>(null);
  const [loaded, setLoaded] = useState(false);
  const [flowing, setFlowing] = useState(false);

  // Already decoded (the deck preloads it): no fade.
  useLayoutEffect(() => {
    if (img.current?.complete && img.current.naturalWidth > 0) setLoaded(true);
  }, []);

  useEffect(() => {
    const el = camera.current;
    if (!el || reduce || typeof el.animate !== "function") return;
    const arrive = el.animate([{ transform: ARRIVE_FROM }, { transform: DRIFT_A }], { duration: 9000, easing: "cubic-bezier(0.22, 1, 0.36, 1)", fill: "forwards" });
    let drift: Animation | null = null;
    arrive.finished
      .then(() => {
        drift = el.animate([{ transform: DRIFT_A }, { transform: DRIFT_B }], { duration: 24000, easing: "cubic-bezier(0.45, 0, 0.55, 1)", iterations: Infinity, direction: "alternate" });
        arrive.cancel();
      })
      .catch(() => {});
    return () => {
      arrive.cancel();
      drift?.cancel();
    };
  }, [reduce]);

  useEffect(() => {
    const c = canvas.current;
    if (reduce || !loaded || !c || typeof WebGL2RenderingContext === "undefined" || typeof createImageBitmap !== "function") return;
    let stop: (() => void) | null = null;
    const timer = window.setTimeout(() => {
      stop = startCoverFlow(c, COVER_IMAGE, FLOW, { onStart: () => setFlowing(true), onFail: () => setFlowing(false) });
    }, FLOW_AFTER_MS);
    return () => {
      window.clearTimeout(timer);
      stop?.();
    };
  }, [reduce, loaded]);

  return (
    <div className="relative h-full w-full overflow-hidden bg-navy-950">
      {/* The storm and the pin move together, so the pin stays on Dublin. */}
      <div ref={camera} className="absolute inset-0 will-change-transform" style={{ transformOrigin: CAMERA_ORIGIN, transform: reduce ? undefined : ARRIVE_FROM }} data-testid="cover-camera">
        <img
          ref={img}
          src={COVER_IMAGE}
          alt="Storm Éowyn over Ireland and Britain on 24 January 2025, from NASA's Terra satellite"
          className={cn("absolute inset-0 h-full w-full object-cover", !reduce && "transition-opacity duration-[1200ms] ease-out", loaded ? "opacity-100" : "opacity-0")}
          decoding="async"
          draggable={false}
          onLoad={() => setLoaded(true)}
        />
        {reduce ? null : (
          <canvas ref={canvas} aria-hidden="true" className={cn("absolute inset-0 h-full w-full transition-opacity duration-700", flowing ? "opacity-100" : "opacity-0")} data-testid="cover-flow" />
        )}
        <div aria-hidden="true" className="absolute" style={DUBLIN}>
          <span className="absolute -left-[9px] -top-[9px] size-[18px] rounded-full shadow-[inset_0_0_0_2px_rgba(244,246,249,0.95),0_0_24px_rgba(8,13,23,0.6)]" />
          <span className="absolute -left-[3px] -top-[3px] size-[6px] rounded-full bg-cloud-50" />
          <span className="absolute left-[20px] top-[-12px] font-mono text-[17px] tracking-[0.16em] text-cloud-50 [text-shadow:0_1px_10px_rgba(8,13,23,0.95)]">DUBLIN</span>
        </div>
      </div>
      {/* Grade: navy behind the words, the storm left bright on the right. Decoration only. */}
      <div aria-hidden="true" className="absolute inset-0 bg-[linear-gradient(90deg,rgba(8,13,23,0.97)_0%,rgba(8,13,23,0.9)_30%,rgba(8,13,23,0.58)_50%,rgba(8,13,23,0.16)_74%,rgba(8,13,23,0.06)_100%)]" />
      <div aria-hidden="true" className="absolute inset-0 bg-[linear-gradient(0deg,rgba(8,13,23,0.92)_0%,rgba(8,13,23,0.35)_22%,rgba(8,13,23,0)_42%)]" />
      <div aria-hidden="true" className="absolute inset-0 bg-[linear-gradient(180deg,rgba(8,13,23,0.55)_0%,rgba(8,13,23,0)_22%)]" />

      <RevealGroup className="relative flex h-full flex-col px-[112px] pb-[72px] pt-[76px]" stagger={0} delay={0}>
        <Reveal delay={0.05}>
          <Brand size="lg" />
        </Reveal>
        <div className="mt-auto">
          {/* Two beats: the code everyone typed, then what the logs say. Then who it is for. */}
          <h2 className="display text-[156px] leading-[0.9] text-cloud-50">
            <Reveal as="span" className="block" delay={0.2}>
              Not weather.{" "}
            </Reveal>
            <Reveal as="span" className="block text-notweather" delay={0.8}>
              Broken plane.
            </Reveal>
          </h2>
          <Reveal delay={1.15}>
            <p className="mt-14 max-w-[1080px] text-[34px] leading-[1.42] text-cloud-300 text-pretty" data-testid="seats-line">
              {SEATS_LINE_PARTS.map((part, i) =>
                part.strong ? (
                  <span key={i} className="text-cloud-50">
                    {part.text}
                  </span>
                ) : (
                  <span key={i}>{part.text}</span>
                ),
              )}
            </p>
          </Reveal>
        </div>
        <Reveal delay={1.3}>
          <p className="mt-16 min-h-[34px] font-mono text-[16px] uppercase tracking-[0.14em] text-cloud-500">{COVER_IMAGE_CREDIT}</p>
        </Reveal>
      </RevealGroup>
    </div>
  );
}
