import type { ReactNode } from "react";
import { Link } from "react-router";
import { ArrowRight } from "lucide-react";
import type { CfoMetrics, Question, Role, StormRun, TraceEvent } from "@/api/types";
import { MicroLabel } from "@/components/chips";
import { Explain, Glossary } from "@/components/explain";
import { Details, Empty, FeedRow, Money, Panel, RoleAvatar, RoutedTo } from "@/components/kit";
import type { Term } from "@/lib/glossary";
import { count } from "@/lib/format";
import { plainIds } from "@/lib/plain";
import { cn } from "@/lib/utils";

const ArrowLink = ({ to, children }: { to: string; children: ReactNode }) => (
  <Link to={to} className="inline-flex items-center gap-1 text-[13px] font-medium text-metar-ink hover:underline">
    {children} <ArrowRight className="size-3.5" aria-hidden="true" />
  </Link>
);

function Tile({ label, figure, children, details, testId }: { label: ReactNode; figure: ReactNode; children: ReactNode; details?: ReactNode; testId?: string }) {
  return (
    <Panel className="flex flex-col">
      <MicroLabel>{label}</MicroLabel>
      <p className="display mt-2 text-[36px] text-navy-900" data-testid={testId}>
        {figure}
      </p>
      <div className="mt-2 flex-1 text-[13.5px] leading-relaxed text-slate-600">{children}</div>
      {details ? <Details className="mt-3">{details}</Details> : null}
    </Panel>
  );
}

/**
 * Current-period compensation, payouts awaiting review, and the selected storm's day-one estimate.
 * The period total may include other storm cohorts; the hero shows the individual flight estimate.
 */
export function LiabilityTiles({ run, cfo, recodedFlight }: { run: StormRun; cfo: CfoMetrics | undefined; recodedFlight: string | null }) {
  const c = run.counters ?? {};
  // The recoded flight's full id, for blame (€ → entitlement → rule → facts).
  const recodedFlightId = recodedFlight ? (run.flights.find((r) => r.decision?.recoded && r.flight.number === recodedFlight)?.flight.id ?? null) : null;
  const terms: Term[] = ["cash-basis", "full-entitlement", "claim-rate", "dr-cr", "ifrs15"];
  return (
    <div className="grid gap-3 md:grid-cols-3">
      <Tile
        label="Current-period compensation"
        testId="ns31-liability"
        figure={
          <>
            {cfo ? <Money cents={cfo.drafted_liability_cents} /> : "—"} <span className="text-[15px] font-medium text-slate-500 [font-stretch:100%]">drafted</span>
          </>
        }
        details={
          cfo ? (
            <div className="flex flex-col gap-3 text-[12.5px] leading-relaxed text-slate-500">
              <p>
                Not <Money cents={cfo.cash_basis_cents} /> on a cash basis or <Money cents={cfo.full_entitlement_cents} /> if every passenger claims. The estimate uses the expected claim rate.
              </p>
              <p>
                <span className="font-mono text-[12px] text-navy-900">Dr 4090 / Cr 2140</span>: a reduction of passenger revenue, and the EU261 compensation liability (2140), drafted, pending approval. If the claim rate moves 5 points, the amount moves <Money cents={cfo.sensitivity_5pp_cents} className="text-navy-900" />.
              </p>
              <Glossary terms={terms} />
              <span className="flex flex-wrap gap-x-4 gap-y-1">
                {recodedFlightId ? <ArrowLink to={`/trace?target=${encodeURIComponent(recodedFlightId)}`}>Example: {recodedFlight}</ArrowLink> : null}
                <ArrowLink to="/close">Liability & Close</ArrowLink>
              </span>
            </div>
          ) : undefined
        }
      >
        {cfo ? (
          <>
            EU261 compensation liability across applicable flights, based on the share of passengers <Explain term="claim-rate">expected to claim</Explain>. Pending approval.
          </>
        ) : null}
      </Tile>

      <Tile label="Payout drafts" figure={count(c.drafted)} details={<p className="text-[12.5px] leading-relaxed text-slate-500">StormCheck drafts the payouts and the journal entries; it never releases a payment run. Whoever drafts an entry can&rsquo;t approve it (<Explain term="preparer-approver">preparer ≠ approver</Explain>).</p>}>
        Ready for the Claims Lead to review. No payments are sent.
        <span className="mt-2 flex items-center gap-2 text-[12.5px] text-slate-500">
          <RoleAvatar role="claims_lead" size="sm" decorative /> Human approval required
        </span>
      </Tile>

      <Tile
        label="All flights · day-one liability"
        figure={<Money cents={run.liability_drafted_cents} />}
        details={
          <div className="flex flex-col gap-2 text-[12.5px] leading-relaxed text-slate-500">
            {cfo?.held_for_legal_cents ? (
              <p>
                <Money cents={cfo.drafted_liability_cents} className="text-navy-900" /> drafted, plus <Money cents={cfo.held_for_legal_cents} className="text-held-ink" /> <Explain term="held-for-legal">held for Legal</Explain>, accrued under the IFRS 15.56 constraint.
              </p>
            ) : null}
            <ArrowLink to="/close">2140 rollforward</ArrowLink>
          </div>
        }
      >
        Includes cases still awaiting a ruling. Weather flights: no compensation; refunds and <Explain term="care">care</Explain> still due.
      </Tile>
    </div>
  );
}

