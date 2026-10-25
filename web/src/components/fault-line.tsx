import type { FlightDecision } from "@/api/types";
import { zuluDay } from "@/lib/format";
import { Explain } from "./explain";

/**
 * "The plane was grounded by a fault in its tech log at 23 Jan 21:40Z, before the storm began, with no MEL
 * relief: it wasn't allowed to fly." Built from the decision's evidence; the engine's reason when it has none.
 */
export function FaultLine({ decision }: { decision: Pick<FlightDecision, "evidence" | "confidence" | "reason"> }) {
  const logged = decision.evidence.find((e) => e.field === "aog.logged_at")?.value;
  if (typeof logged !== "string") return <>{decision.reason}</>;
  const noMel = decision.evidence.some((e) => e.field === "aog.mel_relief" && e.value === false);
  const before = (decision.confidence.features ?? {}).aog_before_window === 1;
  return (
    <>
      The plane was grounded by a fault in its <Explain term="tech-log">tech log</Explain> at {zuluDay(logged)}
      {before ? ", before the storm began" : ""}
      {noMel ? (
        <>
          , with <Explain term="no-mel-relief">no MEL relief</Explain>: it wasn&rsquo;t allowed to fly
        </>
      ) : null}
      .
    </>
  );
}
