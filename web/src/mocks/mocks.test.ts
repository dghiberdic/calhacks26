import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import type {
  AccessDecision,
  AccessMatrix,
  AnswerResponse,
  Blame,
  CfoMetrics,
  ChallengeResponse,
  ClaimCurve,
  Commit,
  ConfirmResponse,
  ControlMapping,
  EstimateCard,
  EvalReport,
  FlightFile,
  InjectResponse,
  Injection,
  InvariantResult,
  JournalEntry,
  MonthEndResponse,
  Question,
  ReplayDiff,
  Rollforward,
  Rule,
  RuleProposal,
  StormRun,
  StormSummary,
  TraceEvent,
} from "@/api/types";
import { sourceById } from "./data/world";
import { createMockFetch, createMockStream, resetMockWorld } from "./index";

const mockFetch = createMockFetch({ latencyMs: [0, 0] });
let token: string | null = null;
type Err = { error: { code: string; message: string } };

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
const EOWYN = `/storms/${enc("EIDW@2025-01-24")}`;
const HERMINIA = `/storms/${enc("EIDW@2025-01-26")}`;

async function as(role: string | null) {
  if (!role) {
    token = null;
    return;
  }
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
    expect(ids).toEqual(expect.arrayContaining(["EIDW@2025-01-24", "EIDW@2025-01-26"]));
    expect(r.json.find((s) => s.id === "EIDW@2025-01-24")).toMatchObject({ station: "EIDW", date: "2025-01-24", cancelled: 27, questions: 3, liability_drafted_cents: 8_214_600 });
  });

  it("serves the golden numbers", async () => {
    const run = (await get<StormRun>(EOWYN)).json;
    expect(run.counters).toMatchObject({ passengers: 5292, cancelled: 27, operated: 11, drafted: 172, held: 530, questions: 3, people: 3, repeat_questions: 0 });
    expect(run.liability_drafted_cents).toBe(8_214_600);
    // NS31 9,900,000 + NS113 7,120,000 + NS115 7,360,000 + NS117 4,200,000
    expect(run.entitlement_cents).toBe(28_580_000);
    expect(run.flights).toHaveLength(38);
    expect(run.learned).toHaveLength(4);
    expect(run.learned[0]).toMatchObject({ support: "41 of 42", rule_ref: "R-MIN-1@1" });
    expect(run.message).toBeNull();
    expect(run.real_context).toEqual(expect.objectContaining({ eurocontrol_departures: 179, normal_departures: "~292–316", reported_cancellations_dep: 119, reported_cancellations_arr: 109, red_warning: "06:00-11:00", orange_warning: "until 16:00" }));
  });

  it("computes the windows from the real METAR", async () => {
    const run = (await get<StormRun>(EOWYN)).json;
    expect(run.metar).toHaveLength(60);
    expect(run.metar[0]).toEqual({ station: "EIDW", valid: "2025-01-23T18:00:00Z", sknt: 6, gust: null, drct: 210, vsby_sm: 6.21, wxcodes: null, raw: "EIDW 231800Z 21006KT 170V250 9999 FEW009 BKN140 05/02 Q0995 NOSIG" });
    expect(run.windows.find((w) => w.start === "2025-01-24T02:30:00Z")).toMatchObject({ end: "2025-01-24T15:00:00Z", peak_gust_kt: 56, obs_count: 24, definition: "gust>=35kt or sknt>=30kt or vsby<0.5sm or wx in {SN,FZ,TS,GR}; gaps<2h merged" });
    expect(run.windows.find((w) => w.start === "2025-01-23T23:30:00Z")).toMatchObject({ end: "2025-01-24T00:30:00Z", peak_gust_kt: 38 });
  });

  it("groups the 27 cancellations exactly as the plan does", async () => {
    const run = (await get<StormRun>(EOWYN)).json;
    const decided = run.flights.filter((r) => r.decision);
    expect(decided).toHaveLength(27);
    const weather = decided.filter((r) => r.decision?.cause === "weather");
    expect(weather).toHaveLength(23);
    expect(weather.filter((r) => r.decision?.in_window_dep === "in")).toHaveLength(13);
    expect(weather.filter((r) => r.flight.ops_cause_code === "72")).toHaveLength(4);
    for (const w of weather) expect(w.decision?.confidence.score).toBeGreaterThanOrEqual(0.9);
    const knock = decided.filter((r) => r.decision?.cause === "knock_on");
    expect(knock.map((r) => r.flight.number).sort()).toEqual(["NS113", "NS115", "NS117"]);
    for (const k of knock) expect(k.decision).toMatchObject({ extraordinary: "needs_legal", outcome: "escalated", routed_to: "legal", question_id: "Q-2", in_window_dep: "out", in_window_arr: "out" });
    for (const k of knock) expect(k.flight.outbound_pair_id).toMatch(/^NS11[246]@2025-01-24$/);
    const ns31 = decided.find((r) => r.flight.id === "NS31@2025-01-24");
    expect(ns31?.flight).toMatchObject({ aircraft: "EI-NSB", pax: 172, sched_dep: "2025-01-24T16:30:00Z", ops_cause_code: "71" });
    expect(ns31?.decision).toMatchObject({ cause: "technical", extraordinary: "not_extraordinary", recoded: true, recode_label: "71 → 41", in_window_dep: "out", window_margin_min: 90, reason: "fault logged before storm", legal_basis: ["EU261 Art.5(3)", "CJEU C-549/07", "CJEU C-257/14"] });
    expect(ns31?.decision?.confidence).toMatchObject({ score: 0.91, label: "cause-finding confidence" });
    const struck = ns31?.decision?.evidence.find((e) => e.struck);
    expect(struck).toMatchObject({ value: "71", trust_tier: 3, quote: "STORM ÉOWYN CNL LIST → NETLINE, RSN 71" });
    const tiers = ns31?.decision?.evidence.map((e) => e.trust_tier) ?? [];
    expect([...tiers].sort()).toEqual(tiers);
    expect(ns31?.decision?.evidence[0]).toMatchObject({ source_id: "tech_log:EI-NSB@2025-01-23", value: "2025-01-23T21:40:00Z", trust_tier: 1 });
    const operated = run.flights.filter((r) => r.flight.status === "operated");
    expect(operated).toHaveLength(11);
    for (const o of operated) expect(o.flight.sched_dep >= "2025-01-24T15:30:00Z" && o.flight.sched_dep <= "2025-01-24T17:30:00Z").toBe(true);
    expect(run.flights.find((r) => r.flight.number === "NS30")?.flight).toMatchObject({ id: "NS30@2025-01-23", aircraft: "EI-NSN", ops_cause_code: "72" });
  });

  it("has a past-tense feed with contract chips", async () => {
    const run = (await get<StormRun>(EOWYN)).json;
    expect(run.feed.length).toBeGreaterThanOrEqual(15);
    const seqs = run.feed.map((e) => e.seq);
    expect([...seqs].sort((a, b) => a - b)).toEqual(seqs);
    expect(run.feed.find((e) => e.summary === "NS31 recoded 71 → 41 · 172 payouts drafted")).toMatchObject({ chip: "DRAFTED", amount_cents: 3_465_000 });
    expect(run.feed.find((e) => e.summary.startsWith("Asked Legal once about 3 knock-on returns"))?.chip).toBe("ASKED");
    expect(run.feed.find((e) => e.summary === "agent.drafter approve_payout → DENIED · SoD")?.chip).toBe("DENIED");
    expect(run.feed.filter((e) => e.chip === "LEARNED").length).toBeGreaterThanOrEqual(2);
    expect(run.feed.find((e) => e.kind === "reminder")?.summary).toContain("4,761 others settled");
  });

  it("quotes only verbatim spans and uses contract IDs and times", async () => {
    for (const id of ["EIDW@2025-01-24", "EIDW@2025-01-26"]) {
      const run = (await get<StormRun>(`/storms/${enc(id)}`)).json;
      for (const row of run.flights) {
        expect(row.flight.id).toMatch(/^[A-Za-z0-9@.:_-]+$/);
        expect(row.flight.sched_dep).toMatch(/Z$/);
        for (const e of row.decision?.evidence ?? []) {
          const text = sourceById(e.source_id)?.text;
          if (e.quote && text) expect(text).toContain(e.quote);
        }
      }
    }
  });
});

