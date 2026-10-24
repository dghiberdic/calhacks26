import { Fragment, type ReactNode } from "react";
import { Link } from "react-router";
import { motion, useReducedMotion } from "motion/react";
import { ArrowUpRight, GitCommitVertical, RotateCcw, Waypoints } from "lucide-react";
import { useBlame } from "@/api/queries";
import type { Rule } from "@/api/types";
import { MicroLabel } from "@/components/chips";
import { RoleAvatar } from "@/components/kit";
import { GroundedQuote, RuleSentence, TIER_LABEL, ruleRef } from "@/components/rule-sentence";
import { Tooltip, TooltipContent, TooltipTrigger } from "@/components/ui/tooltip";
import { ROLE_LABEL, shortId } from "@/lib/format";
import { stormName } from "@/lib/storms";
import { cn } from "@/lib/utils";
import { PRECEDENCE, RULER, caseClause, caseKeys, flightOf, isId, originOf, splitSource, stamp, validFromText, withoutCaseScope, type Origin, type RuleFamily } from "./model";
import { Marked, RuleStatusChip, SupportTicks, TickingCount, VersionTrail } from "./parts";

export type CardActions = { onWiden?: (rule: Rule) => void; onRevert?: (rule: Rule) => void };

/**
 * One rule, read as provenance → behaviour: whose words (or which history) it came from, then what it
 * does, then the record an auditor asks for (authority, citations, dates, versions). Never editable.
 */
