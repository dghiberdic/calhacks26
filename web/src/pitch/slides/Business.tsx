import type { LearnedItem, Question } from "@/api/types";
import { count, eur, pct, ROLE_INITIALS, routedTo } from "@/lib/format";
import { citedNextStorm, passengers, voucherQuestion, type PitchData } from "../data";
import { Bullets, Chip, Fig, GrammarCards, Initials, LoopLine, Num, Reveal, SlideFrame, type GrammarCard } from "../ui";

/** THREAD_JUSTIN J11 slide 1, Hyphenate's `example · the-business` in our colours. Escalates is the highlight. */
export function Business({ data }: { data: PitchData }) {
  const { run, next } = data;
  const q = voucherQuestion(run);
  const cited = citedNextStorm(next);
  const pax = run ? count(passengers(run)) : null;

  const cards: GrammarCard[] = [
    {
      title: "Learns.",
      tag: "self-learning",
      lead: <>Reads the airline&rsquo;s own ops logs, claims and payouts to learn who&rsquo;s owed what.</>,
      details: <Learned items={run?.learned} />,
    },
    {
      title: "Runs.",
      tag: "ai-automated",
      lead: <>The morning after a storm, it sets each flight&rsquo;s real cause and drafts every refund, payout and the liability.</>,
      details: (
        <Bullets
          items={[
            <>
              <Fig value={pax} className="text-cloud-50" /> passengers sorted overnight
            </>,
            "Liability draft ready for the Controller",
          ]}
        />
      ),
    },
    {
      title: "Escalates.",
      tag: "needs-review",
      highlight: "held",
      lead: <>CRM says a passenger took a service-desk voucher instead of cash. Her claim says she never agreed.</>,
      details: <Escalation q={q} loading={!run} />,
    },
    {
      title: "Improves.",
      tag: "new-policy",
      lead: <>Claims Lead: &ldquo;No signed acceptance, no offset.&rdquo;</>,
      details: <Bullets items={["Saved as policy for every flight leaving the EU", "Never asked again"]} />,
    },
  ];

  return (
    <SlideFrame
      eyebrow="example · the-business"
      footer={
        <LoopLine>
          Next storm:{" "}
          {cited ? (
            <>
              <Fig value={count(cited)} className="text-cloud-50" /> voucher cases settled, ruling cited.
            </>
          ) : (
            <>cases like hers settle on their own, ruling cited.</>
          )}
        </LoopLine>
      }
    >
      <Reveal className="mt-10">
        <h2 className="display text-[108px] text-cloud-50">An airline.</h2>
      </Reveal>
      <Reveal className="mt-6 flex flex-wrap items-center gap-x-8 gap-y-4">
        <p className="text-[32px] leading-tight text-cloud-200">The job: settle what every passenger is owed after each storm.</p>
        <span className="flex gap-3">
          <Chip size="sm">
            <Num>€1.1B</Num>&nbsp;Irish carrier
          </Chip>
          <Chip size="sm">
            <Fig value={pax} />
            &nbsp;passengers, one storm
          </Chip>
        </span>
      </Reveal>
      <GrammarCards className="mt-auto pt-10" cards={cards} />
    </SlideFrame>
  );
}

/** What it learned at onboarding, as the API reports it ("Takes the 50% reroute cut (41 of 42)"). */
function Learned({ items }: { items: LearnedItem[] | undefined }) {
  if (items === undefined) {
    return (
      <div className="flex flex-col gap-3">
        <Fig value={null} width="90%" className="h-[22px]" />
        <Fig value={null} width="70%" className="h-[22px]" />
      </div>
    );
  }
  return (
    <Bullets
      items={items.slice(0, 3).map((l) => (
        <>
          {l.text}
          {/* short supports ("41 of 42") stay on one line; long ones wrap like prose */}
          {l.support ? <span className={l.support.length <= 16 ? "whitespace-nowrap text-cloud-500" : "text-cloud-500"}>{` (${l.support})`}</span> : null}
        </>
      ))}
    />
  );
}

/** Routed to the Claims Lead · `confidence 39% · sources disagree` · Holds that one €600 (all from the question). */
function Escalation({ q, loading }: { q: Question | undefined; loading: boolean }) {
  if (!q) {
    return loading ? (
      <div className="flex flex-col gap-4">
        <Fig value={null} width="80%" className="h-[44px]" />
        <Fig value={null} width="95%" className="h-[36px]" />
      </div>
    ) : null;
  }
  const score = q.confidence.score === null ? "uncalibrated" : pct(q.confidence.score);
  return (
    <div className="flex flex-col items-start gap-[18px]">
      <p className="flex items-center gap-3.5 text-[21px] text-cloud-100">
        <Initials className="bg-held text-navy-950">{ROLE_INITIALS[q.routed_to]}</Initials>
        {routedTo(q.routed_to)}
      </p>
      <Chip size="sm" tone="held" wrap className="px-3 text-[15px]">
        confidence {score} · {q.reason_tag.replace(/-/g, " ")}
      </Chip>
      {q.holds_cents ? (
        <Bullets
          items={[
            <>
              Holds {(q.holds?.length ?? 0) > 1 ? "" : "that one "}
              <Num className="text-cloud-50">{eur(q.holds_cents)}</Num>
            </>,
          ]}
        />
      ) : null}
    </div>
  );
}