describe("flight file", () => {
  it("NS31 carries the money, the handoff and the journal preview", async () => {
    const f = (await get<FlightFile>(`/flights/${enc("NS31@2025-01-24")}`)).json;
    expect(f.entitlements_summary).toMatchObject({ coupons: 172, full_entitlement_cents: 9_900_000, drafted_liability_cents: 3_465_000, claim_rate: 0.35, distance_km: 4804, band_eur: 600, payouts_drafted: 172, status_line: "172 payouts drafted, pending Claims Lead approval" });
    expect(f.entitlements_summary.elections).toEqual({ refund: 32, voucher: 14, reaccommodated_own: 112, reroute_partner: 14 });
    expect(f.entitlements_summary.compensation_breakdown).toEqual([{ count: 158, band_eur: 600 }, { count: 14, band_eur: 300 }]);
    expect(f.handoff).toEqual(expect.objectContaining({ refunds_already_initiated: 32, not_repeated: true, rights_notices_drafted: 32, drafter_pii_seen: 0 }));
    const je = f.journal_preview[0];
    expect(je).toMatchObject({ kind: "compensation_estimate", status: "draft", built_from: 3, period: "2025-01" });
    expect(je.memo).toContain("drafted, pending approval");
    expect(je.lines).toEqual([expect.objectContaining({ account: "4090", dr_cents: 3_465_000 }), expect.objectContaining({ account: "2140", cr_cents: 3_465_000 })]);
    expect(f.sample_entitlements.find((e) => e.coupon_id === "NS31@2025-01-24:14C")).toMatchObject({ status: "needs_ruling", compensation_cents: 60_000, voucher_offset_cents: 0 });
    expect(f.sample_entitlements.find((e) => e.coupon_id === "NS31@2025-01-24:22F")).toMatchObject({ compensation_cents: 30_000, reduction: "art7_2_50pct" });
    expect(f.sample_entitlements.find((e) => e.coupon_id === "NS31@2025-01-24:3A")).toMatchObject({ refund_already_initiated: true, refund_due_cents: 0 });
    const kinds = f.timeline.map((m) => m.kind);
    expect(kinds[0]).toBe("tech_log");
    expect(kinds.indexOf("mcc")).toBeLessThan(kinds.indexOf("occ"));
    expect(f.timeline.find((m) => m.kind === "occ")?.text).toContain("RSN 71");
    expect(f.timeline.some((m) => m.kind === "crm" && m.at === "2025-01-24T06:02:00Z")).toBe(true);
    expect(f.timeline.some((m) => String(m.label).startsWith("16:00Z"))).toBe(true);
    expect(f.explanation?.text.startsWith("Not weather. Broken plane.")).toBe(true);
  });

  it("every flight in both storms has a file", async () => {
    for (const id of ["EIDW@2025-01-24", "EIDW@2025-01-26"]) {
      const run = (await get<StormRun>(`/storms/${enc(id)}`)).json;
      for (const row of run.flights) {
        const r = await get<FlightFile>(`/flights/${enc(row.flight.id)}`);
        expect(r.status).toBe(200);
        expect(r.json.timeline.length).toBeGreaterThan(0);
      }
    }
  });

  it("shows the band margin and the weather wording for NS108 DUB–BCN", async () => {
    const f = (await get<FlightFile>(`/flights/${enc("NS108@2025-01-24")}`)).json;
    expect(f.entitlements_summary).toMatchObject({ distance_km: 1486, band_margin_km: 14, band_label: "1,486 km · 14 km under the €400 band", status_line: "no compensation; refunds and care still due", full_entitlement_cents: 0 });
    expect(f.decision).toMatchObject({ cause: "weather", reason: "inside the storm window at DUB" });
    expect(f.sample_entitlements[0]).toMatchObject({ status: "no_compensation", care_due: true });
  });

  it("knock-on files show the C-74/19 pattern and Q2", async () => {
    const f = (await get<FlightFile>(`/flights/${enc("NS117@2025-01-24")}`)).json;
    expect(f.decision.legal_basis).toContain("CJEU C-74/19");
    expect(f.decision.evidence.find((e) => e.field === "spare.available_within_h")?.quote).toBe("No tail at MUC. Earliest ferry ex-DUB 15:30Z → MUC dep 18:25Z = STD+4h20.");
    expect(f.journal_preview[0].lines[1]).toMatchObject({ account: "2140", cr_cents: 840_000 });
    expect(f.entitlements_summary).toMatchObject({ question_id: "Q-2", drafted_liability_cents: 840_000 });
  });

  it("404s an unknown flight with the error envelope", async () => {
    const r = await get<Err>(`/flights/${enc("NS999@2025-01-24")}`);
    expect(r.status).toBe(404);
    expect(r.json.error.code).toBe("not_found");
  });
});