export function RuleCard({ family, index = 0, highlighted, actions }: { family: RuleFamily; index?: number; highlighted?: boolean; actions: CardActions }) {
  const reduce = useReducedMotion();
  const rule = family.current;
  const origin = originOf(rule);
  // Only a rule in force can be widened or reverted; regulation and hard controls never can.
  const live = (origin === "learned" || origin === "ruled" || origin === "rejected") && rule.status === "active";
  const canWiden = live && caseKeys(rule).length > 0 && !family.pending;
  const canRevert = live;

  return (
    <motion.article
      id={ruleRef(rule)}
      data-family={family.id}
      data-testid={`rule-${family.id}`}
      initial={reduce ? false : { opacity: 0, y: 10 }}
      animate={{ opacity: 1, y: 0 }}
      transition={{ delay: Math.min(index, 6) * 0.05, duration: 0.45, ease: [0.16, 1, 0.3, 1] }}
      className={cn(
        "relative scroll-mt-24 rounded-xl bg-card shadow-[0_0_0_1px_var(--color-cloud-200),0_1px_2px_rgba(13,21,36,0.04)] transition-shadow duration-700",
        highlighted && "shadow-[0_0_0_2px_var(--color-navy-800),0_8px_28px_rgba(13,21,36,0.12)]",
      )}
      aria-labelledby={`${family.id}-title`}
    >
      <div className="grid md:grid-cols-[minmax(0,1fr)_268px]">
        <div className="min-w-0 p-5 md:p-6">
          <header className="flex items-start justify-between gap-3">
            <div className="flex min-w-0 flex-wrap items-center gap-x-2.5 gap-y-1 pt-0.5">
              <h3 id={`${family.id}-title`} className="font-mono text-[13px] font-bold text-navy-900">
                {ruleRef(rule)}
              </h3>
              <Tooltip>
                <TooltipTrigger asChild>
                  <span tabIndex={0} className="cursor-help rounded-sm text-[12.5px] text-slate-500 decoration-cloud-400 decoration-dotted underline-offset-[3px] hover:underline focus-visible:outline-2 focus-visible:outline-metar-ink">
                    {TIER_LABEL[rule.tier]}
                  </span>
                </TooltipTrigger>
                <TooltipContent className="max-w-[300px] flex-col items-start gap-1 py-2">
                  <span className="text-[11px] opacity-70">Precedence, highest first</span>
                  <span className="text-[12px] leading-snug">
                    {PRECEDENCE.map((t, i) => (
                      <Fragment key={t}>
                        {i > 0 ? <span className="opacity-60"> › </span> : null}
                        <span className={t === rule.tier ? "font-semibold underline underline-offset-2" : "opacity-80"}>{TIER_LABEL[t]}</span>
                      </Fragment>
                    ))}
                  </span>
                </TooltipContent>
              </Tooltip>
              {rule.kind !== "mined_policy" ? (
                <>
                  <span className="text-cloud-400" aria-hidden="true">
                    ·
                  </span>
                  <span className="font-mono text-[11.5px] text-slate-400">{rule.kind.replace(/_/g, "-")}</span>
                </>
              ) : null}
            </div>
            <RuleStatusChip status={rule.status} className="shrink-0" />
          </header>

          <Provenance rule={rule} origin={origin} />

          <div className={cn("mt-4", origin !== "regulation" && origin !== "hard" && "border-l-2 border-navy-900/80 pl-4")}>
            {origin === "ruled" || origin === "rejected" ? <MicroLabel className="mb-1 block">became</MicroLabel> : null}
            <RuleSentence rule={withoutCaseScope(rule)} className="max-w-[68ch] text-[15.5px] leading-[1.6]" />
            <CaseScope rule={rule} />
          </div>

          {family.pending ? <PendingNote pending={family.pending} onReview={live && actions.onWiden ? () => actions.onWiden?.(rule) : undefined} /> : null}

          <footer className="mt-5 flex flex-wrap items-center gap-2">
            {canWiden && actions.onWiden ? (
              <Tooltip>
                <TooltipTrigger asChild>
                  <button type="button" aria-label={`Widen ${ruleRef(rule)}`} onClick={() => actions.onWiden?.(rule)} className={BUTTON}>
                    <Waypoints className="size-3.5 text-slate-500" aria-hidden="true" />
                    Widen
                  </button>
                </TooltipTrigger>
                <TooltipContent>Drop one case-only condition. One rung at a time.</TooltipContent>
              </Tooltip>
            ) : null}
            {canRevert && actions.onRevert ? (
              <button type="button" aria-label={`Revert ${ruleRef(rule)}`} onClick={() => actions.onRevert?.(rule)} className={BUTTON}>
                <RotateCcw className="size-3.5 text-slate-500" aria-hidden="true" />
                Revert
              </button>
            ) : null}
            <Link to={`/trace?tab=blame&target=${encodeURIComponent(ruleRef(rule))}`} aria-label={`Blame ${ruleRef(rule)}`} className="inline-flex h-8 items-center gap-1.5 rounded-lg px-2.5 text-[13px] text-slate-500 transition-colors hover:bg-cloud-50 hover:text-navy-900">
              <GitCommitVertical className="size-3.5" aria-hidden="true" />
              Blame
            </Link>
          </footer>
        </div>

        <Record family={family} />
      </div>
    </motion.article>
  );
}

const BUTTON =
  "inline-flex h-8 items-center gap-1.5 rounded-lg bg-white px-3 text-[13px] font-medium text-navy-900 shadow-[inset_0_0_0_1px_var(--color-cloud-300)] transition-colors hover:bg-cloud-50 focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-metar-ink";

// ---------- scope copied from the case ----------
function CaseScope({ rule }: { rule: Rule }) {
  const keys = caseKeys(rule);
  if (!keys.length) return null;
  return (
    <div className="mt-2.5 flex flex-wrap items-center gap-1.5">
      <MicroLabel className="mr-0.5">only where</MicroLabel>
      {keys.map((k) => (
        <span key={k} title={`${k} = ${String(rule.scope[k]).slice(5)} (copied from the case)`} className="inline-flex h-6 items-center rounded-md bg-cloud-100 px-2 text-[12.5px] text-slate-600">
          {caseClause(k, rule.scope[k])}
        </span>
      ))}
      <span className="text-[12px] text-slate-400">copied from the case</span>
    </div>
  );
}

