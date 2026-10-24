import { useMemo, useState, type ReactNode } from "react";
import { Link, useSearchParams } from "react-router";
import { motion, useReducedMotion } from "motion/react";
import { ArrowRight, CornerDownRight } from "lucide-react";
import { ApiError } from "@/api/client";
import { useBlame, useRules, useStormRun, useStorms } from "@/api/queries";
import type { Blame, BlameStep } from "@/api/types";
import { MicroLabel } from "@/components/chips";
import { Empty, ErrorNote, Shimmer } from "@/components/kit";
import { longDate, zulu } from "@/lib/format";
import { HERO_STORM } from "@/lib/storms";
import { cn } from "@/lib/utils";
import { STEP_NAME, receiptText, ruleRefIn, shortHash, stepKind, suggestTargets, type BlameTarget, type StepKind } from "./model";
import { CopyButton, Principal } from "./parts";

/**
 * J5 · Blame: walk one euro (or one rule) back through every commit that produced it, ending at the
 * raw observation. Read top to bottom like a receipt an auditor can keep.
 */
export function BlameTab() {
  const [params, setParams] = useSearchParams();
  const storms = useStorms();
  const stormId = storms.data?.find((s) => s.id === HERO_STORM)?.id ?? storms.data?.[0]?.id;
  const run = useStormRun(stormId);
  const rules = useRules();
  const targets = useMemo(() => suggestTargets(run.data, rules.data), [run.data, rules.data]);
  // The default waits for both sources, so it doesn't jump from a rule to NS31 as they arrive.
  const settled = !storms.isLoading && !run.isLoading && !rules.isLoading;
  const target = params.get("target") || (settled ? targets[0]?.id : null) || null;
  const blame = useBlame(target ?? undefined);
  const choose = (id: string) =>
    setParams(
      (prev) => {
        const next = new URLSearchParams(prev);
        next.set("tab", "blame");
        next.set("target", id);
        return next;
      },
      { replace: true },
    );
  const picking = !target && !settled;

  return (
    <div className="grid gap-5 lg:grid-cols-[272px_minmax(0,1fr)] lg:gap-7">
      <TargetPicker targets={targets} current={target} onChoose={choose} loading={picking} />
      <div className="min-w-0">
        {!target ? (
          picking ? (
            <ReceiptSkeleton />
          ) : (
            <Empty title="Pick something to blame">Choose a target, or type any flight, coupon, journal or rule@version id.</Empty>
          )
        ) : blame.isLoading ? (
          <ReceiptSkeleton />
        ) : blame.isError ? (
          <div>
            <ErrorNote error={blame.error} onRetry={blame.error instanceof ApiError && blame.error.status === 404 ? undefined : () => void blame.refetch()} />
            <button
              type="button"
              onClick={() =>
                setParams(
                  (prev) => {
                    const next = new URLSearchParams(prev);
                    next.set("tab", "live");
                    return next;
                  },
                  { replace: true },
                )
              }
              className="mt-3 inline-flex items-center gap-1 text-[13px] font-medium text-metar-ink hover:underline"
            >
              Events about {target} <ArrowRight className="size-3.5" aria-hidden="true" />
            </button>
          </div>
        ) : blame.data && blame.data.steps.length ? (
          <Receipt blame={blame.data} />
        ) : (
          <Empty title="No commits behind this id">{target} has no recorded chain yet.</Empty>
        )}
      </div>
    </div>
  );
}