describe("questions are role-scoped", () => {
  it("routes each question to its owner; cfo and judge see all", async () => {
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
    await as(null);
    expect((await get<Question[]>("/questions?status=all")).json).toHaveLength(3);
    expect((await get<Err>("/questions?status=bogus")).status).toBe(422);
  });

  it("shows PII only to the Claims Lead", async () => {
    await as("claims_lead");
    const cl = (await get<Question[]>("/questions")).json[0] as Question & { others_settled: number };
    expect(JSON.stringify(cl)).toContain("Orla Keane");
    expect(cl).toMatchObject({ status: "reminded", remind_at: "2025-01-25T09:00:00Z", holds_cents: 60_000, reason_tag: "sources-disagree", recommended_option: "No signed acceptance, no offset: pay €600 cash; the voucher stays as goodwill.", others_settled: 4761 });
    expect(cl.confidence.score).toBe(0.39);
    expect(cl.options).toContain(cl.recommended_option);
    await as(null);
    const judge = (await get<Question[]>("/questions?status=all")).json;
    expect(JSON.stringify(judge)).not.toContain("Orla Keane");
    expect(judge.find((q) => q.id === "Q-2")).toMatchObject({ case_refs: ["NS113@2025-01-24", "NS115@2025-01-24", "NS117@2025-01-24"], holds_cents: 4_749_600, reason_tag: "no-precedent" });
    expect(judge.find((q) => q.id === "Q-2")?.confidence.score).toBe(0.47);
    expect(judge.find((q) => q.id === "Q-3")).toMatchObject({ case_refs: ["EIDW@2024-01-21"], holds_cents: 360_000, reason_tag: "release-proposal" });
    expect(judge.find((q) => q.id === "Q-3")?.confidence.score).toBe(0.72);
    await as("ops");
    const storm = (await get<StormRun>(EOWYN)).json;
    expect(JSON.stringify(storm)).not.toContain("Orla Keane");
  });
});

describe("Q1 → R-CL-1 → Herminia", () => {
  it("only the Claims Lead may answer, and the answer drafts a grounded rule", async () => {
    await as("legal");
    expect((await post<Err>("/questions/Q-1/answer", { decision: "x", explanation: "" })).json.error.code).toBe("forbidden");
    await as("claims_lead");
    const herminiaBefore = (await get<StormRun>(HERMINIA)).json;
    expect(herminiaBefore.feed.some((e) => e.summary.includes("settled"))).toBe(false);
    expect(herminiaBefore.counters.needs_ruling).toBe(32);
    const r = await post<AnswerResponse>("/questions/Q-1/answer", {
      decision: "No signed acceptance, no offset: pay €600 cash; the voucher stays as goodwill.",
      explanation: "She never signed. Same for every flight leaving the EU.",
    });
    expect(r.status).toBe(200);
    expect(r.json.ruling).toMatchObject({ question_id: "Q-1", author_role: "claims_lead", kind: "answer" });
    const p = r.json.proposal as RuleProposal;
    expect(p.rule).toMatchObject({ id: "R-CL-1", version: 1, action: "deny_offset", tier: "claims_lead_ruling", authority_required: "claims_lead", status: "shadow" });
    expect(p.rule.condition).toEqual({ all: [{ f: "voucher.in_lieu", op: "eq", v: true }, { f: "voucher.signed", op: "eq", v: false }, { f: "flight.departs_eu", op: "eq", v: true }] });
    expect(p.rule.grounding).toMatchObject({ signed: "No signed acceptance", departs_eu: "every flight leaving the EU" });
    expect(Object.values(p.checks).every(Boolean)).toBe(true);
    expect(Object.keys(p.checks).sort()).toEqual(["author_has_authority", "compiles", "grounded", "no_conflict", "no_hard_control", "reproduces_case"]);
    expect(p.would_flip.flips).toHaveLength(31);
    expect(p.would_flip.flips.every((f) => f.entity_id.startsWith("NS112@2025-01-26:"))).toBe(true);
    expect(p.widen_next).toMatchObject({ drop: "voucher.amount_cents" });
    expect((await get<Question[]>("/questions?status=answered")).json.map((q) => q.id)).toEqual(["Q-1"]);
    expect((await get<Rule[]>("/rules")).json.find((x) => x.id === "R-CL-1")?.status).toBe("shadow");
  });

  it("confirming saves the policy, settles Herminia's 31 and asks the BOS→DUB case once", async () => {
    await as("claims_lead");
    await post("/questions/Q-1/answer", { decision: "No signed acceptance, no offset: pay €600 cash; the voucher stays as goodwill.", explanation: "Every flight leaving the EU." });
    await as("legal");
    expect((await post<Err>(`/proposals/${enc("R-CL-1@1")}/confirm`)).status).toBe(403);
    await as("claims_lead");
    const c = await post<ConfirmResponse>(`/proposals/${enc("R-CL-1@1")}/confirm`);
    expect(c.status).toBe(200);
    expect(c.json.rule).toMatchObject({ id: "R-CL-1", status: "active" });
    expect(c.json.replay.flips).toHaveLength(31);
    const h = (await get<StormRun>(HERMINIA)).json;
    expect(h.feed.map((e) => e.summary)).toEqual(expect.arrayContaining(["31 unsigned in-lieu vouchers on EU departures settled · ruling cited R-CL-1@1", "BOS→DUB case asked again (doesn't depart the EU)"]));
    expect(h.counters).toMatchObject({ rules_cited: 31, needs_ruling: 1, questions: 1, repeat_questions: 0 });
    const open = (await get<Question[]>("/questions?status=open")).json;
    expect(open.map((q) => q.case_refs[0])).toEqual(["NS30@2025-01-25:12A"]);
    expect(open[0]).toMatchObject({ reason_tag: "out-of-scope", routed_to: "claims_lead" });
    const e = (await get<StormRun>(EOWYN)).json;
    expect(e.counters.repeat_questions).toBe(0);
    expect(e.feed.some((x) => x.chip === "RULED" && x.summary.includes("R-CL-1@1"))).toBe(true);
    const f = (await get<FlightFile>(`/flights/${enc("NS31@2025-01-24")}`)).json;
    expect(f.sample_entitlements.find((x) => x.coupon_id === "NS31@2025-01-24:14C")).toMatchObject({ status: "owed", voucher_offset_cents: 0, rules_applied: ["R-CL-1@1"] });
    expect((await get<Rule[]>("/rules")).json.find((x) => x.id === "R-CL-1")).toMatchObject({ status: "active", times_cited: 32 });
    // confirming twice answers the same thing
    expect((await post<ConfirmResponse>(`/proposals/${enc("R-CL-1@1")}/confirm`)).json.replay.flips).toHaveLength(31);
  });

  it("an offset ruling trips the hard control", async () => {
    await as("claims_lead");
    const r = await post<AnswerResponse>("/questions/Q-1/answer", { decision: "Offset the €300 voucher and pay €300 cash.", explanation: "" });
    expect(r.json.proposal?.checks.no_hard_control).toBe(false);
    const c = await post<Err>("/proposals/R-CL-1@1/confirm");
    expect(c.status).toBe(422);
    expect(c.json.error.message).toContain("hard control");
  });

  it("widens one rung and reverts with a replay diff", async () => {
    await as("claims_lead");
    await post("/questions/Q-1/answer", { decision: "No signed acceptance, no offset: pay €600 cash; the voucher stays as goodwill.", explanation: "" });
    await post("/proposals/R-CL-1@1/confirm");
    const w = await post<RuleProposal>("/rules/R-CL-1/widen");
    expect(w.status).toBe(200);
    expect(w.json.rule).toMatchObject({ id: "R-CL-1", version: 2, supersedes: "R-CL-1@1" });
    expect(Object.values(w.json.rule.scope).filter((v) => typeof v === "string" && v.startsWith("case:"))).toHaveLength(1);
    const rv = await post<ReplayDiff>(`/rules/${enc("R-CL-1@1")}/revert`);
    expect(rv.status).toBe(200);
    expect(rv.json.flips.length).toBeGreaterThanOrEqual(31);
    expect(rv.json.locked_periods_untouched).toEqual(["2025-01"]);
    expect((await get<Question[]>("/questions?status=open")).json.map((q) => q.id)).toContain("Q-1");
  });
});

