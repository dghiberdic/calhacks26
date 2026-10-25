import { count } from "@/lib/format";
import { payoutsDrafted, recodedRow, type PitchData } from "../data";
import { Bullets, Fig, GrammarCards, Reveal, SlideFrame, type GrammarCard } from "../ui";
import { StormStrip } from "./StormStrip";

/**
 * One concrete case: reported cause → source evidence → corrected result → human approval.
 */
export function Judged({ data }: { data: PitchData }) {
  const { run } = data;
  const row = recodedRow(run);
  const cards: GrammarCard[] = [
    {
      title: "Reported.",
      tag: "01 · the problem",
      lead: <>{row?.flight.number ?? "The flight"} was marked as a weather cancellation.</>,
      details: <Bullets items={["That label can exclude compensation", "Refunds and care are still due"]} />,
    },
    {
      title: "Evidence.",
      tag: "02 · the check",
      lead: <>The aircraft was grounded before the storm.</>,
      details: <StormStrip run={run} />,
    },
    {
      title: "Corrected.",
      tag: "03 · the result",
      highlight: "bright",
      lead: <>A technical fault: compensation is owed.</>,
      details: <Bullets items={[
        <>Code corrected: {row?.decision?.recode_label ?? "awaiting evidence"}</>,
        "Passenger entitlements recalculated",
      ]} />,
    },
    {
      title: "Review.",
      tag: "04 · the control",
      lead: <>The Claims Lead approves payouts. The system cannot pay.</>,
      details: (
        <div className="flex flex-col gap-5">
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
    <SlideFrame eyebrow="a case from the demo">
      <Reveal className="mt-10">
        <h2 className="display text-[100px] text-cloud-50">Same storm. Different cause.</h2>
      </Reveal>
      <Reveal className="mt-6">
        <p className="text-[32px] leading-tight text-cloud-200">A cancellation code is a starting point, not proof.</p>
      </Reveal>
      <GrammarCards className="mt-auto pt-10" cards={cards} />
    </SlideFrame>
  );
}
