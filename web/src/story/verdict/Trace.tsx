import { useRef } from "react";
import type { BlameStep } from "@/api/types";
import { cn } from "@/lib/utils";
import { useStory } from "../data/context";
import { gsap, MEDIA, useGSAP } from "../motion/gsap";

/** What a step is, read from its commit: the tone of its node on the chain (red only for the fault that wasn't weather). */
function toneOf(step: BlameStep): "money" | "fault" | "metar" | "person" | "plain" {
  const text = `${step.label} ${step.commit.kind} ${step.commit.payload_ref} ${step.quote ?? ""}`;
  if (/€|journal|liabil/i.test(step.label) || step.commit.kind === "journal_event") return "money";
  if (/tech[ _-]?log|AOG|EDP/i.test(text)) return "fault";
  if (/METAR|EIDW \d{6}Z/i.test(text)) return "metar";
  if (step.commit.kind === "ruling" || /ruled|ruling/i.test(step.label)) return "person";
  return "plain";
}

const DOT = {
  money: "border-navy-900 bg-navy-900",
  fault: "border-notweather bg-notweather",
  metar: "border-metar bg-cloud-50",
  person: "border-navy-900 bg-cloud-50",
  plain: "border-slate-400 bg-cloud-50",
} as const;

/**
 * Every euro, traced: the blame chain for NS31's drafted liability, straight from the API — the amount,
 * the entitlement, the rule and the facts behind it, down to the quoted log line and weather hour.
 */
export function Trace() {
  const story = useStory();
  const root = useRef<HTMLElement>(null);
  const steps = story.blame?.steps ?? [];

  useGSAP(
    () => {
      if (!steps.length) return;
      const mm = gsap.matchMedia();
      mm.add(MEDIA.motion, () => {
        gsap.from(".tr-line", { scaleY: 0, transformOrigin: "top center", ease: "none", scrollTrigger: { trigger: ".tr-list", start: "top 70%", end: "bottom 60%", scrub: 0.6 } });
        gsap.utils.toArray<HTMLElement>(".tr-node").forEach((el) => {
          gsap.from(el, { opacity: 0.12, x: -10, duration: 0.6, ease: "power3.out", scrollTrigger: { trigger: el, start: "top 76%", toggleActions: "play none none reverse" } });
        });
      });
    },
    { scope: root, dependencies: [steps.length], revertOnUpdate: true },
  );

  return (
    <section ref={root} aria-label="Every euro, traced" className="bg-cloud-50 px-5 py-28 text-navy-900 md:px-16 md:py-36">
      <div className="mx-auto grid max-w-[1280px] grid-cols-1 gap-14 lg:grid-cols-[minmax(0,5fr)_minmax(0,7fr)]">
        <div className="lg:sticky lg:top-32 lg:self-start">
          <h2 className="display text-[clamp(42px,5.8vw,100px)]">Every euro, traced.</h2>
          <p className="mt-6 max-w-[38ch] text-[16.5px] leading-relaxed text-slate-600 md:text-[19px]">
            Any amount walks back to the log line, the weather hour, the rule and the person who ruled. The auditor follows the same thread.
          </p>
          {story.blame ? <p className="mt-6 font-mono text-[12px] text-slate-500">blame {story.blame.target}</p> : null}
        </div>

        <ol className="tr-list relative">
          <span className="tr-line absolute bottom-6 left-[7px] top-6 w-px bg-navy-900/80" aria-hidden="true" />
          {(steps.length ? steps : Array.from({ length: 6 }, () => null)).map((s, i) => {
            const tone = s ? toneOf(s) : "plain";
            return (
              <li key={s?.commit.hash ?? i} className="tr-node relative grid grid-cols-[16px_minmax(0,1fr)] gap-x-6 pb-11 last:pb-0">
                <span className={cn("relative z-10 mt-[0.55em] size-[15px] rounded-full border-2", DOT[tone])} aria-hidden="true" />
                {s ? (
                  <div className="min-w-0">
                    <p className={cn("display-tight text-[clamp(21px,2.1vw,32px)] leading-tight", tone === "fault" && "text-notweather-ink", tone === "metar" && "text-metar-ink")}>{s.label}</p>
                    {s.quote ? <p className="mt-2 max-w-[60ch] break-words font-mono text-[12.5px] leading-relaxed text-slate-600">{s.quote}</p> : null}
                    <p className="mt-2 font-mono text-[11px] text-slate-400">
                      {s.commit.kind.replace(/_/g, " ")} · {s.commit.hash.slice(0, 8)} · {s.commit.actor}
                    </p>
                  </div>
                ) : (
                  <div className="flex flex-col gap-2 pt-1" aria-hidden="true">
                    <span className="h-6 w-2/3 animate-pulse rounded bg-navy-900/[0.06]" />
                    <span className="h-3 w-1/2 animate-pulse rounded bg-navy-900/[0.05]" />
                  </div>
                )}
              </li>
            );
          })}
        </ol>
      </div>
    </section>
  );
}
