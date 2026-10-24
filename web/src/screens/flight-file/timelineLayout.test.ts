import { describe, expect, it } from "vitest";
import type { Flight, TimelineMark } from "@/api/types";
import { placeLabels, toItems, type Placed } from "./timelineLayout";

const NS31: Flight = {
  id: "NS31@2025-01-24",
  number: "NS31",
  date: "2025-01-24",
  origin: "DUB",
  dest: "BOS",
  sched_dep: "2025-01-24T16:30:00Z",
  sched_arr: "2025-01-24T23:45:00Z",
  aircraft: "EI-NSB",
  status: "cancelled",
  pax: 172,
};

/** NS31's timeline as the mock world sends it: 16 marks, clustered around the fault, the OCC list and the STD. */
const MARKS: TimelineMark[] = [
  ["2025-01-23T21:40:00Z", "tech_log", "AOG · no MEL relief"],
  ["2025-01-23T22:15:00Z", "mcc", "No EDP in DUB stores · pool unit ETA 25 Jan 14:00Z"],
  ["2025-01-23T23:30:00Z", "window", "minor window 23:30–00:30Z"],
  ["2025-01-24T02:30:00Z", "window", "storm window opens 02:30Z"],
  ["2025-01-24T05:12:00Z", "occ", "OCC cancel list · all 27 coded 71/72"],
  ["2025-01-24T05:40:00Z", "spares", "No long-range tail at DUB"],
  ["2025-01-24T06:02:00Z", "crm", "CRM bot · first of 32 refunds initiated"],
  ["2025-01-24T07:00:00Z", "metar", "peak gust 56 kt"],
  ["2025-01-24T09:40:00Z", "crm", "CRM bot · 32nd refund"],
  ["2025-01-24T12:00:00Z", "metar", "gust 56 kt again"],
  ["2025-01-24T14:52:00Z", "crm", "T2 service desk · €300 voucher in lieu to 14C (unsigned)"],
  ["2025-01-24T15:00:00Z", "window", "storm window closes 15:00Z"],
  ["2025-01-24T15:30:00Z", "operated", "11 Northstar departures operate 15:30–17:30Z"],
  ["2025-01-24T16:00:00Z", "metar", "16:00Z · 11 kt · gusts ≤25 kt from here"],
  ["2025-01-24T16:30:00Z", "schedule", "NS31 STD 16:30Z · 90 min after the window"],
].map(([at, kind, label]) => ({ at, kind, label }));

function layout(width: number) {
  const items = toItems(MARKS, NS31, "DUB").filter((i) => i.key !== "window");
  const t0 = items[0].at;
  const t1 = items[items.length - 1].at;
  const x = (t: number) => 14 + ((t - t0) / (t1 - t0)) * (width - 28);
  return placeLabels(
    items.map((it) => ({ ...it, cx: x(it.at), cy: 0 })),
    width,
    "2025-01-24",
  );
}

const overlaps = (a: Placed, b: Placed) => a.left < b.left + b.w && b.left < a.left + a.w;

describe("flight timeline label layout", () => {
  for (const width of [545, 700, 1000]) {
    it(`never overlaps two labels or crosses a label with a leader (${width}px)`, () => {
      const { placed } = layout(width);
      for (const a of placed) {
        expect(a.left).toBeGreaterThanOrEqual(0);
        expect(a.left + a.w).toBeLessThanOrEqual(width);
        for (const b of placed) {
          if (a === b) continue;
          if (a.lane === b.lane) expect(overlaps(a, b)).toBe(false);
          // b's leader runs down from b's lane through every lane below it.
          if (b.lane > a.lane) expect(b.cx > a.left && b.cx < a.left + a.w).toBe(false);
        }
      }
    });
  }

  it("labels the flight, the tech log and the OCC code first; the rest keep a tick", () => {
    const { placed, unplaced } = layout(545);
    const labelled = new Set(placed.map((p) => p.it.key));
    for (const key of ["schedule", "tech", "occ"] as const) expect(labelled.has(key)).toBe(true);
    expect(placed.length + unplaced.length).toBe(12);
  });

  it("adds the flight's own STD at the hub when the timeline doesn't carry it", () => {
    const items = toItems([{ at: "2025-01-24T05:12:00Z", kind: "occ", label: "OCC cancel list" }], NS31, "DUB");
    expect(items.map((i) => i.label)).toEqual(["OCC cancel list", "NS31 STD"]);
  });
});
