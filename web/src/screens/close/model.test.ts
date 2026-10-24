import { describe, expect, it } from "vitest";
import type { Commit, JournalEntry, MonthEndResponse, Rollforward, RollforwardRow, TraceEvent } from "@/api/types";
import { bridgeScale, cohortParts, footRow, journalTies, liabilityChange, lockedPeriods, monthBounds, movementCents, preparerRole, rollforwardCsv, rollforwardTotals } from "./model";

const row = (over: Partial<RollforwardRow> = {}): RollforwardRow => ({
  cohort: "EIDW@2025-01-24",
  opening_cents: 3_105_000,
  new_cents: 0,
  claims_approved_cents: 930_000,
  settled_in_kind_cents: 0,
  change_in_estimate_cents: 399_000,
  recode_cents: 0,
  out_of_period_cents: 0,
  derecognised_cents: 0,
  closing_cents: 2_574_000,
  unclaimed_entitlement_cents: 8_610_000,
  ...over,
});

describe("rollforward movements", () => {
  it("shows reductions as negatives whichever sign the API stores them with", () => {
    expect(movementCents(row(), "claims_approved_cents")).toBe(-930_000);
    expect(movementCents(row({ claims_approved_cents: -930_000 }), "claims_approved_cents")).toBe(-930_000);
    expect(movementCents(row({ derecognised_cents: 360_000 }), "derecognised_cents")).toBe(-360_000);
  });
  it("keeps the sign of movements that can go either way", () => {
    expect(movementCents(row(), "change_in_estimate_cents")).toBe(399_000);
    expect(movementCents(row({ change_in_estimate_cents: -4_749_600 }), "change_in_estimate_cents")).toBe(-4_749_600);
  });
  it("foots the golden February line: 31,050 − 9,300 + 3,990 = 25,740", () => {
    expect(footRow(row())).toEqual({ foots: true, computed: 2_574_000, difference: 0 });
    expect(footRow(row({ claims_approved_cents: -930_000 })).foots).toBe(true);
  });
  it("says by how much a line doesn't foot", () => {
    expect(footRow(row({ closing_cents: 2_575_000 }))).toEqual({ foots: false, computed: 2_574_000, difference: 1_000 });
  });
  it("totals every movement and cross-foots against the closing total", () => {
    const isha = row({ cohort: "EIDW@2024-01-21", opening_cents: 360_000, claims_approved_cents: 0, change_in_estimate_cents: 0, closing_cents: 360_000, unclaimed_entitlement_cents: 4_260_000 });
    const rf: Rollforward = { period: "2025-02", rows: [row(), isha], closing_total_cents: 2_934_000, gl_balance_cents: 2_934_000, ties_to_gl: true };
    const t = rollforwardTotals(rf);
    expect(t.opening).toBe(3_465_000);
    expect(t.movements.claims_approved_cents).toBe(-930_000);
    expect(t.movements.change_in_estimate_cents).toBe(399_000);
    expect(t.closing).toBe(2_934_000);
    expect(t.unclaimed).toBe(12_870_000);
    expect(t.everyRowFoots).toBe(true);
    expect(t.crossFoots).toBe(true);
    expect(rollforwardTotals({ ...rf, closing_total_cents: 2_900_000 }).crossFoots).toBe(false);
  });
});

describe("tick and tie to the journal", () => {
  const je = (id: string, kind: JournalEntry["kind"], dr2140: number, cr2140: number): JournalEntry => ({
    id,
    event_date: "2025-02-28",
    period: "2025-02",
    memo: "",
    kind,
    lines: [
      { account: "2140", account_name: "EU261 compensation liability", dr_cents: dr2140, cr_cents: cr2140 },
      { account: "4090", account_name: "EU261 compensation", dr_cents: cr2140, cr_cents: dr2140 },
    ],
    status: "draft",
    preparer: "agent.engine",
  });
  const rf: Rollforward = { period: "2025-02", rows: [row()], closing_total_cents: 2_574_000, gl_balance_cents: 2_574_000, ties_to_gl: true };

  it("agrees each movement to the journals of its kind, by their effect on 2140", () => {
    const ties = journalTies(rf, [je("JE-1", "claim_approved", 930_000, 0), je("JE-2", "change_in_estimate", 0, 399_000)]);
    expect(ties.claims_approved_cents).toEqual({ ids: ["JE-1"], cents: -930_000, agrees: true });
    expect(ties.change_in_estimate_cents).toEqual({ ids: ["JE-2"], cents: 399_000, agrees: true });
    expect(ties.new_cents).toBe(undefined);
  });
  it("doesn't claim a tie that isn't there", () => {
    const ties = journalTies(rf, [je("JE-1", "claim_approved", 900_000, 0)]);
    expect(ties.claims_approved_cents?.agrees).toBe(false);
  });
  it("ignores entries that never touch 2140", () => {
    const goodwill: JournalEntry = { ...je("JE-9", "voucher_in_lieu", 0, 0), lines: [{ account: "4090", account_name: "", dr_cents: 30_000 }, { account: "2132", account_name: "", cr_cents: 30_000 }] };
    expect(journalTies(rf, [goodwill]).settled_in_kind_cents).toBe(undefined);
  });
  it("writes the note as CSV, negatives signed, total column last", () => {
    const csv = rollforwardCsv(rf).split("\n");
    expect(csv[0]).toBe("Movement,EIDW@2025-01-24,Total");
    expect(csv[1]).toBe("Opening,31050.00,31050.00");
    expect(csv).toContain("Claims approved,-9300.00,-9300.00");
    expect(csv).toContain("Closing,25740.00,25740.00");
    expect(csv).toContain("GL 2140 balance,,25740.00");
  });
});

