import { describe, expect, it } from "vitest";
import type { FlightDecision, FlightRow, StormRun } from "@/api/types";
import { stormStory } from "./story";

const flight = (number: string, status: "cancelled" | "operated" = "cancelled") => ({ id: `${number}@2025-01-24`, number, date: "2025-01-24", origin: "DUB", dest: "LHR", sched_dep: "2025-01-24T06:00:00Z", sched_arr: "2025-01-24T07:00:00Z", status, pax: 100 }) as FlightRow["flight"];
const decision = (d: Partial<FlightDecision>) => ({ cause: "weather", extraordinary: "extraordinary", outcome: "auto", routed_to: null, confidence: { score: 0.99, kind: "cause", label: "cause-finding confidence", features: {} }, evidence: [], ...d }) as FlightDecision;
const run = (rows: FlightRow[], windows: StormRun["windows"] = [{ station: "EIDW", start: "2025-01-24T02:30:00Z", end: "2025-01-24T15:00:00Z", peak_gust_kt: 56 }]) =>
  ({ id: "EIDW@2025-01-24", station: "EIDW", date: "2025-01-24", windows, metar: [], flights: rows, counters: { cancelled: rows.filter((r) => r.flight.status !== "operated").length, passengers: 5292 }, questions: [], learned: [], feed: [] }) as unknown as StormRun;

describe("stormStory", () => {
  it("says what each cancellation turned out to be, from the verdicts", () => {
    const rows: FlightRow[] = [
      { flight: flight("NS100"), decision: decision({}) },
      { flight: flight("NS102"), decision: decision({}) },
      { flight: flight("NS31"), decision: decision({ cause: "technical", extraordinary: "not_extraordinary", recoded: true }) },
      { flight: flight("NS113"), decision: decision({ cause: "knock_on", extraordinary: "needs_legal", outcome: "escalated", routed_to: "legal" }) },
      { flight: flight("NS200", "operated"), decision: null },
    ];
    const s = stormStory(run(rows));
    expect(s.outage).toBe(false);
    expect(s.cancelled).toBe(4);
    expect(s.parts.map((p) => p.text)).toEqual(["2 were weather", "1 was a broken plane: NS31", "1 waits on Legal"]);
  });

  it("says power cut, not weather, for a grid outage", () => {
    const rows: FlightRow[] = [
      { flight: flight("NS500"), decision: decision({ cause: "external_event" }) },
      { flight: flight("NS502"), decision: decision({ cause: "crew", extraordinary: "not_extraordinary" }) },
    ];
    const s = stormStory(run(rows, [{ station: "LPPT", start: "2025-04-28T10:33:00Z", end: "2025-04-28T22:00:00Z", peak_gust_kt: 0, kind: "grid_outage", label: "Grid outage (Iberian blackout)" }]));
    expect(s.outage).toBe(true);
    expect(s.parts.map((p) => p.text)).toEqual(["1 was the power cut", "1 was crew out of duty hours: NS502"]);
  });
});