describe("Q2 → R-LEG-1: one ruling settles 3 flights", () => {
  it("drafts the scripted rule and moves the liability by −4,749,600", async () => {
    await as("legal");
    const r = await post<AnswerResponse>("/questions/Q-2/answer", {
      decision: "A return sector of a storm-cancelled rotation is extraordinary only if no aircraft and crew could operate it within 3 h of STD, and passengers were offered the earliest reroute on any carrier (C-74/19).",
      explanation: "",
    });
    const p = r.json.proposal as RuleProposal;
    expect(p.rule).toMatchObject({ id: "R-LEG-1", version: 1, action: "set_extraordinary", tier: "legal_ruling", valid_from: null });
    expect(p.rule.grounding).toMatchObject({ available_within_h: "within 3 h of STD", reroute_earliest_offered: "offered the earliest reroute on any carrier" });
    expect(p.would_flip.flips.map((f) => f.entity_id).sort()).toEqual(["NS113@2025-01-24", "NS115@2025-01-24", "NS117@2025-01-24"]);
    expect(p.would_flip.total_delta_cents).toBe(-4_749_600);
    const c = await post<ConfirmResponse>("/proposals/R-LEG-1@1/confirm");
    expect(c.json.replay.total_delta_cents).toBe(-4_749_600);
    expect(c.json.replay.locked_periods_untouched).toEqual(["2025-01"]);
    expect(c.json.replay.adjustment_je_ids).toHaveLength(1);
    const run = (await get<StormRun>(EOWYN)).json;
    expect(run.liability_drafted_cents).toBe(3_465_000);
    expect(run.counters).toMatchObject({ held: 0, rules_cited: 17, repeat_questions: 0 });
    expect(run.flights.filter((x) => x.decision?.cause === "knock_on").every((x) => x.decision?.extraordinary === "extraordinary" && x.decision.rules_applied.includes("R-LEG-1@1"))).toBe(true);
    expect((await get<CfoMetrics>("/books/cfo")).json.held_for_legal_cents).toBe(0);
    const je = (await get<JournalEntry[]>("/books/journal?period=2025-02")).json.find((x) => x.id === c.json.replay.adjustment_je_ids?.[0]);
    expect(je).toMatchObject({ kind: "change_in_estimate", ias8_class: "change_in_estimate", status: "draft", period: "2025-02" });
    const rf = (await get<Rollforward>("/books/rollforward?period=2025-02")).json;
    expect(rf.ties_to_gl).toBe(true);
    expect(rf.rows.find((x) => x.cohort === "EIDW@2025-01-24")?.closing_cents).toBe(2_574_000);
    expect(rf.rows.find((x) => x.cohort === "EIDW@2025-01-24:medium_1500_3500")?.closing_cents).toBe(0);
    expect((await get<Rule[]>("/rules")).json.find((x) => x.id === "R-LEG-1")?.times_cited).toBe(3);
    const rv = await post<ReplayDiff>("/rules/R-LEG-1/revert");
    expect(rv.json).toMatchObject({ total_delta_cents: 4_749_600, locked_periods_untouched: ["2025-01"] });
    expect(rv.json.flips).toHaveLength(3);
    expect((await get<StormRun>(EOWYN)).json.liability_drafted_cents).toBe(8_214_600);
  });
});

