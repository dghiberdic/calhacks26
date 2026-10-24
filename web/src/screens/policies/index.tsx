import { useEffect, useMemo, useState, type ReactNode } from "react";
import { Link, useLocation } from "react-router";
import { useMutation } from "@tanstack/react-query";
import { MotionConfig, useReducedMotion } from "motion/react";
import { api } from "@/api/client";
import { useRules } from "@/api/queries";
import type { Rule } from "@/api/types";
import { Empty, ErrorNote, PageHeader, Shimmer } from "@/components/kit";
import { cn } from "@/lib/utils";
import { RevertDialog, WidenDialog } from "./dialogs";
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
  const groups = useMemo(() => (rules.data ? byOrigin(rules.data) : null), [rules.data]);
  const flash = useDeepLinkFlash(!!groups);
  const { actions, dialogs } = useRuleActions();

  useEffect(() => {
    document.title = "Policies · StormCheck";
  }, []);

  return (
    <MotionConfig reducedMotion="user">
      <div className="mx-auto max-w-[1120px]">
        <PageHeader title="Policies" actions={<StatusLifecycle className="hidden lg:flex" />}>
          Rules come only from history, rulings, rejections and regulation. There is no rule editor.
        </PageHeader>

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

function OriginIndex({ groups }: { groups: Record<Origin, RuleFamily[]> }) {
  const shown = ORIGIN_ORDER.filter((o) => o !== "hard" || groups.hard.length > 0);
  return (
    <nav aria-label="Policies by origin" className="mt-7">
      <ol className={cn("grid grid-cols-2 gap-px overflow-hidden rounded-xl bg-cloud-200 shadow-[0_0_0_1px_var(--color-cloud-200)] sm:grid-cols-3", shown.length === 5 ? "lg:grid-cols-5" : "lg:grid-cols-4")}>
        {shown.map((origin, i) => {
          const list = groups[origin];
          const cited = list.reduce((s, f) => s + (f.current.times_cited ?? 0), 0);
          return (
            <li key={origin} className={cn("bg-card", i === shown.length - 1 && shown.length % 2 === 1 && "col-span-2 sm:col-span-1")}>
              <a
                href={`#origin-${origin}`}
                aria-label={`${origin === "hard" ? "Hard controls" : ORIGIN_COPY[origin].title}: ${list.length} ${list.length === 1 ? "rule" : "rules"}${origin !== "hard" && cited > 0 ? `, cited ${cited} times` : ""}`}
                className="group flex h-full flex-col px-4 py-3.5 transition-colors hover:bg-cloud-25 focus-visible:outline-2 focus-visible:-outline-offset-2 focus-visible:outline-metar-ink">
                <span className="flex items-baseline justify-between gap-2">
                  <span className={cn("figure text-[26px] font-semibold leading-none", list.length ? "text-navy-900" : "text-cloud-400")}>{list.length}</span>
                  {origin !== "hard" && cited > 0 ? <span className="font-mono text-[11px] text-slate-400">cited {cited}×</span> : null}
                </span>
                <span className="mt-2 text-[13px] font-medium text-navy-900 group-hover:underline group-hover:decoration-cloud-300 group-hover:underline-offset-2">
                  {origin === "hard" ? "Hard controls" : ORIGIN_COPY[origin].title}
                </span>
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
