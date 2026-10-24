import { describe, expect, it } from "vitest";
import { AIRPORTS, airportLabel, resolveAirport, searchAirports } from "./airports";
import { addMonths, dayLabel, monthGrid, parseDate, todayIn, utcOffsetLabel } from "./dates";
import { findSpan, placeSpans, segment } from "./spans";
import { ApiError } from "@/api/client";
import type { InjectResponse, StormRun } from "@/api/types";
import { flightOf, normaliseInject, normaliseRun, problemOf } from "./state";

describe("airport search", () => {
  it("has no duplicate codes", () => {
    expect(new Set(AIRPORTS.map((a) => a.icao)).size).toBe(AIRPORTS.length);
    expect(new Set(AIRPORTS.map((a) => a.iata)).size).toBe(AIRPORTS.length);
    for (const a of AIRPORTS) {
      expect(a.iata).toMatch(/^[A-Z]{3}$/);
      expect(a.icao).toMatch(/^[A-Z]{4}$/);
    }
  });
  it("finds by IATA, ICAO and city, exact codes first", () => {
    expect(searchAirports("dub")[0].icao).toBe("EIDW");
    expect(searchAirports("EIDW")[0].iata).toBe("DUB");
    expect(searchAirports("lhr")[0].icao).toBe("EGLL");
    expect(searchAirports("london").map((a) => a.iata)).toEqual(expect.arrayContaining(["LHR", "LGW", "STN", "LCY"]));
    expect(searchAirports("new york").map((a) => a.iata).slice(0, 3)).toEqual(["JFK", "EWR", "LGA"]);
  });
  it("ignores accents and case", () => {
    expect(searchAirports("zurich")[0].icao).toBe("LSZH");
    expect(searchAirports("MALAGA")[0].icao).toBe("LEMG");
    expect(searchAirports("munchen")[0].icao).toBe("EDDM");
  });
  it("labels as IATA · ICAO · name", () => {
    expect(airportLabel(searchAirports("dub")[0])).toBe("DUB · EIDW · Dublin");
  });
  it("resolves typed text without a click, and lets an unlisted ICAO through", () => {
    expect(resolveAirport("dub")?.icao).toBe("EIDW");
    expect(resolveAirport("egll")?.icao).toBe("EGLL");
    expect(resolveAirport("DUB · EIDW · Dublin")?.icao).toBe("EIDW");
    expect(resolveAirport("Boston")?.icao).toBe("KBOS");
    expect(resolveAirport("KXYZ")).toEqual({ icao: "KXYZ" });
    // Two airports share the city: the person picks.
    expect(resolveAirport("rome")).toBeNull();
    // A four-letter city is a city, not a code.
    expect(resolveAirport("Lyon")?.icao).toBe("LFLL");
    expect(resolveAirport("")).toBeNull();
  });
});

describe("dates", () => {
  const today = "2026-10-24";
  it("reads the formats people type", () => {
    expect(parseDate("2025-01-24", today)).toBe("2025-01-24");
    expect(parseDate("24 Jan 2025", today)).toBe("2025-01-24");
    expect(parseDate("24 january 25", today)).toBe("2025-01-24");
    expect(parseDate("Jan 24, 2025", today)).toBe("2025-01-24");
    expect(parseDate("24th Jan 2025", today)).toBe("2025-01-24");
    expect(parseDate("24/01/2025", today)).toBe("2025-01-24");
    expect(parseDate("01/24/2025", today)).toBe("2025-01-24");
    expect(parseDate("26.01.2025", today)).toBe("2025-01-26");
    expect(parseDate("24JAN2025", today)).toBe("2025-01-24");
    expect(parseDate("Sept 3 2024", today)).toBe("2024-09-03");
  });
  it("resolves relative words and a missing year to the latest day that isn't ahead", () => {
    expect(parseDate("today", today)).toBe(today);
    expect(parseDate("yesterday", today)).toBe("2026-10-23");
    expect(parseDate("24 Jan", today)).toBe("2026-01-24");
    expect(parseDate("30 Dec", today)).toBe("2025-12-30");
  });
  it("rejects what isn't a date", () => {
    expect(parseDate("31 Feb 2025", today)).toBeNull();
    expect(parseDate("tomorrowish", today)).toBeNull();
    expect(parseDate("2025-13-01", today)).toBeNull();
    expect(parseDate("", today)).toBeNull();
  });
  it("still passes a future date through (the server answers for it)", () => {
    expect(parseDate("1 Jan 2030", today)).toBe("2030-01-01");
  });
  it("labels and steps calendar days without time-zone drift", () => {
    expect(dayLabel("2025-01-24")).toBe("Fri 24 Jan 2025");
    expect(addMonths("2025-01-31", 1)).toBe("2025-02-28");
    const grid = monthGrid(2025, 1);
    expect(grid[0].slice(0, 3)).toEqual([null, null, "2025-01-01"]); // 1 Jan 2025 was a Wednesday
    expect(grid.flat().filter(Boolean)).toHaveLength(31);
  });
  it("knows the airport's offset on that day and its local today", () => {
    expect(utcOffsetLabel("Europe/Dublin", "2025-01-24")).toBe("UTC+0");
    expect(utcOffsetLabel("Europe/Dublin", "2025-07-01")).toBe("UTC+1");
    expect(utcOffsetLabel("America/New_York", "2025-01-24")).toBe("UTC−5");
    expect(utcOffsetLabel("Asia/Kolkata", "2025-01-24")).toBe("UTC+5:30");
    expect(utcOffsetLabel("Not/AZone", "2025-01-24")).toBeNull();
    // 23:30 UTC on 24 Oct is already the 25th in Tokyo and still the 24th in Dublin (UTC+1).
    const at = new Date("2026-10-24T23:30:00Z");
    expect(todayIn("Asia/Tokyo", at)).toBe("2026-10-25");
    expect(todayIn("Europe/Dublin", at)).toBe("2026-10-25");
    expect(todayIn("America/Los_Angeles", at)).toBe("2026-10-24");
  });
});