/** Plain tags for the four steps (FINAL_IDEA's workshop words, said the way an airline would). */
const LEARN_LABEL = ["history", "evidence", "human review", "reuse"] as const;

/** Learns → Runs → Escalates → Improves ↻, four small cards in a row (THREAD_JUSTIN J1, plan §6). One sentence each. */
export function LearnsStrip({ run }: { run: StormRun }) {
  const roles = [...new Set(run.questions.map((q) => q.routed_to))] as Role[];
  const cards: { label: (typeof LEARN_LABEL)[number]; title: string; body: ReactNode; highlight?: boolean }[] = [
    {
      label: "history",
      title: "Learn airline policy",
      body: (
        <>
          Use past claims and approved rulings.{" "}
          <Link to="/policies" className="font-medium text-metar-ink hover:underline">
            View policies
          </Link>
        </>
      ),
    },
    {
      label: "evidence",
      title: "Check each flight",
      body: <>Compare records, determine the cause, and calculate compensation.</>,
    },
    {
      label: "human review",
      title: "Ask when unclear",
      highlight: true,
      body: (
        <>
          <span className="mb-2 flex -space-x-1.5">
            {roles.map((r) => (
              <RoleAvatar key={r} role={r} size="sm" className="ring-2 ring-white" />
            ))}
          </span>
          Conflicting evidence goes to the person authorised to decide.
        </>
      ),
    },
    {
      label: "reuse",
      title: "Apply the ruling",
      body: (
        <>
          Reuse the approved rule where it applies. New situations still need review.
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
            <span className={cn("text-[11.5px]", card.highlight ? "text-held-ink" : "text-slate-400")}>{card.label}</span>
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

const REASON_TERM: Partial<Record<Question["reason_tag"], Term>> = { "sources-disagree": "sources-disagree", "no-precedent": "no-precedent" };

/** What needs a ruling, who can give it and what is held. */
export function QuestionsPreview({ questions }: { questions: Question[] }) {
  if (!questions.length) return <Empty title="Nothing to ask">Every decision was clear enough to draft.</Empty>;
  return (
    <ul className="flex flex-col divide-y divide-cloud-100">
      {questions.map((q) => {
        const reason = q.asked_again ? "asked again · outside your rule's scope" : q.reason_tag.replace(/-/g, " ");
        const term = q.asked_again ? "rule-scope" : REASON_TERM[q.reason_tag];
        return (
          <li key={q.id} className="py-3.5 first:pt-0 last:pb-0">
            <Link to="/questions" className="text-[14.5px] font-medium leading-snug text-navy-900 hover:underline">
              {plainIds(q.title)}
            </Link>
            <div className="mt-1.5 flex flex-wrap items-center gap-x-3 gap-y-1">
              <RoutedTo role={q.routed_to} holdsCents={q.holds_cents} />
              <span className="text-[12.5px] text-slate-500">
                {q.case_refs.length > 1 ? `${count(q.case_refs.length)} flights · ` : ""}
                {term ? <Explain term={term}>{reason}</Explain> : reason}
              </span>
            </div>
          </li>
        );
      })}
    </ul>
  );
}

/** The latest few things it did. Everything, every storm, is on Trace. */
export function FeedPanel({ events }: { events: TraceEvent[] }) {
  return (
    <Panel title="Recent decisions" actions={<ArrowLink to="/trace">Audit trail</ArrowLink>} padded={false}>
      <ol className="px-5 pb-2" aria-live="polite">
        {events.slice(0, 4).map((e) => (
          <FeedRow key={e.seq} event={e} className="border-t border-cloud-100 first:border-t-0" />
        ))}
      </ol>
      {events.length ? null : <p className="px-5 pb-5 text-[13px] text-slate-500">No activity yet.</p>}
    </Panel>
  );
}

