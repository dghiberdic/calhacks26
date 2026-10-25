import { useEffect, useMemo, useState, type ReactNode } from "react";
import { Link, useLocation } from "react-router";
import { useMutation } from "@tanstack/react-query";
import { MotionConfig, useReducedMotion } from "motion/react";
import { api } from "@/api/client";
import { useLearning, useRules } from "@/api/queries";
import type { Rule } from "@/api/types";
import { Explain } from "@/components/explain";
import { Details, DetailsTitle, Empty, ErrorNote, PageHeader, Shimmer } from "@/components/kit";
import { cn } from "@/lib/utils";
import { RevertDialog, WidenDialog } from "./dialogs";
import { LearnedAndReused } from "./Learning";
import { ORIGIN_COPY, ORIGIN_ORDER, byOrigin, familyFromHash, type Origin, type RuleFamily } from "./model";
import { StatusLifecycle } from "./parts";
import { HardControls, StaticRegulationCard } from "./regulation";
import { RuleCard, type CardActions } from "./RuleCard";

const EMPTY_LINE: Record<Origin, ReactNode> = {
  learned: "Nothing mined yet.",
  ruled: (
    <>
      No rulings yet.{" "}
      <Link to="/questions" className="font-medium text-metar-ink hover:underline">
        Answer a question
      </Link>{" "}
      and the ruling lands here as a rule.
    </>
  ),
  rejected: "No rejections yet. A rejected proposal lands here as a rule.",
  regulation: "No regulation versions loaded.",
  hard: "",
};

/** J4 · Policies: every rule by where it came from. Rules come only from history, rulings, rejections and regulation. */
export default function PoliciesScreen() {
  const rules = useRules();
  // Additive route: a server or recording without it answers 404, and the timeline stays hidden.
  const learning = useLearning();
  const groups = useMemo(() => (rules.data ? byOrigin(rules.data) : null), [rules.data]);
  const flash = useDeepLinkFlash(!!groups);
  const { actions, dialogs } = useRuleActions();

  useEffect(() => {
    document.title = "Policies · StormCheck";
  }, []);

  return (
    <MotionConfig reducedMotion="user">
      <div className="mx-auto max-w-[1120px]">
        <PageHeader title="Policies">
          Reuse a decision without losing who made it, why, or where it applies.
        </PageHeader>

        {learning.data?.length ? <LearnedAndReused steps={learning.data} rules={rules.data} /> : null}

        <HowRulesWork />

        {rules.isLoading ? (
          <Skeleton />
        ) : rules.isError ? (
          <ErrorNote error={rules.error} onRetry={() => void rules.refetch()} className="mt-8" />
        ) : !groups || !rules.data?.length ? (
          <Empty title="No policies yet" className="mt-8">
            Rules appear here as StormCheck mines history and people rule on questions.
          </Empty>
        ) : (
          <>
            <OriginIndex groups={groups} />
            {ORIGIN_ORDER.map((origin) => (
              <OriginSection key={origin} origin={origin} families={groups[origin]} flash={flash} actions={actions} />
            ))}
          </>
        )}
      </div>
      {dialogs}
    </MotionConfig>
  );
}

/** Widen and Revert open dialogs. Writes start from a click, never from an effect (StrictMode can't double-post). */
function useRuleActions() {
  const [widenFor, setWidenFor] = useState<Rule | null>(null);
  const [revertFor, setRevertFor] = useState<Rule | null>(null);
  const widen = useMutation({ mutationFn: (rule: Rule) => api.widen(rule.id) });

  const startWiden = (rule: Rule) => {
    setWidenFor(rule);
    widen.reset();
    widen.mutate(rule);
  };

  const dialogs = (
    <>
      <WidenDialog
        rule={widenFor}
        proposal={widen.data ?? null}
        pending={widen.isPending}
        error={widen.error}
        onRetry={() => widenFor && widen.mutate(widenFor)}
        onClose={() => {
          setWidenFor(null);
          widen.reset();
        }}
      />
      <RevertDialog key={revertFor ? `${revertFor.id}@${revertFor.version}` : "none"} rule={revertFor} onClose={() => setRevertFor(null)} />
    </>
  );
  return { actions: { onWiden: startWiden, onRevert: setRevertFor } satisfies CardActions, dialogs };
}

/**
 * `#R-CL-1@1` (what Flight File links to), `#R-CL-1`, or an older version's ref scrolls to the rule's card
 * (its id is the version in force) and outlines it for a moment.
 */
function useDeepLinkFlash(ready: boolean) {
  const { hash } = useLocation();
  const reduce = useReducedMotion();
  const [flash, setFlash] = useState<string | null>(null);
  useEffect(() => {
    const id = ready ? familyFromHash(hash) : null;
    const el = id ? document.querySelector<HTMLElement>(`[data-family="${CSS.escape(id)}"]`) : null;
    if (!id || !el) return;
    const raf = requestAnimationFrame(() => {
      el.scrollIntoView({ block: "center", behavior: reduce ? "auto" : "smooth" });
      setFlash(id);
    });
    const done = window.setTimeout(() => setFlash(null), 3400);
    return () => {
      cancelAnimationFrame(raf);
      window.clearTimeout(done);
    };
  }, [hash, ready, reduce]);
  return flash;
}

