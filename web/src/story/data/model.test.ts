import { beforeAll, describe, expect, it } from "vitest";
import type { Blame, CfoMetrics, FlightFile, Question, Rule, StormRun } from "@/api/types";
import { createMockFetch } from "@/mocks";
import { amosTime, boardRows, chainFromBlame, chainFromFile, focusRow, mainWindow, money, nearestObs, routeEnds, ruleFrom, sentences, techLog, voucherQuestion } from "./model";

// The story's derivations, run against the mock world (typed from CONTRACTS.md): what the page shows
// must be exactly what the API says, picked and shaped, never typed in.
const mockFetch = createMockFetch({ latencyMs: [0, 0] });
const get = async <T,>(path: string): Promise<T> => (await (await mockFetch(path, { method: "GET", headers: { Accept: "application/json" } })).json()) as T;

let run: StormRun;
let file: FlightFile;
let cfo: CfoMetrics;
let questions: Question[];
let rules: Rule[];
let blame: Blame;

beforeAll(async () => {
  run = await get<StormRun>("/storms/EIDW%402025-01-24");
  file = await get<FlightFile>("/flights/NS31%402025-01-24");
  cfo = await get<CfoMetrics>("/books/cfo");
  questions = await get<Question[]>("/questions?status=all");
  rules = await get<Rule[]>("/rules");
  const je = file.journal_preview.find((j) => j.kind === "compensation_estimate");
  blame = await get<Blame>(`/blame?target=${je?.id}`);
});

describe("story model on Storm Éowyn", () => {
  it("finds NS31 as the recoded flight, outside the main window", () => {
    const focus = focusRow(run);
    expect(focus?.flight.number).toBe("NS31");
    expect(focus?.decision?.recode_label).toBe("71 → 41");
    const win = mainWindow(run.windows);
    expect(win && Date.parse(win.end)).toBeLessThan(Date.parse(focus!.flight.sched_dep));
  });

  it("splits the board into departures and arrivals as OCC coded them, and the re-check's verdicts", () => {
    const { departures, arrivals } = boardRows(run);
    expect(departures.length + arrivals.length).toBe(run.counters.cancelled);
    const ns31 = departures.find((r) => r.number === "NS31");
    expect(ns31).toMatchObject({ coded: "71", verdict: "notweather", after: "41", iata: "BOS", time: "16:30" });
    expect(departures.at(-1)?.number).toBe("NS31"); // the last departure, after the window
    expect(arrivals.filter((r) => r.verdict === "held").map((r) => r.routedTo)).toEqual(["legal", "legal", "legal"]);
    expect(arrivals.some((r) => r.coded === "72")).toBe(true);
  });

  it("reads the tech log verbatim: time, ATA chapter and its sentences", () => {
    const log = techLog(file, run);
    expect(log?.at?.toISOString()).toBe("2025-01-23T21:40:00.000Z");
    expect(log?.ata).toBe("29-13");
    expect(log?.lines[0]).toBe("23JAN 21:40Z EI-NSB DUB N/S.");
    expect(log?.lines).toContain("GND RUN: ECAM HYD Y ENG 2 PUMP LO PR.");
    expect(log?.lines.at(-1)).toBe("A/C AOG.");
    expect(amosTime("23JAN 21:40Z EI-NSB", 2025)?.toISOString()).toBe("2025-01-23T21:40:00.000Z");
    expect(sentences("A. B C. 2 D.")).toEqual(["A.", "B C.", "2 D."]);
  });

  it("takes the euros from the Flight File and the CFO view", () => {
    const m = money(file, cfo);
    expect(m).toMatchObject({ full: 9_900_000, drafted: 3_465_000, cash: 0, sensitivity: 495_000, claimRate: 0.35, payouts: 172, band: 600, distanceKm: 4804, reduced: 14 });
    expect(m.statusLine).toBe("172 payouts drafted, pending Claims Lead approval");
    expect(m.je?.lines.map((l) => l.account)).toEqual(["4090", "2140"]);
  });

  it("quotes the METAR the airport issued nearest a time", () => {
    expect(nearestObs(run.metar, "2025-01-24T12:00:00Z")?.raw).toMatch(/^EIDW 241200Z 25027G56KT/);
    expect(nearestObs(run.metar, "2025-01-24T16:30:00Z")?.raw).toMatch(/^EIDW 241630Z/);
  });

  it("draws a route for every far end of a cancellation", () => {
    const ends = routeEnds(run).map((e) => e.iata);
    expect(ends).toEqual(expect.arrayContaining(["BOS", "JFK", "ORD", "YYZ", "LHR", "ATH"]));
    expect(new Set(ends).size).toBe(ends.length);
  });

  it("traces the drafted euros back to METAR, from /blame or from the Flight File", () => {
    const fromBlame = chainFromBlame(blame);
    expect(fromBlame[0].tone).toBe("money");
    expect(fromBlame.at(-1)?.tone).toBe("metar");
    expect(new Set(fromBlame.map((s) => s.key)).size).toBe(fromBlame.length);

    const fromFile = chainFromFile(file, rules, money(file, cfo));
    expect(fromFile.map((s) => s.tone).slice(0, 3)).toEqual(["money", "money", "rule"]);
    expect(fromFile.find((s) => s.struck)?.quote).toContain("RSN 71");
    expect(fromFile.filter((s) => s.meta.startsWith("tech_log")).length).toBe(1); // one step per log, its full line
    expect(fromFile.some((s) => /spares/.test(s.meta))).toBe(false); // spares don't bear on a technical fault
  });

  it("asks the Claims Lead about the voucher, and finds no rule before the ruling", () => {
    const q1 = voucherQuestion(questions);
    expect(q1?.routed_to).toBe("claims_lead");
    expect(q1?.reason_tag).toBe("sources-disagree");
    expect(ruleFrom(rules, q1)).toBeNull();
  });
});
