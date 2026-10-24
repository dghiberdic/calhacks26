import { useRef } from "react";
import { cn } from "@/lib/utils";
import { useStory } from "../data/context";
import type { ChainTone } from "../data/model";
import { gsap, MEDIA, useGSAP } from "../motion/gsap";

const DOT: Record<ChainTone, string> = {
  money: "border-navy-900 bg-navy-900",
  rule: "border-navy-900 bg-cloud-50",
  fault: "border-notweather bg-notweather",
  metar: "border-metar bg-cloud-50",
  plain: "border-slate-400 bg-cloud-50",
};

/**
 * Every euro, traced: NS31's drafted liability walked back through the entitlement and the rule to
 * every quoted line of evidence (GET /blame, or the Flight File's own decision evidence and timeline).
 * Red marks the fault that wasn't weather; the OCC code it overruled is struck.
 */
export function Trace() {
  const story = useStory();
  const root = useRef<HTMLElement>(null);
  const steps = story.chain;

  useGSAP(
    () => {
      if (!steps.length) return;
      const mm = gsap.matchMedia();
      mm.add(MEDIA.motion, () => {
        gsap.from(".tr-line", { scaleY: 0, transformOrigin: "top center", ease: "none", scrollTrigger: { trigger: ".tr-list", start: "top 70%", end: "bottom 60%", scrub: 0.6 } });
        gsap.utils.toArray<HTMLElement>(".tr-node").forEach((el) => {
          gsap.from(el, { opacity: 0.12, x: -10, duration: 0.6, ease: "power3.out", scrollTrigger: { trigger: el, start: "top 78%", toggleActions: "play none none reverse" } });
        });
      });
    },
    { scope: root, dependencies: [steps.length], revertOnUpdate: true },
  );

  return (
    <section ref={root} aria-label="Every euro, traced" data-section="trace" className="bg-cloud-50 px-5 py-28 text-navy-900 md:px-16 md:py-36">
      <div className="mx-auto grid max-w-[1280px] grid-cols-1 gap-14 lg:grid-cols-[minmax(0,5fr)_minmax(0,7fr)]">
        <div className="lg:sticky lg:top-32 lg:self-start">
          <h2 className="display text-[clamp(42px,5.8vw,100px)]">Every euro, traced.</h2>
          <p className="mt-6 max-w-[38ch] text-[16.5px] leading-relaxed text-slate-600 md:text-[19px]">
            Any amount walks back to the log line, the weather hour, the rule and the person who ruled. The auditor follows the same thread.
          </p>
          {steps.length ? (
            <p className="micro mt-6 text-slate-500">
              {story.chainSource === "blame" ? "blame" : "flight file"} · {story.focus?.flight.number ?? ""} · {steps.length} steps
            </p>
          ) : null}
        </div>

        <ol className="tr-list relative">
          <span className="tr-line absolute bottom-6 left-[7px] top-6 w-px bg-navy-900/70" aria-hidden="true" />
          {(steps.length ? steps : Array.from({ length: 6 }, () => null)).map((s, i) => (
            <li key={s?.key ?? i} className="tr-node relative grid grid-cols-[16px_minmax(0,1fr)] gap-x-6 pb-10 last:pb-0">
              <span className={cn("relative z-10 mt-[0.5em] size-[15px] rounded-full border-2", s?.struck ? "border-slate-400 bg-cloud-50" : DOT[s?.tone ?? "plain"])} aria-hidden="true" />
              {s ? (
                <div className="min-w-0">
                  <p
                    className={cn(
                      "display-tight text-[clamp(19px,1.7vw,27px)] leading-tight",
                      s.tone === "fault" && "text-notweather-ink",
                      s.tone === "metar" && "text-metar-ink",
                      s.struck && "text-slate-400 line-through decoration-2",
                    )}
                  >
                    {s.label}
                  </p>
                  {s.quote ? <p className={cn("mt-2 max-w-[62ch] break-words font-mono text-[12px] leading-relaxed text-slate-600", s.struck && "text-slate-400 line-through")}>{s.quote}</p> : null}
                  <p className="mt-1.5 break-words font-mono text-[10.5px] text-slate-400">{s.meta}</p>
                </div>
              ) : (
                <div className="flex flex-col gap-2 pt-1" aria-hidden="true">
                  <span className="h-6 w-2/3 animate-pulse rounded bg-navy-900/[0.06]" />
                  <span className="h-3 w-1/2 animate-pulse rounded bg-navy-900/[0.05]" />
                </div>
              )}
            </li>
          ))}
        </ol>
      </div>
    </section>
  );
}