// ---------- provenance ----------
function Provenance({ rule, origin }: { rule: Rule; origin: Origin }) {
  const prose = rule.origin_example && !isId(rule.origin_example) ? rule.origin_example : null;
  if (origin === "learned") {
    return (
      <div className="mt-4">
        <SupportTicks support={rule.support} detail={prose} />
      </div>
    );
  }
  if (origin === "ruled" || origin === "rejected") return <RulerWords rule={rule} origin={origin} />;
  if (origin === "regulation" && prose) {
    const src = splitSource(prose);
    return (
      <div className="mt-4 rounded-lg bg-cloud-50 px-4 py-3">
        <p className="text-[14.5px] leading-relaxed text-navy-900">
          {src.cite ? <span className="font-semibold">{src.cite}: </span> : null}
          <Marked text={src.body} grounding={rule.grounding} />
        </p>
        {src.gloss ? <p className="mt-1.5 text-[13px] text-slate-500">{src.gloss}</p> : null}
      </div>
    );
  }
  return null;
}

/**
 * The ruler's own words, with the phrases that ground the rule highlighted. The words come from the
 * rule's blame (its ruling commit carries the quote); without it, the grounding phrases alone.
 */
function RulerWords({ rule, origin }: { rule: Rule; origin: "ruled" | "rejected" }) {
  // The rule carries the ruler's words itself now (origin_quote, #13); older servers only have them in blame.
  const blame = useBlame(rule.origin_quote ? undefined : ruleRef(rule));
  const quote = rule.origin_quote ?? blame.data?.steps.find((s) => s.commit.kind === "ruling" && s.quote)?.quote;
  const ruler = RULER[rule.tier] ?? rule.authority_required;
  const phrases = Object.values(rule.grounding ?? {}).filter(Boolean);
  const about = aboutText(rule);
  return (
    <div className="mt-4">
      <p className="flex items-start gap-2 text-[13px] text-slate-500">
        <span aria-hidden="true" className="mt-px inline-flex">
          <RoleAvatar role={ruler} size="sm" />
        </span>
        <span className="min-w-0">
          <span className="font-medium text-navy-900">{ROLE_LABEL[ruler]}</span> {origin === "rejected" ? (rule.kind === "release" ? "rejected a release proposal" : "rejected a proposal") : "ruled"}
          {about ? <> · {about}</> : null}
        </span>
      </p>
      <div className="mt-2.5 rounded-lg bg-cloud-50 px-4 py-3">
        {quote ? (
          <GroundedQuote text={quote} grounding={rule.grounding} className="text-[15px] leading-relaxed" />
        ) : blame.isLoading ? (
          <span className="block h-5 w-4/5 animate-pulse rounded bg-cloud-100" aria-hidden="true" />
        ) : phrases.length ? (
          <p className="flex flex-wrap gap-x-2 gap-y-1 text-[14.5px] leading-relaxed text-navy-900">
            {phrases.map((p) => (
              <mark key={p} className="rounded-sm bg-metar-wash px-1 text-navy-900 shadow-[inset_0_-2px_0_var(--color-metar)]">
                &ldquo;{p}&rdquo;
              </mark>
            ))}
          </p>
        ) : (
          <p className="text-[13.5px] text-slate-500">The ruling&rsquo;s words are in its blame.</p>
        )}
      </div>
    </div>
  );
}

function aboutText(rule: Rule): ReactNode {
  const ex = rule.origin_example;
  if (!ex) return null;
  const flight = flightOf(ex);
  if (flight) {
    return (
      <>
        on{" "}
        <Link to={`/flights/${encodeURIComponent(flight)}`} className="font-mono text-[12px] text-navy-900 underline decoration-cloud-300 underline-offset-2 hover:decoration-navy-900">
          {shortId(ex)}
        </Link>
      </>
    );
  }
  const storm = stormName(ex);
  return storm ? `on the ${storm} cohort` : <span className="font-mono text-[12px]">on {ex}</span>;
}