describe("Q3 rejection → R-CTL-1 → all storm cohorts?", () => {
  it("turns the Controller's rejection into keep_tail and asks once more", async () => {
    await as("controller");
    const r = await post<AnswerResponse>("/questions/Q-3/answer", { decision: "Reject: never release the tail. At M12 keep (ultimate − M12 rate) × entitlement until the six-year limitation.", explanation: "Never release the tail." });
    expect(r.json.ruling.kind).toBe("rejection");
    expect(r.json.proposal?.rule).toMatchObject({ id: "R-CTL-1", action: "keep_tail", tier: "controller_ruling" });
    await post("/proposals/R-CTL-1@1/confirm");
    const open = (await get<Question[]>("/questions?status=open")).json;
    expect(open.map((q) => q.title)).toEqual(["All storm cohorts?"]);
    const a = await post<AnswerResponse>(`/questions/${open[0].id}/answer`, { decision: "Yes: every storm cohort, from M12 until the six-year limitation.", explanation: "" });
    expect(a.json.proposal?.rule).toMatchObject({ id: "R-CTL-1", version: 2, supersedes: "R-CTL-1@1", scope: {} });
    const rf = (await get<Rollforward>("/books/rollforward?period=2025-02")).json;
    expect(rf.rows.find((x) => x.cohort === "EIDW@2024-01-21")).toMatchObject({ opening_cents: 360_000, closing_cents: 360_000 });
  });

  it("rejecting a pending proposal reopens its question", async () => {
    await as("controller");
    await post("/questions/Q-3/answer", { decision: "Reject: never release the tail.", explanation: "" });
    const rj = await post<AnswerResponse>("/rules/R-CTL-1@1/reject", { explanation: "Wrong scope; I'll answer again." });
    expect(rj.json).toMatchObject({ ruling: { kind: "rejection" }, proposal: null });
    expect((await get<Question[]>("/questions?status=open")).json.map((q) => q.id)).toEqual(["Q-3"]);
    expect((await post<Err>("/rules/HC-SOD-1/reject", { explanation: "no" })).status).toBe(403);
  });
});

describe("books", () => {
  it("rolls 2140 forward with the plan's numbers and ties to GL", async () => {
    const jan = (await get<Rollforward>("/books/rollforward?period=2025-01")).json;
    expect(jan.rows.find((r) => r.cohort === "EIDW@2025-01-24")).toMatchObject({ opening_cents: 0, new_cents: 3_465_000, claims_approved_cents: 360_000, closing_cents: 3_105_000 });
    expect(jan.ties_to_gl).toBe(true);
    expect(jan.closing_total_cents).toBe(jan.gl_balance_cents);
    const feb = (await get<Rollforward>("/books/rollforward?period=2025-02")).json;
    expect(feb.rows.find((r) => r.cohort === "EIDW@2025-01-24")).toMatchObject({ opening_cents: 3_105_000, claims_approved_cents: 930_000, change_in_estimate_cents: 399_000, closing_cents: 2_574_000 });
    expect(feb.rows.find((r) => r.cohort === "EIDW@2024-01-21")).toMatchObject({ opening_cents: 360_000, closing_cents: 360_000 });
    expect(feb.ties_to_gl).toBe(true);
    expect(feb.gl_balance_cents).toBe(feb.closing_total_cents);
  });

  it("serves the estimate card and the curves", async () => {
    const e = (await get<EstimateCard>(`/books/estimate?cohort=${enc("EIDW@2025-01-24")}`)).json;
    expect(e).toMatchObject({ pax: 172, entitlement_cents: 9_900_000, curve_version: "LH-v1", months_developed: 1, expected_loss_cents: 2_175_000, bf_cents: 2_574_000, selected: "bf", actual_vs_expected: 1.448, sensitivity_5pp_cents: 495_000, preparer: "controller" });
    expect(e.chain_ladder_cents).toBeGreaterThan(e.bf_cents);
    const lh = (await get<ClaimCurve>("/books/curve?segment=long_haul_gt3500")).json;
    expect(lh).toMatchObject({ version: "LH-v1", ultimate: 0.35, observed_through_month: 18 });
    expect(lh.points).toEqual([[1, 0.09], [3, 0.17], [6, 0.24], [12, 0.29], [18, 0.32]]);
    expect(lh.n_by_point).toHaveLength(5);
    expect((await get<ClaimCurve>("/books/curve?segment=medium_1500_3500")).json.ultimate).toBe(0.27);
    expect((await get<ClaimCurve>("/books/curve?segment=short_le1500")).json.ultimate).toBe(0.2);
    expect((await get<Err>("/books/curve?segment=nope")).status).toBe(422);
  });

  it("serves the CFO bridge", async () => {
    const c = (await get<CfoMetrics>("/books/cfo")).json;
    expect(c).toMatchObject({ cash_basis_cents: 0, full_entitlement_cents: 9_900_000, drafted_liability_cents: 3_465_000, sensitivity_5pp_cents: 495_000, held_for_legal_cents: 4_749_600, recodes_count: 1, recodes_cents: 3_465_000, care_accrued_cents: 22_700_000, care_invoiced_cents: 22_130_000, refunds_within_7d_pct: 100 });
    expect(c.method_range_cents[0]).toBeLessThanOrEqual(2_574_000);
    expect(c.method_range_cents[1]).toBeGreaterThanOrEqual(2_574_000);
    expect(c.liability_bridge.map((r) => r.closing_cents)).toEqual([3_105_000, 2_574_000]);
  });

  it("enforces segregation of duties on approval", async () => {
    await as("controller");
    const sod = await post<Err>("/books/journal/JE-000204/approve");
    expect(sod.status).toBe(403);
    expect(sod.json.error).toEqual({ code: "sod_violation", message: "Preparer can't approve their own entry." });
    const trace = (await get<TraceEvent[]>("/trace?since=0")).json;
    expect(trace[trace.length - 1]).toMatchObject({ kind: "access_denied", chip: "DENIED" });
    expect(trace[trace.length - 1].summary).toContain("DENIED · SoD");
    const log = (await get<AccessDecision[]>("/access/log")).json;
    expect(log[0]).toMatchObject({ principal: "controller", allowed: false });
    const okApprove = await post<JournalEntry>("/books/journal/JE-000101/approve");
    expect(okApprove.json).toMatchObject({ status: "approved", approver: "controller" });
    await as("cfo");
    expect((await post<JournalEntry>("/books/journal/JE-000204/approve")).json.status).toBe("approved");
    await as("ops");
    expect((await post<Err>("/books/journal/JE-000102/approve")).json.error.code).toBe("forbidden");
  });

  it("runs the Feb month end: +399,000 change in estimate", async () => {
    await as("ops");
    expect((await post<Err>("/books/month-end", { period: "2025-02" })).status).toBe(403);
    await as("controller");
    const m = (await post<MonthEndResponse>("/books/month-end", { period: "2025-02" })).json;
    const cie = m.entries.find((e) => e.kind === "change_in_estimate");
    expect(cie).toMatchObject({ ias8_class: "change_in_estimate", status: "draft" });
    expect(cie?.lines).toEqual([expect.objectContaining({ account: "4090", dr_cents: 399_000 }), expect.objectContaining({ account: "2140", cr_cents: 399_000 })]);
    expect(m.rollforward.rows.find((r) => r.cohort === "EIDW@2025-01-24")?.closing_cents).toBe(2_574_000);
    expect(m.estimate).toMatchObject({ bf_cents: 2_574_000, selected: "bf" });
    expect((await post<Err>("/books/month-end", { period: "2025-01" })).status).toBe(422);
  });

  it("locks periods and keeps every invariant green", async () => {
    await as("controller");
    expect((await post<{ locked: string[] }>("/books/lock", { period: "2025-02" })).json.locked).toEqual(["2025-01", "2025-02"]);
    const inv = (await get<InvariantResult[]>("/books/invariants")).json;
    expect(inv.length).toBeGreaterThanOrEqual(10);
    expect(inv.every((i) => i.ok)).toBe(true);
    expect(inv.find((i) => i.description.startsWith("2125 refund clearing = 0"))?.ok).toBe(true);
    expect(inv.find((i) => i.description.includes("ties to GL 2140"))?.ok).toBe(true);
  });
});