// ---------- picker ----------
function TargetPicker({ targets, current, onChoose, loading }: { targets: BlameTarget[]; current: string | null; onChoose: (id: string) => void; loading: boolean }) {
  const [draft, setDraft] = useState("");
  const custom = current && !targets.some((t) => t.id === current);
  return (
    <aside className="min-w-0">
      <MicroLabel className="mb-2 block">Start from</MicroLabel>
      {loading ? (
        <div className="flex flex-col gap-2">
          <Shimmer className="h-14" />
          <Shimmer className="h-14" />
          <Shimmer className="h-14" />
        </div>
      ) : (
        <ul className="-mx-1 flex gap-1.5 overflow-x-auto px-1 pb-1 lg:mx-0 lg:flex-col lg:overflow-visible lg:px-0 lg:pb-0" aria-label="Targets">
          {targets.map((t) => {
            const active = t.id === current;
            return (
              <li key={t.id} className="shrink-0 lg:shrink">
                <button
                  type="button"
                  aria-pressed={active}
                  onClick={() => onChoose(t.id)}
                  className={cn(
                    "w-full rounded-lg px-3 py-2.5 text-left transition-colors focus-visible:outline-2 focus-visible:outline-offset-1 focus-visible:outline-metar-ink",
                    active ? "bg-navy-900 text-cloud-50" : "bg-white text-navy-900 shadow-[inset_0_0_0_1px_var(--color-cloud-200)] hover:bg-cloud-25",
                  )}
                >
                  <span className="block whitespace-nowrap text-[13.5px] font-medium lg:whitespace-normal">{t.title}</span>
                  <span className={cn("mt-0.5 block whitespace-nowrap text-[12px] lg:whitespace-normal", active ? "text-cloud-400" : "text-slate-500")}>{t.hint}</span>
                </button>
              </li>
            );
          })}
          {custom ? (
            <li className="shrink-0 lg:shrink">
              <span className="block rounded-lg bg-navy-900 px-3 py-2.5 font-mono text-[12px] text-cloud-50">{current}</span>
            </li>
          ) : null}
        </ul>
      )}
      <form
        className="mt-3 flex gap-1.5"
        onSubmit={(e) => {
          e.preventDefault();
          const id = draft.trim();
          if (id) onChoose(id);
        }}
      >
        <label className="sr-only" htmlFor="blame-target">
          Any id: flight, coupon, journal or rule@version
        </label>
        <input
          id="blame-target"
          value={draft}
          onChange={(e) => setDraft(e.target.value)}
          placeholder="any id, e.g. JE-… or R-…@1"
          className="h-9 min-w-0 flex-1 rounded-lg bg-white px-3 font-mono text-[12px] text-navy-900 shadow-[inset_0_0_0_1px_var(--color-cloud-300)] outline-none placeholder:font-sans placeholder:text-[12.5px] placeholder:text-slate-400 focus:shadow-[inset_0_0_0_1.5px_var(--color-metar-ink)]"
        />
        <button type="submit" disabled={!draft.trim()} className="h-9 rounded-lg bg-navy-900 px-3 text-[13px] font-semibold text-cloud-50 disabled:opacity-40">
          Blame
        </button>
      </form>
    </aside>
  );
}

// ---------- receipt ----------
function Receipt({ blame }: { blame: Blame }) {
  const reduce = useReducedMotion();
  const origin = typeof window === "undefined" ? "" : window.location.origin;
  const link = `${origin}/trace?tab=blame&target=${encodeURIComponent(blame.target)}`;
  const commits = new Set(blame.steps.map((s) => s.commit.hash)).size;
  return (
    <article className="overflow-hidden rounded-2xl bg-card shadow-[0_0_0_1px_var(--color-cloud-200),0_1px_2px_rgba(13,21,36,0.04),0_12px_32px_-12px_rgba(13,21,36,0.10)]" aria-label={`Blame for ${blame.target}`}>
      <header className="flex flex-wrap items-start justify-between gap-3 px-5 pb-4 pt-5 md:px-7">
        <div className="min-w-0">
          <MicroLabel>
            Blame · {blame.steps.length} steps · {commits} commit{commits === 1 ? "" : "s"}
          </MicroLabel>
          <h2 className="mt-1 break-all text-[15px] font-bold text-navy-900">
            <span className="font-mono">{blame.target}</span>
          </h2>
        </div>
        <div className="flex gap-2">
          <CopyButton text={receiptText(blame.target, blame.steps, origin)} label="Copy receipt" what="Receipt" />
          <CopyButton text={link} label="Copy link" what="Link" />
        </div>
      </header>
      <Perforation />
      <ol className="relative px-5 py-6 md:px-7" data-testid="blame-chain" aria-label="From the amount back to the observation">
        <motion.span
          aria-hidden="true"
          className="absolute bottom-10 left-[33px] top-9 w-px origin-top bg-cloud-300 md:left-[41px]"
          initial={reduce ? false : { scaleY: 0 }}
          animate={{ scaleY: 1 }}
          transition={{ duration: 0.7, ease: [0.16, 1, 0.3, 1] }}
        />
        {blame.steps.map((step, i) => (
          <Step key={`${step.commit.hash}-${i}`} step={step} n={i + 1} last={i === blame.steps.length - 1} />
        ))}
      </ol>
      <Perforation />
      <footer className="px-5 py-4 text-[12.5px] leading-relaxed text-slate-500 md:px-7">
        Every step is a content-hashed commit. <span className="font-mono text-[11.5px] text-slate-600">make verify</span> recomputes them offline, with no LLM calls.
      </footer>
    </article>
  );
}

