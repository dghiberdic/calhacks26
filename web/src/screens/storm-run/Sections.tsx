import { Link } from "react-router";
import { ArrowRight } from "lucide-react";
import type { CfoMetrics, Question, Role, StormRun, TraceEvent } from "@/api/types";
import { MicroLabel, StatusChip } from "@/components/chips";
import { ConfidenceLine, Empty, FeedRow, Money, Panel, RoleAvatar, RoutedTo } from "@/components/kit";
import { ROLE_LABEL, count } from "@/lib/format";
import { cn } from "@/lib/utils";

/** "€34,650 drafted: not €0, not €99,000". The three numbers a CFO argues about, from the API. */
export function LiabilityTiles({ run, cfo, recodedFlight }: { run: StormRun; cfo: CfoMetrics | undefined; recodedFlight: string | null }) {
  const c = run.counters ?? {};
  return (
    <div className="grid gap-3 md:grid-cols-3">
      <Panel className="relative overflow-hidden">
        <MicroLabel>{recodedFlight ? `${recodedFlight} · ` : ""}EU261 compensation liability</MicroLabel>
        <p className="display mt-2 text-[36px] text-navy-900" data-testid="ns31-liability">
          {cfo ? <Money cents={cfo.drafted_liability_cents} /> : "—"} <span className="text-[15px] font-medium text-slate-500 [font-stretch:100%]">drafted</span>
        </p>
        {cfo ? (
          <p className="mt-2 text-[13px] leading-relaxed text-slate-500">
            Not <Money cents={cfo.cash_basis_cents} className="text-navy-900" /> (cash basis), not <Money cents={cfo.full_entitlement_cents} className="text-navy-900" /> (full Art. 7 entitlement if every passenger claims). ±5 pp is <Money cents={cfo.sensitivity_5pp_cents} />.
          </p>
        ) : null}
        <Link to="/close" className="mt-3 inline-flex items-center gap-1 text-[13px] font-medium text-metar-ink hover:underline">
          Liability & close <ArrowRight className="size-3.5" aria-hidden="true" />
        </Link>
      </Panel>
      <Panel>
        <MicroLabel>Storm total · day 1</MicroLabel>
        <p className="display mt-2 text-[36px] text-navy-900">
          <Money cents={run.liability_drafted_cents} />
        </p>
        <p className="mt-2 text-[13px] leading-relaxed text-slate-500">
          EU261 compensation liability, drafted, pending approval.
          {cfo?.held_for_legal_cents ? (
            <>
              {" "}
              Includes <Money cents={cfo.held_for_legal_cents} className="text-held-ink" /> held for Legal.
            </>
          ) : null}{" "}
          Weather flights: no compensation; refunds and care still due.
        </p>
      </Panel>
      <Panel>
        <MicroLabel>Payouts</MicroLabel>
        <p className="display mt-2 text-[36px] text-navy-900">{count(c.drafted)}</p>
        <p className="mt-2 text-[13px] leading-relaxed text-slate-500">payouts drafted, pending Claims Lead approval. StormCheck drafts; it never releases a payment run.</p>
        <div className="mt-3 flex items-center gap-2 text-[12.5px] text-slate-500">
          <RoleAvatar role="claims_lead" size="sm" /> approves every payment
        </div>
      </Panel>
    </div>
  );
}

/** Plain tags for the four steps (FINAL_IDEA's workshop words, said the way an airline would). */
const LEARN_LABEL = ["from its own history", "overnight", "asks a person", "becomes policy"] as const;

/** Learns → Runs → Escalates → Improves ↻, four small cards in a row (THREAD_JUSTIN J1, plan §6). */
export function LearnsStrip({ run }: { run: StormRun }) {
  const c = run.counters ?? {};
  const roles = [...new Set(run.questions.map((q) => q.routed_to))] as Role[];
  const recoded = run.flights.filter((r) => r.decision?.recoded).length;
  const [first, ...more] = run.learned;
  const cards: { label: (typeof LEARN_LABEL)[number]; title: string; body: React.ReactNode; highlight?: boolean }[] = [
    {
      label: "from its own history",
      title: "Learns",
      body: first ? (
        <>
          {first.text}
          {first.support ? <span className="font-mono text-[11.5px] text-slate-400"> · {first.support}</span> : null}
          {more.length ? (
            <Link to="/policies" className="mt-1.5 block text-[12.5px] font-medium text-metar-ink hover:underline">
              +{count(more.length)} more it learned
            </Link>
          ) : null}
        </>
      ) : (
        "Mined from the airline's own history at onboarding."
      ),
    },
    {
      label: "overnight",
      title: "Runs",
      body: (
        <>
          Re-checked {count(c.cancelled)} cancellations overnight{recoded ? `, recoded ${count(recoded)}` : ""}, drafted {count(c.drafted)} payouts and the liability.
        </>
      ),
    },
    {
      label: "asks a person",
      title: "Escalates",
      highlight: true,
      body: (
        <>
          <span className="mb-2 flex -space-x-1.5">
            {roles.map((r) => (
              <RoleAvatar key={r} role={r} size="sm" className="ring-2 ring-white" />
            ))}
          </span>
          Asked {count(c.questions)} {c.questions === 1 ? "question" : "questions"}, each to the person who owns it{c.held ? `; ${count(c.held)} passengers held until they answer` : ""}.
        </>
      ),
    },
    {
      label: "becomes policy",
      title: "Improves",
      body: (
        <>
          Every ruling becomes a scoped, versioned rule. Repeat questions: <span className="figure font-semibold text-navy-900">{count(c.repeat_questions ?? 0)}</span>
          {c.rules_cited ? <> · rules cited {count(c.rules_cited)}×</> : null}.
        </>
      ),
    },
  ];
  return (
    <ol className="grid gap-3 sm:grid-cols-2 xl:grid-cols-4" aria-label="How it works">
      {cards.map((card, i) => (
        <li key={card.label} className={cn("relative flex flex-col rounded-xl bg-card p-4 shadow-[0_0_0_1px_var(--color-cloud-200)]", card.highlight && "shadow-[0_0_0_1.5px_var(--color-held)]")}>
          <div className="flex items-center justify-between gap-2">
            <h3 className="text-[14px] font-semibold text-navy-900">
              <span className="mr-1.5 font-mono text-[11px] font-normal text-slate-400">{String(i + 1).padStart(2, "0")}</span>
              {card.title}
              {i === cards.length - 1 ? (
                <span className="ml-1 text-slate-400" aria-label="and back to Learns">
                  ↻
                </span>
              ) : null}
            </h3>
            <StatusChip tone={card.highlight ? "held" : "outline"} dot={false} className="h-5 text-[10.5px]">
              {card.label}
            </StatusChip>
          </div>
          <div className="mt-2 text-[13px] leading-relaxed text-slate-600">{card.body}</div>
          {i < cards.length - 1 ? (
            <ArrowRight aria-hidden="true" className="absolute -right-[11px] top-1/2 z-10 hidden size-[18px] -translate-y-1/2 rounded-full bg-background p-0.5 text-slate-400 xl:block" />
          ) : null}
        </li>
      ))}
    </ol>
  );
}