describe("challenge", () => {
  it("'the storm would have grounded it anyway' → Decision stands.", async () => {
    const r = await post<ChallengeResponse>(`/flights/${enc("NS31@2025-01-24")}/challenge`, { text: "The storm would have grounded it anyway" });
    expect(r.status).toBe(200);
    expect(r.json).toMatchObject({ classification: "assertion", decision_stands: true, question: null });
    expect(r.json.reply.text.startsWith("Decision stands.")).toBe(true);
    for (const s of ["≤25 kt", "16:00Z", "11 Northstar departures", "15:30 and 17:30Z", "23 Jan 21:40Z", "no MEL relief"]) expect(r.json.reply.text).toContain(s);
    expect(r.json.cited.some((e) => e.trust_tier === 4 && e.field === "challenge.text")).toBe(true);
  });

  it("an Airbus hidden-defect notice is a new legal pattern for Legal", async () => {
    const r = await post<ChallengeResponse>(`/flights/${enc("NS31@2025-01-24")}/challenge`, { text: "Airbus operator notice: hidden defect in this EDP batch" });
    expect(r.json).toMatchObject({ classification: "new_legal_pattern", decision_stands: true });
    expect(r.json.question).toMatchObject({ routed_to: "legal", reason_tag: "new-legal-pattern" });
    expect(r.json.question?.confidence.score).toBe(0.52);
    const run = (await get<StormRun>(EOWYN)).json;
    expect(run.counters).toMatchObject({ questions: 4, people: 3 });
    expect(run.flights.find((x) => x.flight.number === "NS31")?.decision?.cause).toBe("technical");
  });
});

describe("judge's desk", () => {
  it("answers bad input with plain 422s", async () => {
    const unknown = await post<Err>("/desk", { icao: "ZZZZ", date: "2025-01-24" });
    expect(unknown.status).toBe(422);
    expect(unknown.json.error.code).toBe("unknown_airport");
    expect((await post<Err>("/desk", { icao: "EGLL", date: "2099-01-01" })).json.error.code).toBe("future_date");
    expect((await post<Err>("/desk", { icao: "EGLL", date: "2019-03-04" })).json.error.code).toBe("no_metar");
    expect((await post<Err>("/desk", { icao: "EGLL", date: "24/01/2025" })).json.error.code).toBe("validation");
  });

  it("returns the real runs for Dublin's storm days", async () => {
    const r = await post<StormRun>("/desk", { icao: "EIDW", date: "2025-01-24" });
    expect(r.json).toMatchObject({ id: "EIDW@2025-01-24", liability_drafted_cents: 8_214_600 });
    expect((await post<StormRun>("/desk", { icao: "DUB", date: "2025-01-26" })).json.id).toBe("EIDW@2025-01-26");
  });

  it("generates a stormy day with a miscode caught and planted vouchers", async () => {
    const run = (await post<StormRun>("/desk", { icao: "KBOS", date: "2023-12-18" })).json;
    expect(run.id).toBe("KBOS@2023-12-18");
    expect(run.windows.length).toBeGreaterThan(0);
    expect(run.metar[0].raw).toContain("RMK MOCK");
    expect(run.flights.some((x) => x.decision?.recoded)).toBe(true);
    expect(run.counters.needs_ruling).toBe(4);
    expect(run.feed.some((e) => e.summary.includes("unsigned in-lieu vouchers held"))).toBe(true);
    for (const row of run.flights) expect((await get(`/flights/${enc(row.flight.id)}`)).status).toBe(200);
    expect((await get<StormSummary[]>("/storms")).json.map((s) => s.id)).toContain("KBOS@2023-12-18");
  });

  it("a calm day says so", async () => {
    let calm: StormRun | null = null;
    for (let d = 1; d <= 28 && !calm; d++) {
      const run = (await post<StormRun>("/desk", { icao: "LEMD", date: `2024-06-${String(d).padStart(2, "0")}` })).json;
      if (run.message) calm = run;
    }
    expect(calm?.message).toMatch(/^max gust \d+ kt · no storm window$/);
    expect(calm?.windows).toEqual([]);
    expect(calm?.counters.cancelled).toBe(0);
  });
});

