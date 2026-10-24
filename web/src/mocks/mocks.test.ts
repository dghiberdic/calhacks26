import { beforeEach, describe, expect, it } from "vitest";
import type { CfoMetrics, FlightFile, Question, Rule, StormRun, StormSummary } from "@/api/types";
import { SOURCES } from "./data/world";
import { createMockFetch, resetMockWorld } from "./index";

const mockFetch = createMockFetch({ latencyMs: [0, 0] });
let token: string | null = null;

async function call<T = unknown>(method: "GET" | "POST", path: string, body?: unknown): Promise<{ status: number; json: T }> {
  const headers: Record<string, string> = { Accept: "application/json" };
  if (body !== undefined) headers["Content-Type"] = "application/json";
  if (token) headers.Authorization = `Bearer ${token}`;
  const res = await mockFetch(path, { method, headers, body: body === undefined ? undefined : JSON.stringify(body) });
  return { status: res.status, json: (await res.json()) as T };
}
const get = <T>(path: string) => call<T>("GET", path);
const post = <T>(path: string, body?: unknown) => call<T>("POST", path, body);
const enc = encodeURIComponent;

async function as(role: string) {
  const r = await post<{ token: string }>("/session", { role, name: role });
  token = r.json.token;
}

beforeEach(() => {
  resetMockWorld();
  token = null;
});

describe("storm run (Éowyn)", () => {
  it("lists both real storm days", async () => {
    const r = await get<StormSummary[]>("/storms");
    expect(r.status).toBe(200);
    const ids = r.json.map((s) => s.id);
    expect(ids).toContain("EIDW@2025-01-24");
    expect(ids).toContain("EIDW@2025-01-26");
    expect(r.json.find((s) => s.id === "EIDW@2025-01-24")).toMatchObject({ cancelled: 27, questions: 3, liability_drafted_cents: 8_214_600 });
  });

  it("serves the golden numbers", async () => {
    const r = await get<StormRun>(`/storms/${enc("EIDW@2025-01-24")}`);
    expect(r.status).toBe(200);
    const run = r.json;
    expect(run.counters).toMatchObject({ passengers: 5292, cancelled: 27, operated: 11, drafted: 172, held: 530, questions: 3, people: 3, repeat_questions: 0 });
    expect(run.liability_drafted_cents).toBe(8_214_600);
    // NS31 9,900,000 + NS113 7,120,000 + NS115 7,360,000 + NS117 4,200,000
    expect(run.entitlement_cents).toBe(28_580_000);
    expect(run.flights).toHaveLength(38);
    expect(run.learned).toHaveLength(4);
    expect(run.real_context).toMatchObject({ eurocontrol_departures: 179, reported_cancellations_dep: 119, red_warning: "06:00-11:00" });
  });

  it("computes the windows from the real METAR", async () => {
    const run = (await get<StormRun>(`/storms/${enc("EIDW@2025-01-24")}`)).json;
    expect(run.metar).toHaveLength(60);
    const main = run.windows.find((w) => w.start === "2025-01-24T02:30:00Z");
    expect(main).toMatchObject({ end: "2025-01-24T15:00:00Z", peak_gust_kt: 56 });
    expect(run.windows.find((w) => w.start === "2025-01-23T23:30:00Z")).toMatchObject({ end: "2025-01-24T00:30:00Z" });
  });

  it("groups the 27 cancellations exactly as the plan does", async () => {
    const run = (await get<StormRun>(`/storms/${enc("EIDW@2025-01-24")}`)).json;
    const decided = run.flights.filter((r) => r.decision);
    expect(decided).toHaveLength(27);
    const weather = decided.filter((r) => r.decision?.cause === "weather");
    expect(weather).toHaveLength(23);
    expect(weather.filter((r) => r.decision?.in_window_dep === "in")).toHaveLength(13);
    expect(weather.filter((r) => r.flight.ops_cause_code === "72")).toHaveLength(4);
    const knock = decided.filter((r) => r.decision?.cause === "knock_on");
    expect(knock.map((r) => r.flight.number).sort()).toEqual(["NS113", "NS115", "NS117"]);
    for (const k of knock) expect(k.decision).toMatchObject({ extraordinary: "needs_legal", outcome: "escalated", routed_to: "legal", question_id: "Q-2", in_window_dep: "out", in_window_arr: "out" });
    const ns31 = decided.find((r) => r.flight.id === "NS31@2025-01-24")?.decision;
    expect(ns31).toMatchObject({ cause: "technical", extraordinary: "not_extraordinary", recoded: true, recode_label: "71 → 41", in_window_dep: "out", window_margin_min: 90 });
    expect(ns31?.confidence).toMatchObject({ score: 0.91, label: "cause-finding confidence" });
    expect(ns31?.evidence.find((e) => e.struck)).toMatchObject({ value: "71", trust_tier: 3 });
    const operated = run.flights.filter((r) => r.flight.status === "operated");
    expect(operated).toHaveLength(11);
    for (const o of operated) expect(o.flight.sched_dep >= "2025-01-24T15:30:00Z" && o.flight.sched_dep <= "2025-01-24T17:30:00Z").toBe(true);
  });

  it("quotes only verbatim spans", async () => {
    const run = (await get<StormRun>(`/storms/${enc("EIDW@2025-01-24")}`)).json;
    const texts = new Map(SOURCES.map((s) => [s.id, s.text ?? ""]));
    for (const row of run.flights)
      for (const e of row.decision?.evidence ?? []) if (e.quote && texts.has(e.source_id)) expect(texts.get(e.source_id)).toContain(e.quote);
  });
});

