import { useRef } from "react";
import { StatusChip } from "@/components/chips";
import { Money, RoleAvatar } from "@/components/kit";
import { GroundedQuote, RuleSentence, ruleRef, TIER_LABEL } from "@/components/rule-sentence";
import { count, longDate, pct, routedTo, shortId } from "@/lib/format";
import { cn } from "@/lib/utils";
import { useStory } from "../data/context";
import { gsap, MEDIA, useGSAP } from "../motion/gsap";
import { RollingNumber } from "../motion/RollingNumber";
import { Pending } from "../ui";

const TAG: Record<string, string> = {
  "sources-disagree": "sources disagree",
  "no-precedent": "no precedent",
  "out-of-scope": "out of scope",
  "release-proposal": "release proposal",
  "concurrent-causes": "concurrent causes",
  "new-legal-pattern": "new legal pattern",
};

/**
 * The 1%: one question, to one person, once. Q1 (the service-desk voucher, from the API), the rule its
 * ruling became, and the next storm, Herminia, where the same pattern settles itself, ruling cited.
 */
export function AskOnce() {
  const story = useStory();
  const root = useRef<HTMLElement>(null);
  const q = story.q1;
  const rule = story.rule;
  const next = story.next;
  const cited = next?.counters.rules_cited;
  const waiting = next?.counters.needs_ruling;
  const askedAgain = next?.questions[0] ?? null;
  const c = story.run?.counters;
  // "No signed acceptance, no offset: pay €600 cash; …" → the ruling's own words before the colon
  const shortOption = q ? (q.recommended_option.split(":")[0] ?? q.recommended_option).replace(/\.$/, "") : "";

  useGSAP(
    () => {
      const mm = gsap.matchMedia();
      mm.add(MEDIA.motion, () => {
        gsap.from(".ao-head > *", { opacity: 0, y: 24, stagger: 0.1, duration: 0.9, scrollTrigger: { trigger: root.current, start: "top 65%" } });
        gsap.from(".ao-card", { opacity: 0, y: 40, duration: 0.8, stagger: 0.3, ease: "power3.out", scrollTrigger: { trigger: ".ao-cards", start: "top 72%" } });
      });
    },
    { scope: root },
  );

  return (
    <section ref={root} aria-label="One question for the Claims Lead" data-section="ask" className="bg-cloud-50 px-5 py-28 text-navy-900 md:px-16 md:py-36">
      <div className="mx-auto max-w-[1280px]">
        <div className="ao-head">
          <h2 className="text-balance display max-w-[16ch] text-[clamp(42px,5.8vw,100px)]">
            {c ? count(c.questions) : <Pending ch={1} tone="light" />} {c?.questions === 1 ? "question" : "questions"} for {c ? count(c.passengers) : <Pending ch={5} tone="light" />} passengers.
          </h2>
          <p className="mt-6 max-w-[50ch] text-[16.5px] leading-relaxed text-slate-600 md:text-[19px]">
            When sources disagree, StormCheck sends one question to the person who can rule on it, with the evidence attached. Their answer becomes a rule with a scope and a version.
          </p>
        </div>

        <div className="ao-cards mt-16 grid grid-cols-1 gap-4 md:mt-20 lg:grid-cols-3">
          {/* 1 · the question */}
          <article className="ao-card flex flex-col rounded-2xl bg-white p-6 shadow-[0_0_0_1px_var(--color-cloud-200)]">
            <header className="flex flex-wrap items-center justify-between gap-2 text-[13.5px]">
              {q ? (
                <span className="flex items-center gap-2 font-medium">
                  <RoleAvatar role={q.routed_to} size="sm" />
                  {routedTo(q.routed_to)}
                </span>
              ) : (
                <Pending ch={18} tone="light" />
              )}
              {q ? (
                <StatusChip tone="held">
                  {q.confidence.score !== null ? pct(q.confidence.score) : "uncalibrated"} · {TAG[q.reason_tag] ?? q.reason_tag}
                </StatusChip>
              ) : null}
            </header>
            {q ? (
              <>
                {/* The title, not `found`: the finding can name the passenger, and this page is public. */}
                <p className="mt-5 text-[18px] leading-snug">{q.title}</p>
                {q.evidence.some((e) => e.quote) ? (
                  <div className="mt-4 space-y-1.5 rounded-lg bg-cloud-50 p-3.5 font-mono text-[11.5px] leading-relaxed text-slate-600 shadow-[inset_0_0_0_1px_var(--color-cloud-200)]">
                    {q.evidence
                      .filter((e) => e.quote)
                      .slice(0, 3)
                      .map((e) => (
                        <p key={e.fact_id} className="break-words">
                          {e.quote}
                        </p>
                      ))}
                  </div>
                ) : null}
                <div className="mt-auto flex flex-wrap gap-2 pt-6">
                  {q.options.map((o) => (
                    <span key={o} className={cn("rounded-lg px-3 py-2 text-[13.5px]", o === q.recommended_option ? "bg-navy-900 font-medium text-cloud-50" : "text-slate-500 shadow-[inset_0_0_0_1px_var(--color-cloud-300)]")}>
                      {o}
                    </span>
                  ))}
                </div>
                {q.holds_cents ? (
                  <p className="mt-3 flex items-center gap-2 text-[13px] text-held-ink">
                    <span className="relative inline-flex size-2 shrink-0" aria-hidden="true">
                      <span className="absolute inset-0 rounded-full bg-held opacity-60 motion-safe:animate-ping" />
                      <span className="relative inline-flex size-2 rounded-full bg-held" />
                    </span>
                    <span>
                      Holds <Money cents={q.holds_cents} /> until answered · {q.case_refs.map(shortId).join(", ")}
                    </span>
                  </p>
                ) : null}
              </>
            ) : story.questionsLoaded ? (
              <p className="mt-5 text-[15px] leading-relaxed text-slate-500">This question is routed to the Claims Lead, and this role doesn&rsquo;t see it. Switch roles in the app to read it.</p>
            ) : (
              <div className="mt-5 flex flex-col gap-2" aria-hidden="true">
                <span className="h-5 w-11/12 animate-pulse rounded bg-navy-900/[0.06]" />
                <span className="h-5 w-3/4 animate-pulse rounded bg-navy-900/[0.06]" />
                <span className="mt-4 h-16 w-full animate-pulse rounded-lg bg-navy-900/[0.04]" />
              </div>
            )}
          </article>

          {/* 2 · the rule */}
          <article className="ao-card flex flex-col rounded-2xl bg-white p-6 shadow-[0_0_0_1px_var(--color-cloud-200)]">
            <header className="flex flex-wrap items-center justify-between gap-2 text-[13.5px]">
              <span className="font-medium">{rule ? `${TIER_LABEL[rule.tier]} → policy` : "The ruling becomes a rule"}</span>
              {rule ? <span className="font-mono text-[12.5px] text-slate-500">{ruleRef(rule)}</span> : null}
            </header>
            {rule ? (
              <>
                <RuleSentence rule={rule} className="mt-5 text-[16px]" />
                {rule.origin_example ? <GroundedQuote text={rule.origin_example} grounding={rule.grounding} className="mt-4 text-slate-600" /> : null}
                <dl className="mt-auto grid grid-cols-[auto_minmax(0,1fr)] gap-x-5 gap-y-2 pt-6 text-[13.5px]">
                  <dt className="text-slate-500">Status</dt>
                  <dd className="font-mono text-[12.5px]">{rule.status}</dd>
                  {rule.valid_from ? (
                    <>
                      <dt className="text-slate-500">From</dt>
                      <dd>{longDate(rule.valid_from)}</dd>
                    </>
                  ) : null}
                  {rule.times_cited !== undefined ? (
                    <>
                      <dt className="text-slate-500">Cited</dt>
                      <dd>
                        <span className="figure">{count(rule.times_cited)}</span> times
                      </dd>
                    </>
                  ) : null}
                </dl>
              </>
            ) : q ? (
              <>
                <p className="mt-5 text-[16px] leading-relaxed">
                  If the Claims Lead answers <strong className="font-semibold">&ldquo;{shortOption}&rdquo;</strong>, StormCheck drafts a rule from that wording, checks it and replays it before it goes live.
                </p>
                <p className="mt-auto pt-6 text-[13px] text-slate-500">{q.recommends}</p>
              </>
            ) : (
              <div className="mt-5 flex flex-col gap-2" aria-hidden="true">
                <span className="h-5 w-full animate-pulse rounded bg-navy-900/[0.06]" />
                <span className="h-5 w-2/3 animate-pulse rounded bg-navy-900/[0.06]" />
              </div>
            )}
          </article>

          {/* 3 · the next storm: settled under the ruling once it exists, waiting on it until then */}
          <article className="ao-card flex flex-col rounded-2xl bg-navy-900 p-6 text-cloud-50">
            <header className="flex flex-wrap items-center justify-between gap-2 text-[13.5px]">
              <span className="font-medium">Next storm{story.nextName ? `: ${story.nextName.replace("Storm ", "")}` : ""}</span>
              <span className="text-cloud-400">{next ? longDate(next.date) : <Pending ch={10} />}</span>
            </header>
            <div className="mt-5 flex items-baseline gap-3">
              {next ? (
                <RollingNumber text={count(rule ? (cited ?? 0) : (waiting ?? 0))} className="display text-[72px]" start="top 80%" delay={0.6} />
              ) : (
                <Pending ch={2} className="h-14" />
              )}
              <span className="text-[16px] leading-snug text-cloud-300">
                {rule ? (
                  <>
                    cases settled,
                    <br />
                    ruling cited
                  </>
                ) : (
                  <>
                    cases held for
                    <br />
                    this one answer
                  </>
                )}
              </span>
            </div>
            {/* one mark per case, from the API count: waiting on the answer (a slow wave runs through them), or settled */}
            {next ? (
              <div className="mt-6 flex max-w-[22rem] flex-wrap gap-[5px]" aria-hidden="true">
                {Array.from({ length: Math.min(64, rule ? (cited ?? 0) : (waiting ?? 0)) }, (_, i) => (
                  <span key={i} className={cn("ao-case size-[7px] rounded-[2px]", rule ? "bg-cloud-200" : "bg-held/80")} style={{ animationDelay: `${(i % 16) * 90 + Math.floor(i / 16) * 140}ms` }} />
                ))}
              </div>
            ) : null}
            {rule && askedAgain ? (
              <p className="mt-6 text-[14px] leading-relaxed text-cloud-300">
                <span className="figure text-cloud-50">{count(next?.questions.length ?? 1)}</span> asked again, outside the ruling&rsquo;s scope: {askedAgain.title}
              </p>
            ) : !rule && next ? (
              <p className="mt-6 text-[14px] leading-relaxed text-cloud-300">
                {story.nextName?.replace("Storm ", "") ?? "The next storm"}&rsquo;s cancellations came with more unsigned service-desk vouchers. Once the Claims Lead answers, the ones inside the ruling&rsquo;s scope settle without a new question; the rest are asked again.
              </p>
            ) : null}
            <p className="mt-auto flex items-center gap-2 pt-8 font-mono text-[12px] text-cloud-500">
              <span className="inline-block motion-safe:animate-[spin_7s_linear_infinite]" aria-hidden="true">
                ↻
              </span>
              a ruling applies only where its scope holds
            </p>
          </article>
        </div>
      </div>
    </section>
  );
}