describe("injections", () => {
  it("serves the 8 rehearsed scenarios and every one returns a result", async () => {
    const list = (await get<Injection[]>("/injections")).json;
    expect(list.map((i) => i.id)).toEqual([
      "01_aog_inside_window",
      "02_duplicate_direct_plus_agency",
      "03_prompt_injection_email",
      "04_chargeback_after_bot_refund",
      "05_airbus_hidden_defect_notice",
      "06_claim_after_limitation",
      "07_challenge_storm_anyway",
      "08_uk261_520_on_dub_lhr",
    ]);
    for (const inj of list) {
      resetMockWorld();
      const r = await post<InjectResponse>("/inject", inj.request);
      expect(r.status, inj.id).toBe(200);
      expect(r.json.events.length, inj.id).toBeGreaterThan(0);
      expect(r.json.message, inj.id).toBeTruthy();
      for (const f of r.json.facts) expect(r.json.source.text).toContain(f.span ?? "");
    }
  });

  it("an AOG inside the window holds the flight for Legal", async () => {
    const inj = (await get<Injection[]>("/injections")).json[0];
    const r = (await post<InjectResponse>("/inject", inj.request)).json;
    expect(r.affected).toContain("NS110@2025-01-24");
    expect(r.facts.find((f) => f.field === "aog.logged_at")?.value).toBe("2025-01-24T08:20:00Z");
    const run = (await get<StormRun>(EOWYN)).json;
    expect(run.flights.find((x) => x.flight.id === "NS110@2025-01-24")?.decision).toMatchObject({ cause: "concurrent", extraordinary: "needs_legal", routed_to: "legal" });
    expect(run.liability_drafted_cents).toBe(8_214_600 + 950_000);
  });

  it("the injection email yields facts only and a denial", async () => {
    const inj = (await get<Injection[]>("/injections")).json[2];
    const r = (await post<InjectResponse>("/inject", inj.request)).json;
    expect(r.dropped_unverifiable).toBeGreaterThanOrEqual(1);
    expect(r.events.some((e) => e.chip === "DENIED")).toBe(true);
    expect((await get<StormRun>(EOWYN)).json.counters.drafted).toBe(172);
  });

  it("unparseable text falls back to an Ops question, never a 500", async () => {
    const r = await post<InjectResponse>("/inject", { kind: "occ_log", text: "lorem ipsum dolor sit amet" });
    expect(r.status).toBe(200);
    expect(r.json.fallback_used).toBe(true);
    expect((await post<Err>("/inject", { kind: "fax", text: "x" })).status).toBe(422);
  });
});

describe("trace, access, controls, proof", () => {
  it("serves hash-chained commits with LLM calls, people and agents", async () => {
    await as("claims_lead");
    await post("/questions/Q-1/answer", { decision: "No signed acceptance, no offset: pay €600 cash; the voucher stays as goodwill.", explanation: "" });
    const commits = (await get<Commit[]>("/commits?limit=500")).json;
    expect(commits[0].parent).toBe(commits[1].hash);
    for (const c of commits) expect(c.hash).toMatch(/^[0-9a-f]{64}$/);
    const kinds = new Set(commits.map((c) => c.kind));
    for (const k of ["fact", "decision", "entitlement", "question", "ruling", "journal_event", "access_denied", "llm_call"]) expect(kinds.has(k as Commit["kind"]), k).toBe(true);
    const actors = new Set(commits.map((c) => c.actor));
    expect(actors.has("claims_lead")).toBe(true);
    expect(actors.has("agent.drafter")).toBe(true);
    expect((await get<Commit[]>("/commits?limit=5")).json).toHaveLength(5);
  });

  it("blames NS31's euros back to a METAR observation", async () => {
    const b = (await get<Blame>(`/blame?target=${enc("NS31@2025-01-24")}`)).json;
    expect(b.steps[0].label).toContain("€34,650");
    expect(b.steps.some((s) => s.label.startsWith("R-MIN-1@1"))).toBe(true);
    expect(b.steps.some((s) => s.quote === "23JAN 21:40Z EI-NSB DUB N/S. HYD FLUID ENG 2 LWR COWL. GND RUN: ECAM HYD Y ENG 2 PUMP LO PR. EXT LEAK EDP CASE DRAIN PORT, EXCEEDS AMM LIMIT. EDP RPLCMT REQD. NO MEL RELIEF. A/C AOG.")).toBe(true);
    const last = b.steps[b.steps.length - 1];
    expect(last.label.startsWith("METAR")).toBe(true);
    expect(last.quote).toBe("EIDW 241630Z 23011G22KT 190V270 9999 -RA FEW012 SCT020 BKN050 05/00 Q0990 NOSIG");
    for (const target of ["JE-000101", "NS31@2025-01-24:14C", "R-MIN-1@1", "NS108@2025-01-24"]) expect((await get(`/blame?target=${enc(target)}`)).status, target).toBe(200);
    expect((await get<Err>("/blame?target=nothing")).status).toBe(404);
  });

  it("audits a journal entry", async () => {
    const a = (await get<Record<string, unknown>>("/audit/JE-000101")).json;
    expect(a).toMatchObject({ balanced: true, period_locked: true });
    expect((a.register as unknown[]).length).toBeGreaterThan(0);
    expect((await get("/audit/JE-999999")).status).toBe(404);
  });

  it("maps access for people and agents, with the SoD denial on file", async () => {
    const m = (await get<AccessMatrix>("/access/matrix")).json;
    expect(m.principals).toEqual(expect.arrayContaining(["claims_lead", "ops", "agent.drafter", "agent.reader"]));
    expect(m.cells.ops.coupons).toBe("redacted");
    expect(m.cells.controller.journal).toBe("approve");
    const log = (await get<AccessDecision[]>("/access/log")).json;
    expect(log.find((x) => x.principal === "agent.drafter" && x.action === "approve_payout")).toMatchObject({ allowed: false });
    const controls = (await get<ControlMapping[]>("/controls")).json;
    expect(controls.map((c) => c.framework_ref)).toEqual(["CC6.1", "CC6.3", "CC7.2", "CC8.1", "PI1"]);
  });

  it("serves an EvalReport with the proof headline", async () => {
    const e = (await get<EvalReport>("/eval")).json;
    expect(e.label).toBe("calibrated on synthetic labels; validates the pipeline, not the world");
    expect(e.stormcheck_runs).toMatchObject({ liability_eur: [34650, 34650, 34650], hash_identical: true });
    expect(e.baseline.hash_identical).toBe(false);
    expect(new Set(e.baseline.liability_eur as number[]).size).toBe(3);
    for (const bin of e.calibration.cause) expect(bin.wilson_lo <= bin.accuracy && bin.accuracy <= bin.wilson_hi).toBe(true);
  });
});