describe("periods", () => {
  it("knows the first and last day of a period", () => {
    expect(monthBounds("2025-02")).toEqual({ first: "2025-02-01", last: "2025-02-28" });
    expect(monthBounds("2024-02")).toEqual({ first: "2024-02-01", last: "2024-02-29" });
    expect(monthBounds("2025-01").last).toBe("2025-01-31");
  });
  it("collects locked periods from LOCKED trace events, period_lock commits and this session", () => {
    const events = [
      { seq: 1, at: "2025-02-01T00:00:00Z", kind: "info", actor: "controller", summary: "Jan 2025 locked", ref: "2025-01", chip: "LOCKED" },
      { seq: 2, at: "2025-02-01T00:00:00Z", kind: "journal", actor: "agent.engine", summary: "JE-000201 drafted for 2025-03", ref: "JE-000201", chip: "DRAFTED" },
    ] as TraceEvent[];
    const commits = [{ hash: "a", parent: null, kind: "period_lock", at: "2025-03-01T00:00:00Z", actor: "controller", payload_hash: "b", payload_ref: "period:2024-12", message: "lock" }] as Commit[];
    expect([...lockedPeriods(events, commits, ["2025-02"])].sort()).toEqual(["2024-12", "2025-01", "2025-02"]);
    expect(lockedPeriods(undefined, undefined, []).size).toBe(0);
  });
  it("reads a lock off the locked-period invariant's detail, and nothing else", () => {
    const inv = [
      { id: "INV-11", description: "Nothing written to a locked period", ok: true, detail: "2025-01 locked, untouched" },
      { id: "INV-01", description: "2140 rollforward foots and ties to GL 2140", ok: true, detail: "2025-02: closing €29,340 = GL €29,340" },
    ];
    expect([...lockedPeriods(undefined, undefined, [], inv)]).toEqual(["2025-01"]);
    expect(lockedPeriods(undefined, undefined, [], [{ id: "X", description: "Nothing written to a locked period", ok: true, detail: "no period locked yet" }]).size).toBe(0);
  });
});

describe("cohort ids", () => {
  it("reads station, date and an optional segment suffix", () => {
    expect(cohortParts("EIDW@2025-01-24")).toEqual({ base: "EIDW@2025-01-24", station: "EIDW", date: "2025-01-24", segment: null });
    expect(cohortParts("EIDW@2025-01-24:medium_1500_3500")).toEqual({ base: "EIDW@2025-01-24", station: "EIDW", date: "2025-01-24", segment: "medium_1500_3500" });
    expect(cohortParts("odd")).toEqual({ base: "odd", station: "odd", date: "", segment: null });
  });
});

describe("who prepared it", () => {
  it("maps a preparer principal to a seat", () => {
    expect(preparerRole("controller")).toBe("controller");
    expect(preparerRole("user:controller:Controller")).toBe("controller");
    expect(preparerRole("Claims Lead")).toBe("claims_lead");
    expect(preparerRole("claims-lead")).toBe("claims_lead");
    expect(preparerRole("agent.engine")).toBe("agent.engine");
    expect(preparerRole("cfo")).toBe("cfo");
    expect(preparerRole("stops")).toBe(null);
    expect(preparerRole("")).toBe(null);
  });
});

describe("month-end result", () => {
  const je = (over: Partial<JournalEntry>): JournalEntry => ({
    id: "JE-000210",
    event_date: "2025-02-28",
    period: "2025-02",
    memo: "",
    kind: "change_in_estimate",
    lines: [
      { account: "4090", account_name: "EU261 compensation", dr_cents: 399_000, cr_cents: 0 },
      { account: "2140", account_name: "EU261 compensation liability", dr_cents: 0, cr_cents: 399_000 },
    ],
    status: "draft",
    preparer: "agent.engine",
    ...over,
  });
  it("reads the change in estimate off 2140 in the drafted entries: +€3,990", () => {
    const res = { entries: [je({})], rollforward: { period: "2025-02", rows: [], closing_total_cents: 0, gl_balance_cents: 0, ties_to_gl: true } } as unknown as MonthEndResponse;
    expect(liabilityChange(res)).toBe(399_000);
  });
  it("falls back to the rollforward when no change-in-estimate entry came back", () => {
    const res = { entries: [], rollforward: { period: "2025-02", rows: [row()], closing_total_cents: 2_574_000, gl_balance_cents: 2_574_000, ties_to_gl: true } } as unknown as MonthEndResponse;
    expect(liabilityChange(res)).toBe(399_000);
  });
  it("is negative when the estimate comes down", () => {
    const down = je({ lines: [{ account: "2140", account_name: "", dr_cents: 4_749_600 }, { account: "4090", account_name: "", cr_cents: 4_749_600 }] });
    expect(liabilityChange({ entries: [down] } as unknown as MonthEndResponse)).toBe(-4_749_600);
  });
});

describe("the CFO bridge scale", () => {
  it("places cash basis, drafted ± sensitivity and the full entitlement on one axis", () => {
    const s = bridgeScale({ cash: 0, drafted: 3_465_000, full: 9_900_000, sensitivity: 495_000, range: [2_175_000, 3_726_700] });
    expect(s.max).toBe(9_900_000);
    expect(s.at(3_465_000)).toBeCloseTo(0.35, 5);
    expect(s.band).toEqual([2_970_000, 3_960_000]);
    expect(s.range).toEqual([2_175_000, 3_726_700]);
  });
  it("never lets a band fall off either end", () => {
    const s = bridgeScale({ cash: 0, drafted: 200_000, full: 1_000_000, sensitivity: 495_000, range: [3_465_000, 3_465_000] });
    expect(s.band[0]).toBe(0);
    expect(s.range).toBe(null);
    expect(s.at(-5)).toBe(0);
    expect(s.at(5_000_000)).toBe(1);
  });
});
