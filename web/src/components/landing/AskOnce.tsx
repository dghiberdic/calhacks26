"use client";

import { useRef } from "react";
import { gsap, useGSAP } from "@/components/motion/gsap";
import { RollingNumber } from "@/components/motion/RollingNumber";

const CASES = ["NS102", "NS214", "NS306", "NS27", "NS21", "NS25", "NS51"];

/** The 1%: one question, to one person, once. The answer becomes a scoped, versioned rule. */
export function AskOnce() {
  const root = useRef<HTMLDivElement>(null);

  useGSAP(
    () => {
      const tl = gsap.timeline({ scrollTrigger: { trigger: root.current, start: "top 55%", toggleActions: "play none none reverse" } });
      tl.from(".ao-card", { opacity: 0, y: 40, duration: 0.8, stagger: 0.35, ease: "power3.out" })
        .to(".ao-pick", { backgroundColor: "#121417", color: "#f4f4f1", duration: 0.3 }, 0.7)
        .from(".ao-rule-word", { opacity: 0, duration: 0.25, stagger: 0.04 }, 1.0)
        .from(".ao-case", { opacity: 0, x: -12, duration: 0.35, stagger: 0.07 }, 1.4);
    },
    { scope: root },
  );

  return (
    <div ref={root} className="mx-auto max-w-[1400px]">
      <h2 className="display max-w-[14ch] text-[clamp(44px,6vw,104px)] text-ink">Asks once. Never twice.</h2>
      <p className="mt-6 max-w-[48ch] text-[17px] leading-relaxed text-graphite md:text-[19px]">
        When the evidence disagrees, StormCheck asks one person one question, with the evidence attached. The answer becomes a rule with a scope and a version.
      </p>

      <div className="mt-20 grid grid-cols-1 gap-5 lg:grid-cols-3">
        {/* 1 · the question */}
        <article className="ao-card flex flex-col rounded-xl bg-paper p-6 shadow-[0_0_0_1px_var(--color-rule)]">
          <header className="flex items-center justify-between text-[14px]">
            <span className="font-medium">To the Claims Lead</span>
            <span className="rounded-full bg-review-wash px-2.5 py-1 text-[13px] text-review-ink">39% · sources disagree</span>
          </header>
          <p className="mt-5 text-[19px] leading-snug text-ink">
            The CRM says Aoife Byrne took a €300 voucher at the gate. Her claim says she never agreed. Offset the voucher against her €600?
          </p>
          <div className="mt-5 space-y-2 rounded-lg bg-chart p-4 font-mono text-[12.5px] leading-relaxed text-graphite">
            <p>CRM 9 DEC 20:52Z VOUCHER €300 ISSUED GATE B4 NS31</p>
            <p>EMAIL 11 DEC &ldquo;I NEVER AGREED TO A VOUCHER&rdquo;</p>
          </div>
          <div className="mt-auto flex flex-wrap gap-2 pt-6">
            <span className="ao-pick rounded-md border border-ink px-3 py-2 text-[14px] font-medium">No signed acceptance, no offset</span>
            <span className="rounded-md border border-rule-2 px-3 py-2 text-[14px] text-graphite">Offset it</span>
          </div>
          <p className="mt-3 text-[13px] text-graphite">Holds €600 for one passenger until answered.</p>
        </article>

        {/* 2 · the rule */}
        <article className="ao-card flex flex-col rounded-xl bg-paper p-6 shadow-[0_0_0_1px_var(--color-rule)]">
          <header className="flex items-center justify-between text-[14px]">
            <span className="font-medium">New rule</span>
            <span className="font-mono text-[13px] text-graphite">R-7 v1</span>
          </header>
          <p className="mt-5 text-[19px] leading-snug text-ink">
            {"A gate voucher is offset against EU261 compensation only with a signed acceptance.".split(" ").map((w, i) => (
              <span key={i} className="ao-rule-word">
                {w}{" "}
              </span>
            ))}
          </p>
          <dl className="mt-6 grid grid-cols-[auto_1fr] gap-x-5 gap-y-2 text-[14px]">
            <dt className="text-graphite">Scope</dt>
            <dd>Flights departing the EU</dd>
            <dt className="text-graphite">From</dt>
            <dd>11 Dec 2025</dd>
            <dt className="text-graphite">Source</dt>
            <dd>Claims Lead ruling, 10:14Z</dd>
            <dt className="text-graphite">Replay</dt>
            <dd>Changes 0 past decisions</dd>
          </dl>
        </article>

        {/* 3 · the next storm */}
        <article className="ao-card flex flex-col rounded-xl bg-ink p-6 text-chart">
          <header className="flex items-center justify-between text-[14px]">
            <span className="font-medium">Next storm, 27 Jan</span>
            <span className="text-[13px] text-mist">0 questions asked</span>
          </header>
          <div className="mt-5 flex items-baseline gap-3">
            <RollingNumber value={31} className="display text-[72px]" trigger="top 75%" delay={1.2} />
            <span className="text-[17px] text-haze">voucher cases settled</span>
          </div>
          <ul className="mt-6 space-y-2 text-[14px]">
            {CASES.map((c, i) => (
              <li key={c} className="ao-case flex items-center justify-between border-b border-white/10 pb-2">
                <span className="font-mono">{c}</span>
                <span className="text-haze">{["no offset", "offset, signed", "no offset", "no offset", "offset, signed", "no offset", "no offset"][i]}</span>
                <span className="rounded bg-white/10 px-2 py-0.5 font-mono text-[12px]">R-7 v1</span>
              </li>
            ))}
          </ul>
        </article>
      </div>
    </div>
  );
}
