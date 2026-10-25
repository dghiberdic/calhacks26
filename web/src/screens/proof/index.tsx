import type { ReactNode } from "react";
import { Info } from "lucide-react";
import { ApiError } from "@/api/client";
import { useEvalReport } from "@/api/queries";
import type { EvalReport } from "@/api/types";
import { MicroLabel, StatusChip } from "@/components/chips";
import { Details, DetailsTitle, Empty, ErrorNote, PageHeader, Shimmer } from "@/components/kit";
import { count, eur, idDate, pct } from "@/lib/format";
import { HERO_STORM, stormName } from "@/lib/storms";
import { cn } from "@/lib/utils";
import { asFraction } from "@/screens/close/model";
import { RunsHero } from "./hero";
import { injectionSummary, liabilityVsActual, measures, orderedKinds, rangeIncludes, splitText } from "./model";
import { ReliabilityCard } from "./reliability";

const PANEL = "rounded-xl bg-card shadow-[0_0_0_1px_var(--color-cloud-200),0_1px_2px_rgba(13,21,36,0.04)]";
/** The contract's default for EvalReport.label, if a report ever arrives without one. */
const HONEST_LABEL = "calibrated on synthetic labels; validates the pipeline, not the world";

/** J8 · Proof: how we know. */
export default function ProofScreen() {
  const q = useEvalReport();
  return (
    <div className="mx-auto flex max-w-[1280px] flex-col gap-3">
      <PageHeader className="mb-3" eyebrow={<MicroLabel>Evaluation</MicroLabel>} title="Test results">
        Held-out scenarios test correct decisions, repeatability and unsafe inputs. The answer key is generated separately from the engine.
      </PageHeader>
      {q.isError && q.error instanceof ApiError && q.error.status === 404 ? (
        <Empty title="The eval hasn't run yet">
          The plain-Claude baseline, the scorecard and the reliability bins show here once the eval has written its report.{" "}
          <button type="button" onClick={() => void q.refetch()} className="font-medium text-metar-ink hover:underline">
            Check again
          </button>
        </Empty>
      ) : q.isError ? (
        <ErrorNote error={q.error} onRetry={() => void q.refetch()} />
      ) : !q.data ? (
        <>
          <Shimmer className="h-[440px] rounded-2xl" />
          <div className="grid grid-cols-[minmax(0,1fr)] gap-3 sm:grid-cols-2 lg:grid-cols-3">
            {Array.from({ length: 6 }, (_, i) => (
              <Shimmer key={i} className="h-[132px]" />
            ))}
          </div>
        </>
      ) : (
        <Report report={q.data} />
      )}
    </div>
  );
}

