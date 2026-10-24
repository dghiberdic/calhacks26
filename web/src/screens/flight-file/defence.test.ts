import { describe, expect, it } from "vitest";
import type { FlightFile, StormRun } from "@/api/types";
import { createMockFetch } from "@/mocks";
import { weatherDefence } from "./defence";

const api = createMockFetch();
const get = async <T>(path: string) => (await (await api(path, { method: "GET" })).json()) as T;

describe("weather defence (Art. 5(3)), from the file's own evidence", () => {
  it("argues NS108 on its own weather, and says what is against it", async () => {
    const run = await get<StormRun>("/storms/EIDW%402025-01-24");
    const file = await get<FlightFile>(`/flights/${encodeURIComponent("NS108@2025-01-24")}`);
    const d = weatherDefence(file, "DUB", run.windows, run.real_context)!;
    expect(d).not.toBeNull();
    expect(d.end).toBe("dep");
    expect(d.station).toBe("DUB");
    // The window is the computed one that contains STD, and its close is the "why not wait?" answer.
    expect(Date.parse(d.window!.start)).toBeLessThanOrEqual(Date.parse(d.at));
    expect(Date.parse(d.window!.end)).toBeGreaterThanOrEqual(Date.parse(d.at));
    expect(d.minutesToClose).toBe(Math.round((Date.parse(d.window!.end) - Date.parse(d.at)) / 60_000));
    expect(d.metar).toMatch(/^EIDW \d{6}Z/);
    // The airport never closed: the claimant can find that too, so the panel says it.
    expect(d.departures).toMatch(/departures \(Eurocontrol\)/);
    // The server's own line when it sends one (the golden world does); the panel falls back to the same words.
    if (d.stillOwed !== null) expect(d.stillOwed).toMatch(/refunds and care/i);
  });

  it("has nothing to defend on a technical fault or a held knock-on", async () => {
    const run = await get<StormRun>("/storms/EIDW%402025-01-24");
    for (const id of ["NS31@2025-01-24", "NS117@2025-01-24"]) {
      const file = await get<FlightFile>(`/flights/${encodeURIComponent(id)}`);
      expect(weatherDefence(file, "DUB", run.windows, run.real_context)).toBeNull();
    }
  });
});