function Perforation() {
  return <div className="mx-5 border-t border-dashed border-cloud-300 md:mx-7" aria-hidden="true" />;
}

function Step({ step, n, last }: { step: BlameStep; n: number; last: boolean }) {
  const reduce = useReducedMotion();
  const kind = stepKind(step);
  return (
    <motion.li
      initial={reduce ? false : { opacity: 0, y: 6 }}
      animate={{ opacity: 1, y: 0 }}
      transition={{ delay: 0.08 + n * 0.07, duration: 0.4, ease: [0.16, 1, 0.3, 1] }}
      className={cn("relative grid grid-cols-[28px_minmax(0,1fr)] gap-x-4", !last && "pb-7")}
      data-step-kind={kind}
    >
      <span className="relative z-10 flex flex-col items-center pt-0.5" aria-hidden="true">
        <span
          className={cn(
            "flex size-7 items-center justify-center rounded-full font-mono text-[10.5px] font-bold",
            kind === "metar" ? "bg-metar text-white" : kind === "money" ? "bg-navy-900 text-cloud-50" : "bg-card text-navy-900 shadow-[inset_0_0_0_1.5px_var(--color-navy-800)]",
          )}
        >
          {String(n).padStart(2, "0")}
        </span>
      </span>
      <div className="min-w-0 pt-0.5">
        <MicroLabel tone={kind === "metar" ? "metar" : "slate"}>{STEP_NAME[kind]}</MicroLabel>
        <div className="mt-1.5">
          <StepBody step={step} kind={kind} />
        </div>
        <CommitMeta step={step} />
      </div>
    </motion.li>
  );
}

const MONEY_HEAD = /^\s*(\(?[+−-]?€[\d,]+(?:\.\d{2})?\)?)\s*(.*)$/;

function StepBody({ step, kind }: { step: BlameStep; kind: StepKind }) {
  const quote = step.quote?.trim();
  switch (kind) {
    case "money": {
      const m = step.label.match(MONEY_HEAD);
      return m ? (
        <>
          <p className="display text-[30px] leading-none text-navy-900 md:text-[34px]">{m[1]}</p>
          {m[2] ? <p className="mt-2 text-[14px] leading-snug text-slate-600">{m[2].replace(/^[·\s]+/, "")}</p> : null}
          {quote ? <Quote>{quote}</Quote> : null}
        </>
      ) : (
        <Label text={step.label} quote={quote} big />
      );
    }
    case "rule": {
      const ref = ruleRefIn(step.label);
      return (
        <>
          <p className="text-[15px] leading-snug text-navy-900">
            {ref ? <RuleLinked label={step.label} refText={ref} /> : step.label}
          </p>
          {quote ? <Quote>{quote}</Quote> : null}
        </>
      );
    }
    case "ruling":
      return (
        <figure>
          {quote ? (
            <blockquote className="border-l-2 border-navy-900/80 pl-4 text-[16px] leading-relaxed text-navy-900">&ldquo;{quote}&rdquo;</blockquote>
          ) : null}
          <figcaption className={cn("text-[13px] text-slate-500", quote && "mt-2")}>{step.label}</figcaption>
        </figure>
      );
    case "span":
      return (
        <>
          <p className="text-[14px] leading-snug text-slate-600">{step.label}</p>
          {quote ? (
            <pre className="mt-2 whitespace-pre-wrap break-words rounded-lg bg-cloud-50 px-3.5 py-3 text-[12.5px] leading-relaxed text-navy-900 shadow-[inset_0_0_0_1px_var(--color-cloud-200)]">
              <span className="font-mono">{quote}</span>
            </pre>
          ) : null}
        </>
      );
    case "metar":
      return (
        <>
          <p className="text-[14px] leading-snug text-navy-900">{step.label}</p>
          {quote ? (
            <pre className="mt-2 whitespace-pre-wrap break-words rounded-lg bg-metar-wash px-3.5 py-3 text-[13px] leading-relaxed text-metar-ink shadow-[inset_0_0_0_1px_color-mix(in_srgb,var(--color-metar)_30%,transparent)]">
              <span className="font-mono">{quote}</span>
            </pre>
          ) : null}
        </>
      );
    default:
      return <Label text={step.label} quote={quote} />;
  }
}

