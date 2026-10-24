import { useRef } from "react";
import { count, eur } from "@/lib/format";
import { cn } from "@/lib/utils";
import { useStory } from "../data/context";
import type { ChainTone } from "../data/model";
import { gsap, MEDIA, useGSAP } from "../motion/gsap";
import { Pending } from "../ui";

const DOT: Record<ChainTone, string> = {
  money: "border-navy-900 bg-navy-900",
  rule: "border-navy-900 bg-cloud-50",
  fault: "border-notweather bg-notweather",
  metar: "border-metar bg-cloud-50",
  plain: "border-slate-400 bg-cloud-50",
};

/** The first step leads with its amount: "€34,650" large, the rest of the server's label beside it. */
function Lead({ label }: { label: string }) {
  const m = label.match(/^(€[\d,]+(?:\.\d+)?)\s*(?:·\s*)?(.*)$/);
  if (!m) return <>{label}</>;
  return (
    <>
      <span className="figure">{m[1]}</span>
      {m[2] ? <span className="mt-1 block font-sans text-[15px] font-normal tracking-normal text-slate-600 [font-stretch:100%] md:text-[16px]">{m[2]}</span> : null}
    </>
  );
}

/**
 * Every euro, traced: NS31's drafted liability walked back through the entitlement and the rule to
 * every quoted line of evidence (GET /blame, or the Flight File's own decision evidence and timeline).
 * Red marks the fault that wasn't weather; the OCC code it overruled is struck.
 */
export function Trace() {
  const story = useStory();
  const root = useRef<HTMLElement>(null);
  const steps = story.chain;
  const drafted = story.money.drafted;

  useGSAP(
    () => {
      if (!steps.length) return;
      const mm = gsap.matchMedia();
      mm.add(MEDIA.motion, () => {
        gsap.from(".tr-line, .tr-track", {
          scaleY: 0,
          transformOrigin: "top center",
          ease: "none",
          scrollTrigger: { trigger: ".tr-list", start: "top 70%", end: "bottom 60%", scrub: 0.6, onUpdate: (self) => root.current?.querySelector(".tr-pulse")?.setAttribute("data-on", String(self.progress > 0.12)) },
        });
        gsap.utils.toArray<HTMLElement>(".tr-node").forEach((el) => {
          gsap.from(el, { opacity: 0.12, x: -10, duration: 0.6, ease: "power3.out", scrollTrigger: { trigger: el, start: "top 78%", toggleActions: "play none none reverse" } });
        });
      });
    },
    { scope: root, dependencies: [steps.length], revertOnUpdate: true },
  );

  return (
    <section ref={root} aria-label="The audit trail" data-section="trace" className="bg-cloud-50 px-5 py-28 text-navy-900 md:px-16 md:py-36">
      <div className="mx-auto grid max-w-[1280px] grid-cols-1 gap-14 lg:grid-cols-[minmax(0,5fr)_minmax(0,7fr)]">
        <div className="lg:sticky lg:top-32 lg:self-start">
          <h2 className="text-balance display text-[clamp(38px,4.6vw,80px)]">
            {drafted !== null ? eur(drafted) : <Pending ch={7} tone="light" />} traces back to a log line in {steps.length ? count(steps.length) : <Pending ch={2} tone="light" />} steps.
          </h2>
          <p className="mt-6 max-w-[40ch] text-[16.5px] leading-relaxed text-slate-600 md:text-[19px]">
            Each step is a recorded commit, from the journal entry down to the tech-log and METAR lines the decision quoted. An auditor sees the same chain.
          </p>
          {steps.length ? (
            <p className="micro mt-6 text-slate-500">
              {story.chainSource === "blame" ? "blame" : "flight file"} · {story.focus?.flight.number ?? ""} · {steps.length} steps
            </p>
          ) : null}
        </div>

        <ol className="tr-list relative">
          <span className="tr-line absolute bottom-6 left-[7px] top-6 w-px bg-navy-900/70" aria-hidden="true" />
          {/* once the line is drawn, a reading walks it from the euros down to the log lines */}
          <span className="tr-track pointer-events-none absolute bottom-6 left-[7px] top-6 w-px motion-reduce:hidden" aria-hidden="true">
            <span className="tr-pulse" data-on="false" />
          </span>
          {(steps.length ? steps : Array.from({ length: 6 }, () => null)).map((s, i) => (
            <li key={s?.key ?? i} className="tr-node relative grid grid-cols-[16px_minmax(0,1fr)] gap-x-6 pb-9 last:pb-0">
              <span className={cn("relative z-10 size-[15px] rounded-full border-2", i === 0 ? "mt-[0.6em]" : "mt-[0.2em]", s?.struck ? "border-slate-400 bg-cloud-50" : DOT[s?.tone ?? "plain"])} aria-hidden="true" />
              {s ? (
                <div className="min-w-0">
                  <p
                    className={cn(
                      i === 0 ? "display-tight text-[clamp(30px,3vw,46px)] leading-none" : "text-[16.5px] font-medium leading-snug md:text-[18px]",
                      s.tone === "fault" && "text-notweather-ink",
                      s.tone === "metar" && "text-metar-ink",
                      s.struck && "text-slate-400 line-through decoration-2",
                    )}
                  >
                    {i === 0 ? <Lead label={s.label} /> : s.label}
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