/** A wider version drafted and replayed, not yet confirmed: v1 stays in force meanwhile. */
function PendingNote({ pending, onReview }: { pending: Rule; onReview?: () => void }) {
  return (
    <div className="mt-4 flex flex-wrap items-center gap-2 rounded-lg px-3 py-2 text-[13px] text-slate-600 shadow-[inset_0_0_0_1px_var(--color-cloud-300)]">
      <RuleStatusChip status={pending.status} />
      <span className="font-mono text-[12px] text-navy-900">{ruleRef(pending)}</span>
      <span>waiting for confirmation</span>
      {onReview ? (
        <button type="button" aria-label={`Review ${ruleRef(pending)}`} onClick={onReview} className="ml-auto rounded-md px-2 py-1 text-[12.5px] font-medium text-metar-ink hover:bg-cloud-50">
          Review
        </button>
      ) : null}
    </div>
  );
}

// ---------- the record ----------
function Record({ family }: { family: RuleFamily }) {
  const rule = family.current;
  const applies = validFromText(rule);
  const flight = flightOf(rule.origin_example);
  return (
    <dl className="grid grid-cols-2 content-start gap-x-4 gap-y-4 border-t border-cloud-100 px-5 py-5 text-[13px] sm:grid-cols-3 md:grid-cols-2 md:border-l md:border-t-0 md:px-5 md:py-6">
      <Item label="Authority">
        <span className="inline-flex items-center gap-1.5">
          <span aria-hidden="true" className="inline-flex">
            <RoleAvatar role={rule.authority_required} size="sm" />
          </span>
          <span className="text-navy-900">{ROLE_LABEL[rule.authority_required]}</span>
        </span>
      </Item>
      <Item label="Cited">
        {rule.times_cited ? (
          <Link
            to={`/trace?tab=commits&q=${encodeURIComponent(rule.id)}`}
            title={`Commits that mention ${rule.id}`}
            aria-label={`Cited ${rule.times_cited} times: commits that mention ${rule.id}`}
            className="figure text-[15px] font-semibold text-navy-900 underline decoration-cloud-300 underline-offset-[3px] hover:decoration-navy-900"
          >
            <TickingCount value={rule.times_cited} />×
          </Link>
        ) : (
          <span className="figure text-[15px] font-semibold text-slate-400">0×</span>
        )}
      </Item>
      <Item label="Applies">
        <span className="text-navy-900" title={applies.long}>
          {applies.short}
        </span>
      </Item>
      <Item label="Recorded">
        <span className="figure text-navy-900" title={stamp(rule.recorded_at)}>
          {stamp(rule.recorded_at).split(" · ")[0]}
        </span>
      </Item>
      <Item label="Versions">
        <VersionTrail versions={family.versions} current={rule} />
      </Item>
      {(isId(rule.origin_example) && rule.origin_example) || rule.origin_ruling_id ? (
        <Item label="Origin">
          {rule.origin_example && isId(rule.origin_example) ? (
            flight ? (
              <Link to={`/flights/${encodeURIComponent(flight)}`} className="inline-flex items-center gap-0.5 font-mono text-[12px] text-navy-900 hover:underline">
                {shortId(rule.origin_example)}
                <ArrowUpRight className="size-3 text-slate-400" aria-hidden="true" />
              </Link>
            ) : (
              <span className={cn("block break-words text-slate-600", stormName(rule.origin_example) ? "text-[13px]" : "font-mono text-[11.5px]")}>{stormName(rule.origin_example) ?? rule.origin_example}</span>
            )
          ) : null}
          {rule.origin_ruling_id ? <span className="mt-0.5 block whitespace-nowrap font-mono text-[11px] text-slate-400">ruling {rule.origin_ruling_id}</span> : null}
        </Item>
      ) : null}
    </dl>
  );
}

function Item({ label, children }: { label: string; children: ReactNode }) {
  return (
    <div className="min-w-0">
      <dt className="micro mb-1.5 text-slate-400">{label}</dt>
      <dd className="min-w-0">{children}</dd>
    </div>
  );
}
