import { useRef } from "react";
import { Link } from "react-router";
import { ArrowUpRight } from "lucide-react";
import { RuleLab } from "@/features/rule-lab/RuleLab";
import { gsap, MEDIA, useGSAP } from "../motion/gsap";
import { RollingNumber } from "../motion/RollingNumber";

/** The next beat after AskOnce: demonstrate how that same ruling is tested before reuse. */
export function RuleLabChapter() {
  const root = useRef<HTMLElement>(null);
  useGSAP(() => {
    const mm = gsap.matchMedia();
    mm.add(MEDIA.motion, () => {
      gsap.from(".rl-story-heading > *", {opacity: 0, y: 26, stagger: 0.12, duration: 0.9,
        scrollTrigger: {trigger: root.current, start: "top 70%"}});
      gsap.from(".rl-story-panel", {opacity: 0, y: 40, duration: 0.9,
        scrollTrigger: {trigger: ".rl-story-panel", start: "top 85%"}});
    });
    return () => mm.revert();
  }, {scope: root});

  return (
    <section ref={root} id="rule-lab" data-section="rule-lab" aria-label="Test the ruling’s boundaries"
      className="relative scroll-mt-6 overflow-hidden bg-navy-950 px-5 py-28 text-cloud-50 md:px-16 md:py-36">
      <div className="pointer-events-none absolute inset-0 opacity-[0.045]" aria-hidden="true"
        style={{backgroundImage: "linear-gradient(to right, #c8d0db 1px, transparent 1px), linear-gradient(to bottom, #c8d0db 1px, transparent 1px)", backgroundSize: "80px 80px"}} />
      <div className="relative mx-auto max-w-[1280px]">
        <div className="rl-story-heading mb-14 grid items-end gap-8 lg:grid-cols-[minmax(0,7fr)_minmax(0,5fr)]">
          <div><p className="mb-5 font-mono text-[11px] uppercase tracking-[0.18em] text-cloud-500">Learning with boundaries / Rule Lab</p><h2 className="display max-w-[15ch] text-balance text-[clamp(40px,5.7vw,92px)]">A ruling learns.<br /><span className="text-cloud-500">Its limits stay.</span></h2></div>
          <div><p className="max-w-[44ch] text-[16px] leading-relaxed text-cloud-300 md:text-[18px]">Before that answer becomes routine, test the cases it should resolve and the cases it must leave alone. Try changing the draft below.</p><p className="mt-4 max-w-[52ch] text-[12px] leading-relaxed text-cloud-500">An isolated replay of the original voucher ruling. This test pack prepares evidence for human review; it does not activate a policy.</p><Link to="/rule-lab" className="mt-6 inline-flex items-center gap-2 text-[13px] text-cloud-200 hover:text-white">Open Rule Lab in the app <ArrowUpRight size={15} aria-hidden="true" /></Link></div>
        </div>
        <div className="rl-story-panel"><RuleLab renderFigure={value => <RollingNumber text={value} className="rl-figure" delay={0.12} />} /></div>
      </div>
    </section>
  );
}
