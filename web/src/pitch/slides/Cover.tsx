import { motion, useReducedMotion } from "motion/react";
import { COVER_IMAGE_CREDIT, SEATS_LINE_PARTS } from "../copy";
import { Brand, Reveal, RevealGroup } from "../ui";

/**
 * Where Dublin (53.43°N, 6.27°W) falls on the cover. The image is the GIBS mosaic (equirectangular, 30 px per
 * degree, 84°W–22°E, 71°N–22°N) cropped at x 1065, y 215, 1707×960 and scaled to 1920×1080.
 */
const DUBLIN = { left: 1425, top: 351 };

export const COVER_IMAGE = `${import.meta.env.BASE_URL}pitch/eowyn-2025-01-24.webp`;

/** The moment, over the real storm: Éowyn on the morning it shut Dublin, from NASA's Terra satellite. */
export function Cover() {
  const reduce = useReducedMotion();
  return (
    <div className="relative h-full w-full overflow-hidden bg-navy-950">
      {/* The storm settles slowly into place; the pin moves with it, so it stays on Dublin. */}
      <motion.div
        className="absolute inset-0"
        style={{ transformOrigin: "74% 26%" }}
        initial={reduce ? false : { scale: 1.06 }}
        animate={{ scale: 1 }}
        transition={{ duration: 9, ease: [0.22, 1, 0.36, 1] }}
      >
        <img
          src={COVER_IMAGE}
          alt="Storm Éowyn over Ireland and Britain on 24 January 2025, from NASA's Terra satellite"
          className="absolute inset-0 h-full w-full object-cover [filter:saturate(0.78)_brightness(0.92)]"
          draggable={false}
        />
        <div aria-hidden="true" className="absolute" style={DUBLIN}>
          <span className="absolute -left-[9px] -top-[9px] size-[18px] rounded-full shadow-[inset_0_0_0_2px_rgba(244,246,249,0.95),0_0_24px_rgba(8,13,23,0.6)]" />
          <span className="absolute -left-[3px] -top-[3px] size-[6px] rounded-full bg-cloud-50" />
          <span className="absolute left-[20px] top-[-12px] font-mono text-[17px] tracking-[0.16em] text-cloud-50 [text-shadow:0_1px_10px_rgba(8,13,23,0.95)]">DUBLIN</span>
        </div>
      </motion.div>
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
