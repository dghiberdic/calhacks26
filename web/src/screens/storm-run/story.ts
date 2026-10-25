import type { Cause, FlightRow, Role, StormRun } from "@/api/types";
import { isOutage, mainWindowOf } from "@/components/storm/model";
import { verdictOf, type VerdictKind } from "@/components/verdict";
import { count, theSeat } from "@/lib/format";

/** One clause of the opening sentence: "23 were weather", "1 was a broken plane: NS31", "3 wait on Legal". */
export type StoryPart = { kind: VerdictKind; n: number; text: string; flightId?: string };

export type Story = {
  /** The main window is a grid outage (an external event), not a storm. */
  outage: boolean;
  cancelled: number;
  passengers: number | undefined;
  parts: StoryPart[];
};

const CAUSE_PHRASE: Partial<Record<Cause, string>> = {
  technical: "an aircraft fault",
  crew: "crew out of duty hours",
  atc: "air traffic control",
};

const was = (n: number) => (n === 1 ? "was" : "were");

/** The one role every row waits on, when they share one. */
function sharedSeat(rows: FlightRow[]): Role | null {
  const seats = new Set(rows.map((r) => r.decision?.routed_to).filter(Boolean));
  return seats.size === 1 ? ([...seats][0] as Role) : null;
}

/**
 * What the opening sentence says, from the run itself: how many were cancelled, and what each turned out to
 * be. Counts come from the flights' own verdicts, the same ones that colour the timeline.
 */
export function stormStory(run: StormRun): Story {
  const outage = isOutage(mainWindowOf(run.windows));
  const cancelled = run.flights.filter((r) => r.flight.status !== "operated");
  const by = (k: VerdictKind) => cancelled.filter((r) => verdictOf(r) === k);
  const parts: StoryPart[] = [];

  const weather = by("weather");
  if (weather.length) parts.push({ kind: "weather", n: weather.length, text: `${count(weather.length)} ${was(weather.length)} ${outage ? "the power cut" : "weather"}` });

  const owed = by("notweather");
  if (owed.length === 1) {
    const [row] = owed;
    const what = CAUSE_PHRASE[row.decision?.cause ?? "unknown"] ?? `not ${outage ? "the power cut" : "weather"}`;
    parts.push({ kind: "notweather", n: 1, text: `1 was ${what}: ${row.flight.number}`, flightId: row.flight.id });
  } else if (owed.length > 1) {
    parts.push({ kind: "notweather", n: owed.length, text: `${count(owed.length)} weren't ${outage ? "the power cut" : "weather"}, so compensation is owed` });
  }

  const held = by("held");
  if (held.length) {
    const seat = sharedSeat(held);
    parts.push({ kind: "held", n: held.length, text: `${count(held.length)} ${held.length === 1 ? "waits" : "wait"} on ${seat ? theSeat(seat) : "a ruling"}` });
  }

  const pending = by("pending");
  if (pending.length) parts.push({ kind: "pending", n: pending.length, text: `${count(pending.length)} ${pending.length === 1 ? "is" : "are"} still being checked` });

  return { outage, cancelled: run.counters?.cancelled ?? cancelled.length, passengers: run.counters?.passengers, parts };
}
