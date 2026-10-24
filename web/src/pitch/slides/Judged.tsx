import { count } from "@/lib/format";
import { REAL_CARD } from "../copy";
import { payoutsDrafted, type PitchData } from "../data";
import { Bullets, Fig, GrammarCards, Reveal, SlideFrame, type GrammarCard } from "../ui";
import { StormStrip } from "./StormStrip";

/**
 * THREAD_JUSTIN J11 slide 2: the airline against the four questions (the tags are the judges' own words).
 * Wow gets a bright outline, not a meaning colour.
 */
export function Judged({ data }: { data: PitchData }) {
  const { run } = data;
  const cards: GrammarCard[] = [
    {
      title: "Real.",
      tag: "real-enough",
      lead: <>{REAL_CARD}.</>,
      details: <Bullets items={["A 5 a.m. cancel list, all coded weather", "Answer key: every passenger checked"]} />,
    },
    {
      title: "Hireable.",
      tag: "would-you-hire-it",
      lead: <>One role: disruption liability. Drafts it, never pays it.</>,
      details: <Bullets items={["Each question goes to the person who owns it", "Every euro traces to a log line"]} />,
    },
    {
      title: "New.",
      tag: "something-new",
      lead: <>Works out what each cancellation costs from what really caused it.</>,
      details: <Bullets items={["Storm window checked at both ends of a flight", "Rules that differ route to route"]} />,
    },
    {
      title: "Wow.",
      tag: "wow-moment",
      highlight: "bright",
      lead: <>Catches a &ldquo;weather&rdquo; cancellation that was a broken plane.</>,
      details: (
        <div className="flex flex-col gap-5">
          {/* "Shows the weather and the tech log", drawn rather than said. */}
          <StormStrip run={run} />
          <Bullets
            items={[
              <>
                <Fig value={run ? count(payoutsDrafted(run)) : null} className="text-cloud-50" /> payouts drafted, pending Claims Lead approval
              </>,
            ]}
          />
        </div>
      ),
    },
  ];

  return (
    <SlideFrame eyebrow="judged">
      <Reveal className="mt-10">
        <h2 className="display text-[108px] text-cloud-50">The airline, judged.</h2>
      </Reveal>
      <Reveal className="mt-6">
        <p className="text-[32px] leading-tight text-cloud-200">Its storm night, against the four questions.</p>
      </Reveal>
      <GrammarCards className="mt-auto pt-10" cards={cards} />
    </SlideFrame>
  );
}
