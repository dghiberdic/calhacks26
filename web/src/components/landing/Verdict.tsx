"use client";

import { useMemo, useRef } from "react";
import { line, curveMonotoneX } from "d3-shape";
import { RollingNumber } from "@/components/motion/RollingNumber";
import { gsap, useGSAP } from "@/components/motion/gsap";
import { NS31 } from "@/data/scenario";

/** The euros, in the order a controller would check them. */
export function Verdict() {
  const root = useRef<HTMLDivElement>(null);

  const curve = useMemo(() => {
    // cumulative share of owed passengers who have claimed, by month after the storm
    const pts = Array.from({ length: 25 }, (_, m) => ({ m, r: 0.35 * (1 - Math.exp(-m / 5.2)) }));
    const x = (m: number) => 8 + (m / 24) * 284;
    const y = (r: number) => 112 - (r / 0.4) * 100;
    return { d: line<{ m: number; r: number }>().x((p) => x(p.m)).y((p) => y(p.r)).curve(curveMonotoneX)(pts) ?? "", y35: y(0.35), x, y };
  }, []);

  useGSAP(
    () => {
      gsap.from(".vd-line", {
        drawSVG: 0,
        duration: 1.8,
        ease: "power2.inOut",
        scrollTrigger: { trigger: ".vd-curve", start: "top 80%" },
      });
      gsap.from(".vd-reveal", {
        opacity: 0,
        y: 24,
        duration: 0.9,
        stagger: 0.12,
        ease: "power3.out",
        scrollTrigger: { trigger: root.current, start: "top 65%" },
      });
      gsap.from(".vd-conf", { scaleX: 0, transformOrigin: "left center", duration: 1.2, ease: "power3.inOut", scrollTrigger: { trigger: ".vd-conf", start: "top 90%" } });
    },
    { scope: root },
  );

  return (
    <div ref={root} className="mx-auto max-w-[1400px]">
      <h2 className="display vd-reveal text-[clamp(48px,7.4vw,128px)] text-ink">
        Not weather.
        <br />
        <span className="text-owed-ink">Broken plane.</span>
      </h2>

      <div className="mt-24 grid grid-cols-1 items-end gap-x-8 gap-y-10 md:grid-cols-[auto_auto_auto_auto_1fr]">
        <figure className="vd-reveal">
          <RollingNumber value={NS31.flight.pax} className="display-tight text-[clamp(44px,5vw,84px)]" />
          <figcaption className="mt-3 text-[15px] text-graphite">passengers on NS31</figcaption>
        </figure>
        <span className="vd-reveal hidden pb-12 text-[40px] font-light text-rule-2 md:block" aria-hidden="true">
          ×
        </span>
        <figure className="vd-reveal">
          <RollingNumber value={600} prefix="€" className="display-tight text-[clamp(44px,5vw,84px)]" />
          <figcaption className="mt-3 text-[15px] text-graphite">each, over 3,500&nbsp;km (EU261 Art.&nbsp;7)</figcaption>
        </figure>
        <span className="vd-reveal hidden pb-12 text-[40px] font-light text-rule-2 md:block" aria-hidden="true">
          =
        </span>
        <figure className="vd-reveal">
          <RollingNumber value={NS31.exposure} prefix="€" className="display-tight text-[clamp(44px,5vw,84px)] text-graphite" />
          <figcaption className="mt-3 text-[15px] text-graphite">if every passenger claims</figcaption>
        </figure>
      </div>

      <div className="mt-24 grid grid-cols-1 gap-12 rounded-xl bg-paper p-8 shadow-[0_1px_0_rgba(0,0,0,0.04),0_0_0_1px_var(--color-rule)] md:grid-cols-[1.1fr_1fr] md:p-12">
        <div className="vd-reveal">
          <p className="text-[15px] text-graphite">Provision drafted for the Controller</p>
          <RollingNumber value={NS31.provision} prefix="€" className="display mt-3 text-[clamp(56px,7vw,120px)] text-owed-ink" delay={0.2} />
          <p className="mt-6 max-w-[42ch] text-[17px] leading-relaxed text-ink">
            About one in three owed passengers ever claims. StormCheck learned that from two years of Northstar&rsquo;s own claims, and books the expected cost, not the worst case.
          </p>
          <dl className="mt-8 grid max-w-[460px] grid-cols-[auto_1fr] gap-x-6 gap-y-3 text-[15px]">
            <dt className="text-graphite">Confidence</dt>
            <dd className="flex items-center gap-3">
              <span className="relative h-[6px] flex-1 rounded-full bg-fog">
                <span className="vd-conf absolute inset-y-0 left-0 w-[91%] rounded-full bg-ink" />
                <span className="absolute -top-1 left-[80%] h-[14px] w-px bg-owed" title="Auto-draft threshold" />
              </span>
              <span className="tabular font-mono text-[14px]">91%</span>
            </dd>
            <dt className="text-graphite">Why</dt>
            <dd>Fault logged 3&nbsp;h&nbsp;05&nbsp;min before the storm window</dd>
            <dt className="text-graphite">Status</dt>
            <dd>212 payouts drafted, held for the Claims Lead</dd>
          </dl>
        </div>

        <div className="vd-reveal flex flex-col justify-between gap-8">
          <figure className="vd-curve">
            <svg viewBox="0 0 300 130" className="w-full" role="img" aria-label="Expected claims rise over two years toward 35 percent of owed passengers.">
              <line x1="8" x2="292" y1="112" y2="112" stroke="var(--color-rule-2)" />
              <line x1="8" x2="292" y1={curve.y35} y2={curve.y35} stroke="var(--color-owed)" strokeDasharray="3 4" strokeOpacity="0.7" />
              <path className="vd-line" d={curve.d} fill="none" stroke="var(--color-ink)" strokeWidth="2" />
              <circle cx={curve.x(0)} cy={curve.y(0)} r="3" fill="var(--color-ink)" />
              <text x="292" y={curve.y35 - 6} textAnchor="end" className="fill-[var(--color-owed-ink)] font-mono text-[9px]">
                35%
              </text>
              {[0, 6, 12, 18, 24].map((m) => (
                <text key={m} x={curve.x(m)} y="126" textAnchor="middle" className="fill-[var(--color-graphite)] font-mono text-[8px]">
                  {m === 0 ? "storm" : `${m} mo`}
                </text>
              ))}
            </svg>
            <figcaption className="mt-3 text-[14px] text-graphite">Claims arrive for years. The provision is trued up against this curve every month-end.</figcaption>
          </figure>

          <figure className="rounded-lg bg-chart p-5 font-mono text-[13px] leading-[1.9] text-ink">
            <figcaption className="mb-2 font-sans text-[13px] text-graphite">Journal entry, drafted 09:00Z</figcaption>
            <div className="grid grid-cols-[auto_1fr_auto] gap-x-4">
              <span>Dr</span>
              <span>Passenger compensation</span>
              <span className="tabular text-right">44,520.00</span>
              <span>Cr</span>
              <span className="pl-6">EU261 claims provision</span>
              <span className="tabular text-right">44,520.00</span>
            </div>
          </figure>
        </div>
      </div>
    </div>
  );
}