describe("spans", () => {
  const tech = "23JAN 21:40Z EI-NSB DUB N/S. HYD FLUID ENG 2 LWR COWL.\nGND RUN: ECAM HYD Y ENG 2  PUMP LO PR. NO MEL RELIEF. A/C AOG.";
  it("finds a span exactly, across collapsed whitespace", () => {
    expect(findSpan(tech, "23JAN 21:40Z")).toEqual([{ start: 0, end: 12 }]);
    const [r] = findSpan(tech, "COWL. GND RUN");
    expect(tech.slice(r.start, r.end)).toBe("COWL.\nGND RUN");
    const [p] = findSpan(tech, "ENG 2 PUMP LO PR");
    expect(tech.slice(p.start, p.end)).toBe("ENG 2  PUMP LO PR");
  });
  it("falls back to any case and reports what it can't place", () => {
    expect(findSpan(tech, "no mel relief")).toHaveLength(1);
    const { unplaced, placed } = placeSpans(tech, [{ span: "NO MEL RELIEF" }, { span: "a span the Reader made up" }, { span: null }]);
    expect([...placed]).toEqual([0]);
    expect(unplaced).toEqual([1]);
  });
  it("splits overlapping spans into segments that know every fact covering them", () => {
    const text = "EXT LEAK EDP CASE DRAIN PORT";
    const segs = segment(text, [
      { key: 0, range: { start: 0, end: 12 } },
      { key: 1, range: { start: 9, end: 28 } },
    ]);
    expect(segs.map((s) => [s.text, s.keys])).toEqual([
      ["EXT LEAK ", [0]],
      ["EDP", [0, 1]],
      [" CASE DRAIN PORT", [1]],
    ]);
    expect(segs.map((s) => s.text).join("")).toBe(text);
  });
});

describe("answers at the boundary", () => {
  it("maps each 422 to the input it is about, and a lost connection to a retry", () => {
    expect(problemOf(new ApiError(422, "future_date", "That day hasn't happened yet."))).toMatchObject({ field: "date", message: "That day hasn't happened yet." });
    expect(problemOf(new ApiError(422, "no_metar", "No METAR."))).toMatchObject({ field: "date" });
    expect(problemOf(new ApiError(422, "unknown_airport", "Unknown."))).toMatchObject({ field: "airport" });
    expect(problemOf(new ApiError(0, "network", "Can't reach the StormCheck server."))).toMatchObject({ network: true });
    expect(problemOf(new Error("boom")).message).not.toMatch(/boom/);
  });
  it("fills lists the server leaves out", () => {
    const run = normaliseRun({ id: "EGLL@2024-01-21", station: "EGLL", date: "2024-01-21", entitlement_cents: 0, liability_drafted_cents: 0 } as unknown as StormRun);
    expect(run.windows).toEqual([]);
    expect(run.flights).toEqual([]);
    expect(run.counters).toEqual({});
    const res = normaliseInject({ source: { id: "s", kind: "email", title: "t", sha256: "x", received_at: "", trust_tier: 4 } } as unknown as InjectResponse, { kind: "email", text: "hi" });
    expect(res.facts).toEqual([]);
    expect(res.events).toEqual([]);
    expect(res.affected).toEqual([]);
    expect(res.dropped_unverifiable).toBe(0);
  });
  it("finds the flight in any affected id", () => {
    expect(flightOf("NS31@2025-01-24:14C")).toBe("NS31@2025-01-24");
    expect(flightOf("NS100@2025-01-24")).toBe("NS100@2025-01-24");
    expect(flightOf("EIDW@2025-01-24")).toBeNull();
    expect(flightOf("Q-6")).toBeNull();
  });
});