/** "Waiting on Claims Lead 3h · reminder sent · 4,761 others settled" (plan §2 Q5; N from the API). */
function ReminderChip({ q }: { q: Question }) {
  if (q.status !== "reminded") return null;
  const waitedH = q.remind_at ? Math.round((Date.parse(q.remind_at) - Date.parse(q.asked_at)) / 3_600_000) : null;
  return (
    <p className="mt-1.5 inline-flex flex-wrap items-center gap-x-1.5 rounded-md bg-held-wash px-2 py-0.5 font-mono text-[11.5px] text-held-ink">
      <span>
        Waiting on {ROLE_LABEL[q.routed_to]}
        {waitedH ? ` ${waitedH}h` : ""}
      </span>
      <span aria-hidden="true">·</span>
      <span>reminder sent</span>
      {q.others_settled ? (
        <>
          <span aria-hidden="true">·</span>
          <span>{count(q.others_settled)} others settled</span>
        </>
      ) : null}
    </p>
  );
}

/** The 1% it asked about, one card per pattern. */
export function QuestionsPreview({ questions }: { questions: Question[] }) {
  if (!questions.length) return <Empty title="Nothing to ask">Every decision was clear enough to draft.</Empty>;
  return (
    <ul className="flex flex-col divide-y divide-cloud-100">
      {questions.map((q) => (
        <li key={q.id} className="py-3.5 first:pt-0 last:pb-0">
          <div className="flex flex-wrap items-start justify-between gap-2">
            <Link to="/questions" className="text-[14.5px] font-medium text-navy-900 hover:underline">
              {q.title}
            </Link>
            <span className="font-mono text-[11.5px] text-slate-400">{q.case_refs.length > 1 ? `${q.case_refs.length} flights` : /^[A-Z0-9]{2}\d/.test(q.case_refs[0] ?? "") ? q.case_refs[0].split("@")[0] : null}</span>
          </div>
          <div className="mt-1.5 flex flex-wrap items-center gap-x-3 gap-y-1">
            <RoutedTo role={q.routed_to} holdsCents={q.holds_cents} />
            <ConfidenceLine confidence={q.confidence} reason={q.reason_tag.replace(/-/g, " ")} showCaps={false} className="text-[11.5px]" />
          </div>
          <ReminderChip q={q} />
        </li>
      ))}
    </ul>
  );
}

/**
 * The live activity feed. On a laptop it takes the height of the row (the questions set it, via
 * `contain: size`) and scrolls inside, so the two panels end level.
 */
export function FeedPanel({ events }: { events: TraceEvent[] }) {
  return (
    <section className="flex flex-col rounded-xl bg-card shadow-[0_0_0_1px_var(--color-cloud-200),0_1px_2px_rgba(13,21,36,0.04)] lg:min-h-[360px] lg:[contain:size]" aria-label="What it did">
      <div className="flex items-center justify-between gap-3 px-5 pt-4">
        <h2 className="text-[14.5px] font-semibold text-navy-900">What it did</h2>
        <Link to="/trace" className="inline-flex items-center gap-1 text-[12.5px] font-medium text-metar-ink hover:underline">
          Trace <ArrowRight className="size-3.5" aria-hidden="true" />
        </Link>
      </div>
      <ol className="mt-1 max-h-[440px] min-h-0 flex-1 overflow-y-auto px-5 pb-2 lg:max-h-none" aria-live="polite">
        {events.slice(0, 40).map((e) => (
          <FeedRow key={e.seq} event={e} className="border-t border-cloud-100 first:border-t-0" />
        ))}
      </ol>
      {events.length ? null : <p className="px-5 pb-5 text-[13px] text-slate-500">No activity yet.</p>}
    </section>
  );
}