describe("flight file", () => {
  it("NS31 carries the money, the handoff and the journal preview", async () => {
    const r = await get<FlightFile>(`/flights/${enc("NS31@2025-01-24")}`);
    expect(r.status).toBe(200);
    const f = r.json;
    expect(f.entitlements_summary).toMatchObject({ coupons: 172, full_entitlement_cents: 9_900_000, drafted_liability_cents: 3_465_000, claim_rate: 0.35, distance_km: 4804, band_eur: 600 });
    expect(f.entitlements_summary.elections).toEqual({ refund: 32, voucher: 14, reaccommodated_own: 112, reroute_partner: 14 });
    expect(f.handoff).toEqual(expect.objectContaining({ refunds_already_initiated: 32, not_repeated: true, rights_notices_drafted: 32, drafter_pii_seen: 0 }));
    const je = f.journal_preview[0];
    expect(je.kind).toBe("compensation_estimate");
    expect(je.status).toBe("draft");
    expect(je.memo).toContain("drafted, pending approval");
    expect(je.lines).toEqual([expect.objectContaining({ account: "4090", dr_cents: 3_465_000 }), expect.objectContaining({ account: "2140", cr_cents: 3_465_000 })]);
    expect(f.sample_entitlements.find((e) => e.coupon_id === "NS31@2025-01-24:14C")).toMatchObject({ status: "needs_ruling", compensation_cents: 60_000, voucher_offset_cents: 0 });
    expect(f.timeline[0]).toMatchObject({ at: "2025-01-23T21:40:00Z", kind: "tech_log" });
  });

  it("every flight in both storms has a file", async () => {
    for (const id of ["EIDW@2025-01-24", "EIDW@2025-01-26"]) {
      const run = (await get<StormRun>(`/storms/${enc(id)}`)).json;
      for (const row of run.flights) expect((await get(`/flights/${enc(row.flight.id)}`)).status).toBe(200);
    }
  });

  it("shows the band margin for NS108 DUB–BCN", async () => {
    const f = (await get<FlightFile>(`/flights/${enc("NS108@2025-01-24")}`)).json;
    expect(f.entitlements_summary).toMatchObject({ distance_km: 1486, band_margin_km: 14, band_label: "1,486 km · 14 km under the €400 band", status_line: "no compensation; refunds and care still due" });
  });

  it("404s an unknown flight with the error envelope", async () => {
    const r = await get<{ error: { code: string } }>(`/flights/${enc("NS999@2025-01-24")}`);
    expect(r.status).toBe(404);
    expect(r.json.error.code).toBe("not_found");
  });
});

describe("questions are role-scoped", () => {
  it("routes each question to its owner", async () => {
    await as("claims_lead");
    expect((await get<Question[]>("/questions?status=open")).json.map((q) => q.id)).toEqual(["Q-1"]);
    await as("legal");
    expect((await get<Question[]>("/questions?status=open")).json.map((q) => q.id)).toEqual(["Q-2"]);
    await as("controller");
    expect((await get<Question[]>("/questions?status=open")).json.map((q) => q.id)).toEqual(["Q-3"]);
    await as("ops");
    expect((await get<Question[]>("/questions?status=open")).json).toEqual([]);
    await as("cfo");
    expect((await get<Question[]>("/questions?status=all")).json).toHaveLength(3);
  });

  it("shows PII only to the Claims Lead", async () => {
    await as("claims_lead");
    const cl = (await get<Question[]>("/questions")).json[0];
    expect(JSON.stringify(cl)).toContain("Orla Keane");
    expect(cl).toMatchObject({ status: "reminded", holds_cents: 60_000, reason_tag: "sources-disagree" });
    expect(cl.confidence.score).toBe(0.39);
    token = null;
    const judge = (await get<Question[]>("/questions?status=all")).json;
    expect(JSON.stringify(judge)).not.toContain("Orla Keane");
    expect(judge.find((q) => q.id === "Q-2")).toMatchObject({ holds_cents: 4_749_600, reason_tag: "no-precedent" });
    expect(judge.find((q) => q.id === "Q-3")).toMatchObject({ holds_cents: 360_000, reason_tag: "release-proposal" });
  });
});

describe("rules and the CFO bridge", () => {
  it("lists the mined, regulation and hard-control rules", async () => {
    const rules = (await get<Rule[]>("/rules")).json;
    expect(rules.find((r) => r.id === "R-MIN-1")).toMatchObject({ support: "41 of 42", action: "apply_7_2_reduction", status: "active", times_cited: 14 });
    expect(rules.find((r) => r.static_card)).toMatchObject({ id: "REG-2026-2202", origin_example: "Reg (EU) 2026/2202 · in force 22 Oct 2026 · applies from 23 Oct 2027 · 9-month claim window" });
    expect(rules.filter((r) => r.tier === "hard_control").length).toBeGreaterThan(5);
  });

  it("serves the CFO bridge", async () => {
    const c = (await get<CfoMetrics>("/books/cfo")).json;
    expect(c).toMatchObject({ cash_basis_cents: 0, full_entitlement_cents: 9_900_000, drafted_liability_cents: 3_465_000, sensitivity_5pp_cents: 495_000, held_for_legal_cents: 4_749_600, recodes_count: 1, recodes_cents: 3_465_000, care_accrued_cents: 22_700_000, care_invoiced_cents: 22_130_000 });
  });
});