function Label({ text, quote, big }: { text: string; quote?: string; big?: boolean }) {
  return (
    <>
      <p className={cn("leading-snug text-navy-900", big ? "text-[16px] font-medium" : "text-[15px]")}>{text}</p>
      {quote ? <Quote>{quote}</Quote> : null}
    </>
  );
}

function Quote({ children }: { children: ReactNode }) {
  return <p className="mt-2 border-l-2 border-cloud-300 pl-3 text-[13.5px] leading-relaxed text-slate-600">&ldquo;{children}&rdquo;</p>;
}

function RuleLinked({ label, refText }: { label: string; refText: string }) {
  const at = label.indexOf(refText);
  const id = refText.split("@")[0];
  return (
    <>
      {label.slice(0, at)}
      <Link to={`/policies#${encodeURIComponent(id)}`} className="font-mono text-[13.5px] font-bold text-navy-900 underline decoration-cloud-300 underline-offset-[3px] hover:decoration-navy-900">
        {refText}
      </Link>
      {label.slice(at + refText.length)}
    </>
  );
}

/** `journal_event · d44ec17 · books · 25 Jan 09:00Z`, the hash opening the commit in the log. */
function CommitMeta({ step }: { step: BlameStep }) {
  const c = step.commit;
  return (
    <p className="mt-2.5 flex flex-wrap items-center gap-x-2 gap-y-1 text-[11.5px] text-slate-400">
      <CornerDownRight className="size-3 text-cloud-400" aria-hidden="true" />
      <span className="font-mono">{c.kind}</span>
      <span aria-hidden="true">·</span>
      <Link to={`/trace?tab=commits&commit=${encodeURIComponent(c.hash)}`} aria-label={`Open commit ${shortHash(c.hash)} in the log`} className="font-mono text-metar-ink hover:underline" title={c.hash}>
        {shortHash(c.hash)}
      </Link>
      <span aria-hidden="true">·</span>
      <Principal principal={c.actor} className="[&>span:last-child]:text-[11px] [&>span:last-child]:text-slate-400" />
      <span aria-hidden="true">·</span>
      <span className="figure">
        {longDate(c.at)} · {zulu(c.at)}
      </span>
    </p>
  );
}

function ReceiptSkeleton() {
  return (
    <div className="rounded-2xl bg-card p-7 shadow-[0_0_0_1px_var(--color-cloud-200)]" aria-busy="true" aria-label="Loading blame">
      <Shimmer className="h-4 w-40" />
      <Shimmer className="mt-2 h-5 w-64" />
      <div className="mt-8 flex flex-col gap-7">
        {Array.from({ length: 5 }, (_, i) => (
          <div key={i} className="grid grid-cols-[28px_1fr] gap-4">
            <Shimmer className="size-7 rounded-full" />
            <div>
              <Shimmer className="h-3 w-24" />
              <Shimmer className="mt-2 h-5 w-4/5" />
            </div>
          </div>
        ))}
      </div>
    </div>
  );
}