/** Where rules come from, which wins, where each applies and how it lives: one click away, in words. */
function HowRulesWork() {
  return (
    <section aria-label="How rules work" className="mt-6 rounded-xl bg-card px-5 py-3.5 shadow-[0_0_0_1px_var(--color-cloud-200),0_1px_2px_rgba(13,21,36,0.04)]">
      <Details summary={<DetailsTitle title="How rules work" note="where they come from, which wins, where they apply" />}>
        <ul className="flex max-w-[86ch] flex-col gap-2 text-[13.5px] leading-relaxed text-slate-600">
          <li>
            <span className="font-medium text-navy-900">Where they come from.</span> Patterns mined from Northstar&rsquo;s past decisions, a person&rsquo;s answer to a question, a proposal someone rejected, or a version of the law. Hard controls are code and sit above all of them.
          </li>
          <li>
            <span className="font-medium text-navy-900">Which one wins.</span> When two rules match a case, <Explain term="rule-precedence">the stronger source wins</Explain>.
          </li>
          <li>
            <span className="font-medium text-navy-900">Where each applies.</span> Every rule has a <Explain term="rule-scope">scope</Explain>; a case outside it is asked again rather than guessed.
          </li>
          <li>
            <span className="font-medium text-navy-900">How a rule lives.</span> A widened version runs in shadow first, recording what it would change, and applies once someone confirms it. A replay or a challenge can mark it suspect; a revert retires it, kept for replay.
            <StatusLifecycle className="mt-2" />
          </li>
        </ul>
      </Details>
    </section>
  );
}

/** Jump to each origin: its name and how many rules it holds. */
function OriginIndex({ groups }: { groups: Record<Origin, RuleFamily[]> }) {
  const shown = ORIGIN_ORDER.filter((o) => o !== "hard" || groups.hard.length > 0);
  return (
    <nav aria-label="Policies by origin" className="mt-4">
      <ol className="flex flex-wrap gap-1.5">
        {shown.map((origin) => {
          const list = groups[origin];
          const title = origin === "hard" ? "Hard controls" : ORIGIN_COPY[origin].title;
          return (
            <li key={origin}>
              <a
                href={`#origin-${origin}`}
                aria-label={`${title}: ${list.length} ${list.length === 1 ? "rule" : "rules"}`}
                className="inline-flex h-8 items-center gap-2 rounded-full bg-white px-3 text-[13px] font-medium text-navy-900 shadow-[inset_0_0_0_1px_var(--color-cloud-200)] transition-colors hover:bg-cloud-50 focus-visible:outline-2 focus-visible:outline-offset-1 focus-visible:outline-metar-ink"
              >
                {title}
                <span className={cn("figure text-[12px]", list.length ? "text-slate-500" : "text-cloud-400")}>{list.length}</span>
              </a>
            </li>
          );
        })}
      </ol>
    </nav>
  );
}

function OriginSection({ origin, families, flash, actions }: { origin: Origin; families: RuleFamily[]; flash: string | null; actions: CardActions }) {
  if (origin === "hard" && families.length === 0) return null;
  const copy = ORIGIN_COPY[origin];
  return (
    <section id={`origin-${origin}`} aria-labelledby={`origin-${origin}-title`} className="mt-11 scroll-mt-20">
      <div className="mb-3.5 flex flex-wrap items-baseline gap-x-3 gap-y-1">
        <h2 id={`origin-${origin}-title`} className="display-tight text-[18px] text-navy-900">
          {copy.title}
        </h2>
        <p className="text-[13.5px] text-slate-500">{copy.blurb}</p>
      </div>
      {families.length === 0 ? (
        <p className="rounded-xl px-5 py-4 text-[13.5px] text-slate-500 shadow-[inset_0_0_0_1px_var(--color-cloud-200)]">{EMPTY_LINE[origin]}</p>
      ) : origin === "hard" ? (
        <HardControls families={families} />
      ) : (
        <div className="flex flex-col gap-3.5">
          {families.map((f, i) =>
            f.current.static_card ? (
              <StaticRegulationCard key={f.id} rule={f.current} highlighted={flash === f.id} index={i} />
            ) : (
              <RuleCard key={f.id} family={f} index={i} highlighted={flash === f.id} actions={actions} />
            ),
          )}
        </div>
      )}
    </section>
  );
}

function Skeleton() {
  return (
    <div className="mt-7" aria-busy="true" aria-label="Loading policies">
      <Shimmer className="h-[84px] w-full rounded-xl" />
      <Shimmer className="mt-11 h-6 w-56" />
      <div className="mt-4 flex flex-col gap-3.5">
        <Shimmer className="h-[220px] w-full rounded-xl" />
        <Shimmer className="h-[220px] w-full rounded-xl" />
      </div>
    </div>
  );
}