function Report({ report: r }: { report: EvalReport }) {
  const straight = asFraction(r.straight_through_pct);
  const lva = liabilityVsActual(r.liability_vs_actual);
  const all = measures(r.liability_vs_actual);
  const kinds = orderedKinds(r.calibration ?? {});
  const inj = injectionSummary(r.injections);
  const columns = Object.entries(r.real_vs_simulated ?? {});

  return (
    <>
      <RunsHero report={r} />
      <RunContext report={r} />

      {/* the honest framing stays in view: what is real, what is simulated, and what the calibration validates */}
      <section aria-labelledby="real-sim" className={cn(PANEL, "mt-3 px-5 pb-5 pt-4")}>
        <div className="flex items-start gap-3 rounded-lg bg-white px-4 py-3 shadow-[inset_0_0_0_1.5px_var(--color-navy-900)]" data-testid="honest-label">
          <Info className="mt-0.5 size-[18px] shrink-0 text-navy-900" aria-hidden="true" />
          <p className="text-[15px] font-medium leading-snug text-navy-900 first-letter:uppercase">{r.label ?? HONEST_LABEL}</p>
        </div>
        <h2 id="real-sim" className="mt-4 text-[15.5px] font-semibold text-navy-900">
          Real vs simulated
        </h2>
        {columns.length ? (
          <div className={cn("mt-2 grid gap-x-6 gap-y-4", columns.length > 1 && "sm:grid-cols-2", columns.length > 2 && "lg:grid-cols-3")}>
            {columns.map(([key, items]) => (
              <div key={key}>
                <h3 className="flex items-center gap-2 text-[13px] font-semibold capitalize text-navy-900">
                  <span className={cn("size-2 rounded-full", /real/i.test(key) ? "bg-navy-900" : "shadow-[inset_0_0_0_1.5px_var(--color-slate-400)]")} aria-hidden="true" />
                  {key.replace(/_/g, " ")}
                </h3>
                <ul className="mt-1.5 flex flex-col">
                  {items.map((item) => (
                    <li key={item} className="border-t border-cloud-100 py-1.5 text-[13.5px] leading-snug text-slate-600 first:border-t-0">
                      {item}
                    </li>
                  ))}
                </ul>
              </div>
            ))}
          </div>
        ) : (
          <p className="mt-2 text-[13.5px] text-slate-500">Not reported.</p>
        )}
      </section>

      {/* the scorecard, the reliability bins and every measure: one click away */}
      <section aria-label="Detailed scorecard" className={cn(PANEL, "mt-3 px-5 py-3.5")}>
        <Details summary={<DetailsTitle title="Detailed scorecard" note="every number against the answer key" />}>
          <div className="grid grid-cols-[minmax(0,1fr)] gap-3 sm:grid-cols-2 lg:grid-cols-3">
            <Tile label="Straight-through" value={straight === null ? "—" : pct(straight)} sub="of passengers settled with no person in the loop" />
            <Tile label="Miscodes caught" value={`${count(r.miscodes_caught)} of ${count(r.miscodes_total)}`} sub={`planted cause miscodes, worth ${eur(r.miscodes_eur_cents)} in compensation`} />
            <Tile label="False holds" value={count(r.false_holds)} sub="held for a person when the answer key needed none" />
            <Tile label="Repeat questions" value={count(r.repeat_questions)} sub="asked again after a ruling" target="target 0" />
            <Tile label="Out-of-scope automated" value={count(r.out_of_scope_auto)} sub="cases outside EU261 decided without a person" target="target 0" />
            <Tile
              label="Liability vs actual"
              value={
                lva ? (
                  <span className="flex flex-col gap-1 text-[22px]">
                    {lva.value.map((v) => (
                      <span key={v}>{v}</span>
                    ))}
                  </span>
                ) : (
                  "—"
                )
              }
              sub={lva?.sub ?? "drafted liability against the claims that actually came"}
            />
          </div>

          {all.length ? (
            <div className="mt-5">
              <h3 className="text-[13.5px] font-semibold text-navy-900">Every measure</h3>
              <dl className="mt-1.5 grid grid-cols-[minmax(0,1fr)] gap-x-8 sm:grid-cols-2 lg:grid-cols-3">
                {all.map((m) => (
                  <div key={m.key} className="flex items-baseline justify-between gap-3 border-t border-cloud-100 py-1.5 text-[12.5px]">
                    <dt className="min-w-0 text-slate-500 first-letter:uppercase">{m.label}</dt>
                    <dd className="figure shrink-0 text-navy-900">{m.text}</dd>
                  </div>
                ))}
              </dl>
            </div>
          ) : null}

          <div className="mt-6">
            <h3 id="reliability" className="text-[15.5px] font-semibold text-navy-900">
              How often each confidence level was right
            </h3>
            <p className="mt-0.5 max-w-[86ch] text-[13px] leading-relaxed text-slate-500">
              Per decision kind: stated confidence against how often it was right, a dot per bin with its Wilson 95% interval and n. The diagonal is perfect calibration; coverage@0.9 is the share decided at 90% or more.
            </p>
            {kinds.length ? (
              <div className="mt-3 grid grid-cols-[minmax(0,1fr)] gap-3 sm:grid-cols-2 xl:grid-cols-4">
                {kinds.map((k) => (
                  <ReliabilityCard key={k} kind={k} bins={r.calibration[k] ?? []} coverage={r.coverage_at_90?.[k]} />
                ))}
              </div>
            ) : (
              <Empty title="No calibration reported" className="mt-3">
                Every decision kind is uncalibrated until the eval writes its bins.
              </Empty>
            )}
          </div>

          {inj?.rest.length ? (
            <div className="mt-6">
              <h3 className="text-[13.5px] font-semibold text-navy-900">Prompt injection, by count</h3>
              <dl className="mt-1.5 grid grid-cols-2 gap-x-6 sm:grid-cols-4" data-testid="injections-blocked">
                {inj.rest.map((x) => (
                  <div key={x.key} className="flex items-baseline justify-between gap-2 border-t border-cloud-100 py-1.5 text-[12.5px]">
                    <dt className="text-slate-500">{x.label}</dt>
                    <dd className="figure text-navy-900">{count(x.value)}</dd>
                  </div>
                ))}
              </dl>
            </div>
          ) : null}
        </Details>
      </section>
    </>
  );
}

/** "Learned on Jul 2023 – Dec 2024 · Scored on Jan – Jun 2025 (Storm Éowyn included, never seen) · 9 storms · 48,112 passengers". */
function RunContext({ report: r }: { report: EvalReport }) {
  const split = splitText(r.split);
  const heroDate = idDate(HERO_STORM);
  const scoreKey = Object.keys(r.split ?? {}).find((k) => /score|test/i.test(k));
  const heroScored = scoreKey ? rangeIncludes(r.split[scoreKey], heroDate) : false;
  const learnKey = Object.keys(r.split ?? {}).find((k) => /learn|train/i.test(k));
  const heroLearned = learnKey ? rangeIncludes(r.split[learnKey], heroDate) : false;
  return (
    <p className="figure px-1 text-[12.5px] leading-relaxed text-slate-500">
      {split.map((s, i) => (
        <span key={s.key}>
          {i ? " · " : ""}
          {s.label} <span className="text-navy-900">{s.value}</span>
          {s.key === scoreKey && heroScored && !heroLearned ? ` (${stormName(HERO_STORM) ?? HERO_STORM} included, never seen in learning)` : ""}
        </span>
      ))}
      {split.length ? " · " : ""}
      <span className="text-navy-900">{count(r.n_storms)}</span> storms · <span className="text-navy-900">{count(r.n_passengers)}</span> passengers
    </p>
  );
}

function Tile({ label, value, sub, target }: { label: string; value: ReactNode; sub: string; target?: string }) {
  return (
    <div className={cn(PANEL, "flex flex-col px-5 pb-4 pt-4")}>
      <div className="flex items-center justify-between gap-2">
        <span className="text-[13px] text-slate-500">{label}</span>
        {target ? (
          <StatusChip tone="outline" dot={false} className="h-5 text-[10.5px]">
            {target}
          </StatusChip>
        ) : null}
      </div>
      <div className="display-tight mt-2 text-[32px] leading-none text-navy-900">{value}</div>
      <p className="mt-2 text-[12.5px] leading-snug text-slate-500">{sub}</p>
    </div>
  );
}