describe("session, clock, reset, health", () => {
  it("issues decodable tokens and fails closed on foreign ones", async () => {
    const r = await post<{ token: string; session: { role: string; principal: string } }>("/session", { role: "controller", name: "Niamh" });
    expect(r.json.token.startsWith("mock.")).toBe(true);
    expect(r.json.session).toMatchObject({ role: "controller", principal: "controller" });
    expect((await post<Err>("/session", { role: "pilot" })).status).toBe(422);
    token = "not-ours";
    expect((await get<Err>("/storms")).status).toBe(403);
  });

  it("moves the clock forward only, sending reminders", async () => {
    expect((await post<Err>("/clock", { known_at: "2025-01-24T00:00:00Z" })).status).toBe(422);
    const r = await post<{ known_at: string }>("/clock", { known_at: "2025-01-25T12:00:00Z" });
    expect(r.json.known_at).toBe("2025-01-25T12:00:00Z");
    expect((await get<{ known_at: string }>("/clock")).json.known_at).toBe("2025-01-25T12:00:00Z");
    expect((await get<Question[]>("/questions?status=all")).json.filter((q) => q.status === "reminded").map((q) => q.id)).toEqual(["Q-1", "Q-2", "Q-3"]);
  });

  it("POST /reset restores the baseline", async () => {
    await as("legal");
    await post("/questions/Q-2/answer", { decision: "A return sector of a storm-cancelled rotation is extraordinary only if no aircraft and crew could operate it within 3 h of STD, and passengers were offered the earliest reroute on any carrier (C-74/19).", explanation: "" });
    await post("/proposals/R-LEG-1@1/confirm");
    expect((await get<StormRun>(EOWYN)).json.liability_drafted_cents).toBe(3_465_000);
    expect((await post<{ ok: boolean }>("/reset")).json).toEqual({ ok: true });
    expect((await get<StormRun>(EOWYN)).json.liability_drafted_cents).toBe(8_214_600);
    expect((await get<{ ok: boolean; mode: string }>("/health")).json).toMatchObject({ ok: true, mode: "mock" });
    expect((await get<Err>("/nope")).status).toBe(404);
  });
});

describe("contract formats", () => {
  /** Walk a payload: datetimes end in Z, *_cents are integers, id-like fields use only [A-Za-z0-9@.:_-]. */
  function check(value: unknown, path = "$"): string[] {
    const bad: string[] = [];
    if (typeof value === "string") {
      if (/^\d{4}-\d{2}-\d{2}T/.test(value) && !/Z$/.test(value)) bad.push(`${path} not Z: ${value}`);
    } else if (Array.isArray(value)) value.forEach((v, i) => bad.push(...check(v, `${path}[${i}]`)));
    else if (value && typeof value === "object") {
      for (const [k, v] of Object.entries(value)) {
        if (k.endsWith("_cents") && typeof v === "number" && !Number.isInteger(v)) bad.push(`${path}.${k} not integer cents: ${v}`);
        if ((k === "id" || k === "flight_id" || k === "coupon_id" || k === "question_id" || k === "rule_ref") && typeof v === "string" && !/^[A-Za-z0-9@.:_-]+$/.test(v)) bad.push(`${path}.${k} bad id: ${v}`);
        bad.push(...check(v, `${path}.${k}`));
      }
    }
    return bad;
  }

  it("every GET payload uses Z times, integer cents and contract IDs", async () => {
    await as("cfo");
    const paths = [
      "/storms", EOWYN, HERMINIA, `/flights/${enc("NS31@2025-01-24")}`, `/flights/${enc("NS117@2025-01-24")}`, `/flights/${enc("NS120@2025-01-24")}`, "/questions?status=all", "/rules", "/trace?since=0", "/commits?limit=100",
      `/blame?target=${enc("NS31@2025-01-24")}`, "/audit/JE-000101", "/books/rollforward?period=2025-01", "/books/rollforward?period=2025-02", `/books/estimate?cohort=${enc("EIDW@2025-01-24")}`,
      "/books/journal", "/books/curve?segment=long_haul_gt3500", "/books/cfo", "/books/invariants", "/access/matrix", "/access/log", "/controls", "/injections", "/eval", "/health", "/airports", "/clock",
    ];
    for (const path of paths) {
      const r = await get(path);
      expect(r.status, path).toBe(200);
      expect(check(r.json), path).toEqual([]);
    }
    const desk = await post("/desk", { icao: "EGLL", date: "2024-01-21" });
    expect(check(desk.json)).toEqual([]);
  });

  it("the BOS→DUB follow-up ruling widens R-CL-1 past departs_eu", async () => {
    await as("claims_lead");
    await post("/questions/Q-1/answer", { decision: "No signed acceptance, no offset: pay €600 cash; the voucher stays as goodwill.", explanation: "Every flight leaving the EU." });
    await post("/proposals/R-CL-1@1/confirm");
    const q6 = (await get<Question[]>("/questions?status=open")).json[0];
    const a = await post<AnswerResponse>(`/questions/${q6.id}/answer`, { decision: q6.recommended_option, explanation: "Here too." });
    expect(a.json.proposal?.rule).toMatchObject({ id: "R-CL-1", version: 2, supersedes: "R-CL-1@1" });
    expect(a.json.proposal?.rule.scope).not.toHaveProperty("flight.departs_eu");
    await post("/proposals/R-CL-1@2/confirm");
    const h = (await get<StormRun>(HERMINIA)).json;
    expect(h.counters.needs_ruling).toBe(0);
    expect(h.feed.some((e) => e.summary.startsWith("BOS→DUB case settled"))).toBe(true);
    const rules = (await get<Rule[]>("/rules")).json.filter((r) => r.id === "R-CL-1");
    expect(rules.map((r) => [r.version, r.status])).toEqual([[1, "retired"], [2, "active"]]);
  });
});

describe("stream", () => {
  afterEach(() => vi.useRealTimers());

  it("replays events after lastSeq every 2 s, then streams new ones", async () => {
    vi.useFakeTimers();
    const got: TraceEvent[] = [];
    const lastSeq = 20;
    const stop = createMockStream((e) => got.push(e), lastSeq);
    vi.advanceTimersByTime(2_000);
    expect(got).toHaveLength(1);
    expect(got[0].seq).toBe(lastSeq + 1);
    vi.advanceTimersByTime(60_000);
    const replayed = got.length;
    expect(got.every((e, i) => i === 0 || e.seq > got[i - 1].seq)).toBe(true);
    // zero-latency mock fetch needs no timers, so the write can run under the fake clock
    await as("controller");
    await post("/books/journal/JE-000204/approve");
    vi.advanceTimersByTime(4_000);
    expect(got.length).toBeGreaterThan(replayed);
    expect(got[got.length - 1].chip).toBe("DENIED");
    stop();
  });
});
