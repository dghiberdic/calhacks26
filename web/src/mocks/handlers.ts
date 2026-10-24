// The mock router: every route in CONTRACTS §3, answered from state.ts. Paths arrive as the API client
// sends them (after `/api`, segments URI-encoded, query string attached). Errors use the contract
// envelope {"error":{"code","message"}} with plain messages; user input never produces a 500.
import type { CfoMetrics, CurveSegment, Role, Session } from "@/api/types";
import { answerQuestion, approveJournal, challenge, confirmProposal, lockPeriod, monthEnd, rejectRule, revertRule, setClock, widenRule } from "./actions";
import { CURVES, invariants } from "./data/books";
import { INJECTIONS } from "./data/injections";
import { deskRun, inject } from "./live";
import { accessMatrix, audit, blame, CONTROLS, EVAL_REPORT, newestCommits } from "./views";
import { fail, ok, PEOPLE, ROLE_NAME, ROLES, type Reply, type Req } from "./reply";
import { AIRPORTS } from "./data/airports";
import { cfoMetrics, COHORT_ISHA, COHORT_LH, estimateCard, rollforward } from "./data/books";
import { decide, fullEntitlementCents, HERO_FLIGHT, liabilityCents, stormMoney } from "./data/engine";
import { EOWYN_ID } from "./data/flights";
import { cohortEntitlement, ctxOf, flightFile, publicQuestion, resetState, rulesView, S, specOf, stormById, stormRun, stormSummaries, type MockState } from "./state";

// ---------- session tokens: mock.<base64url(JSON Session)> ----------
function b64urlEncode(text: string) {
  const bytes = new TextEncoder().encode(text);
  let bin = "";
  for (const b of bytes) bin += String.fromCharCode(b);
  return btoa(bin).replace(/\+/g, "-").replace(/\//g, "_").replace(/=+$/, "");
}
function b64urlDecode(text: string) {
  const bin = atob(text.replace(/-/g, "+").replace(/_/g, "/") + "===".slice((text.length + 3) % 4));
  return new TextDecoder().decode(Uint8Array.from(bin, (c) => c.charCodeAt(0)));
}

export const encodeToken = (session: Session) => `mock.${b64urlEncode(JSON.stringify(session))}`;

/** null = no token (the Judge); "invalid" = a token we didn't issue (fail closed). */
export function decodeToken(header: string | null): Session | null | "invalid" {
  if (!header) return null;
  const m = header.match(/^Bearer\s+(.+)$/i);
  if (!m) return "invalid";
  const token = m[1].trim();
  if (!token.startsWith("mock.")) return "invalid";
  try {
    const s = JSON.parse(b64urlDecode(token.slice(5))) as Partial<Session>;
    if (!s.role || !ROLES.includes(s.role) || typeof s.principal !== "string") return "invalid";
    return { principal: s.principal, role: s.role, name: s.name ?? ROLE_NAME[s.role], issued_at: s.issued_at ?? S().knownAt };
  } catch {
    return "invalid";
  }
}

export const judgeSession = (): Session => ({ principal: "judge", role: "judge", name: "Judge", issued_at: S().knownAt });

// ---------- reads ----------
function cfo(s: MockState): CfoMetrics {
  const ctx = ctxOf(s);
  const hero = specOf(s, HERO_FLIGHT);
  const eowyn = stormById(s, EOWYN_ID);
  if (!hero || !eowyn) throw new Error("hero storm missing");
  const d = decide(hero.storm, hero.spec, ctx);
  const recoded = eowyn.flights.filter((spec) => decide(eowyn, spec, ctx)?.recoded);
  const est = estimateFor(s, COHORT_LH);
  const bridge = ["2025-01", "2025-02"].flatMap((p) => rollforward(s.journal, p, (c) => cohortEntitlement(s, c)).rows.filter((r) => r.cohort === COHORT_LH));
  return cfoMetrics({
    as_of: s.knownAt,
    entries: s.journal,
    fullEntitlement: fullEntitlementCents(hero.spec, d, ctx),
    drafted: liabilityCents(hero.spec, d, ctx),
    heldForLegal: stormMoney(eowyn, ctx).held_for_legal_cents,
    recodes: { count: recoded.length, cents: recoded.reduce((sum, spec) => sum + liabilityCents(spec, decide(eowyn, spec, ctx), ctx), 0) },
    estimate: est ?? estimateCard(s.journal, { cohort: COHORT_LH, segment: "long_haul_gt3500", pax: 172, entitlement: 9_900_000, monthsDeveloped: 1, expectedToDatePct: 0.09 }),
    bridge,
  });
}

export function estimateFor(s: MockState, cohort: string) {
  if (cohort === COHORT_LH) return estimateCard(s.journal, { cohort, segment: "long_haul_gt3500", pax: 172, entitlement: cohortEntitlement(s, cohort), monthsDeveloped: 1, expectedToDatePct: 0.09 });
  if (cohort === COHORT_ISHA) return estimateCard(s.journal, { cohort, segment: "long_haul_gt3500", pax: 100, entitlement: 6_000_000, monthsDeveloped: 12, expectedToDatePct: 0.29 });
  return null;
}

type Route = { method: "GET" | "POST"; path: string; run: (req: Req, params: Record<string, string>) => Reply };

const routes: Route[] = [
  { method: "GET", path: "/health", run: () => ok({ ok: true, mode: "mock", impl: { world: "mock", engine: "mock", books: "mock", reader: "mock", drafter: "mock" } }) },
  { method: "GET", path: "/storms", run: () => ok(stormSummaries(S())) },
  {
    method: "GET",
    path: "/storms/:id",
    run: (req, p) => {
      const storm = stormById(S(), p.id);
      return storm ? ok(stormRun(S(), storm, req.role)) : fail(404, "not_found", `No storm run ${p.id}.`);
    },
  },
  {
    method: "GET",
    path: "/flights/:id",
    run: (req, p) => {
      const file = flightFile(S(), p.id, req.role);
      return file ? ok(file) : fail(404, "not_found", `No flight ${p.id}.`);
    },
  },
  {
    method: "GET",
    path: "/questions",
    run: (req) => {
      // As the contract stub: no status means every question; "open" also returns reminded (both unanswered).
      const status = req.query.get("status") ?? "all";
      if (!["open", "answered", "reminded", "all"].includes(status)) return fail(422, "validation", "status must be open, answered or reminded.");
      const s = S();
      const role = req.role;
      const visible = s.questions.filter((q) => (role === "cfo" || role === "judge" ? true : q.routed_to === role));
      const byStatus = visible.filter((q) => status === "all" || (status === "answered" ? q.status === "answered" : status === "reminded" ? q.status === "reminded" : q.status !== "answered"));
      return ok(byStatus.map((q) => publicQuestion(s, q, role)));
    },
  },
  { method: "GET", path: "/rules", run: () => ok(rulesView(S())) },
  {
    method: "GET",
    path: "/trace",
    run: (req) => {
      const since = Number(req.query.get("since") ?? 0);
      if (!Number.isFinite(since)) return fail(422, "validation", "since must be a sequence number.");
      return ok(S().trace.filter((e) => e.seq > since));
    },
  },
  { method: "GET", path: "/books/cfo", run: () => ok(cfo(S())) },
  { method: "GET", path: "/airports", run: () => ok(AIRPORTS) },
  { method: "GET", path: "/clock", run: () => ok({ known_at: S().knownAt }) },
  {
    method: "POST",
    path: "/session",
    run: (req) => {
      const b = (req.body ?? {}) as { role?: string; name?: string };
      if (!b.role || !ROLES.includes(b.role as Role)) return fail(422, "validation", `role must be one of ${PEOPLE.join(", ")}.`);
      const role = b.role as Role;
      const name = typeof b.name === "string" && b.name.trim() ? b.name.trim().slice(0, 80) : ROLE_NAME[role];
      const session: Session = { principal: role, role, name, issued_at: S().knownAt };
      return ok({ token: encodeToken(session), session });
    },
  },
  // ---------- trace, books, access, proof (reads) ----------
  {
    method: "GET",
    path: "/commits",
    run: (req) => {
      const limit = Number(req.query.get("limit") ?? 100);
      if (!Number.isInteger(limit) || limit < 1 || limit > 5000) return fail(422, "validation", "limit must be a whole number from 1 to 5000.");
      return ok(newestCommits(S(), limit));
    },
  },
  {
    method: "GET",
    path: "/blame",
    run: (req) => {
      const target = req.query.get("target") ?? "";
      if (!target) return fail(422, "validation", "Name what to blame: ?target=NS31@2025-01-24, a coupon, a JE or a rule.");
      const b = blame(S(), target);
      return b ? ok(b) : fail(404, "not_found", `Nothing to blame for ${target}.`);
    },
  },
  {
    method: "GET",
    path: "/audit/:id",
    run: (_req, p) => {
      const a = audit(S(), p.id);
      return a ? ok(a) : fail(404, "not_found", `No journal entry ${p.id}.`);
    },
  },
  {
    method: "GET",
    path: "/books/rollforward",
    run: (req) => {
      const s = S();
      const period = req.query.get("period") ?? latestPeriod(s);
      if (!/^\d{4}-(0[1-9]|1[0-2])$/.test(period)) return fail(422, "validation", "period must look like 2025-02.");
      return ok(rollforward(s.journal, period, (c) => cohortEntitlement(s, c)));
    },
  },
  {
    method: "GET",
    path: "/books/estimate",
    run: (req) => {
      const cohort = req.query.get("cohort") ?? COHORT_LH;
      const card = estimateFor(S(), cohort);
      return card ? ok(card) : fail(404, "not_found", `No estimate card for ${cohort}. Try ${COHORT_LH} or ${COHORT_ISHA}.`);
    },
  },
  {
    method: "GET",
    path: "/books/journal",
    run: (req) => {
      const period = req.query.get("period");
      const status = req.query.get("status");
      if (status && !["draft", "approved", "posted"].includes(status)) return fail(422, "validation", "status must be draft, approved or posted.");
      if (period && !/^\d{4}-(0[1-9]|1[0-2])$/.test(period)) return fail(422, "validation", "period must look like 2025-02.");
      const rows = S().journal.filter((e) => (!period || e.period === period) && (!status || e.status === status));
      return ok([...rows].sort((a, b) => a.event_date.localeCompare(b.event_date) || a.id.localeCompare(b.id)));
    },
  },
  {
    method: "GET",
    path: "/books/curve",
    run: (req) => {
      const segment = (req.query.get("segment") ?? "long_haul_gt3500") as CurveSegment;
      return CURVES[segment] ? ok(CURVES[segment]) : fail(422, "validation", "segment must be long_haul_gt3500, medium_1500_3500 or short_le1500.");
    },
  },
  {
    method: "GET",
    path: "/books/invariants",
    run: () => {
      const s = S();
      const eowyn = stormById(s, EOWYN_ID);
      const flights = eowyn?.flights ?? [];
      const rf = rollforward(s.journal, latestPeriod(s), (c) => cohortEntitlement(s, c));
      return ok(invariants({ entries: s.journal, locked: s.locked, lockedWrites: s.lockedWrites, rf, scheduled: flights.length, operated: flights.filter((f) => f.flight.status === "operated").length, cancelled: flights.filter((f) => f.flight.status === "cancelled").length }));
    },
  },
  { method: "GET", path: "/access/matrix", run: () => ok(accessMatrix()) },
  { method: "GET", path: "/access/log", run: () => ok([...S().accessLog].sort((a, b) => b.at.localeCompare(a.at))) },
  { method: "GET", path: "/controls", run: () => ok(CONTROLS) },
  { method: "GET", path: "/injections", run: () => ok(INJECTIONS) },
  { method: "GET", path: "/eval", run: () => ok(EVAL_REPORT) },
  {
    method: "GET",
    path: "/stream",
    run: () => ok({ error: { code: "not_found", message: "In mock mode the stream comes from createMockStream(); poll /trace?since= otherwise." } }, 404),
  },

  // ---------- writes ----------
  { method: "POST", path: "/flights/:id/challenge", run: (req, p) => challenge(req, p.id) },
  { method: "POST", path: "/questions/:id/answer", run: (req, p) => answerQuestion(req, p.id) },
  { method: "POST", path: "/proposals/:id/confirm", run: (req, p) => confirmProposal(req, p.id) },
  { method: "POST", path: "/rules/:id/reject", run: (req, p) => rejectRule(req, p.id) },
  { method: "POST", path: "/rules/:id/widen", run: (req, p) => widenRule(req, p.id) },
  { method: "POST", path: "/rules/:id/revert", run: (req, p) => revertRule(req, p.id) },
  { method: "POST", path: "/books/journal/:id/approve", run: (req, p) => approveJournal(req, p.id) },
  {
    method: "POST",
    path: "/books/month-end",
    run: (req) => {
      const s = S();
      return monthEnd(req, () => estimateFor(s, COHORT_LH), (c) => cohortEntitlement(s, c));
    },
  },
  { method: "POST", path: "/books/lock", run: (req) => lockPeriod(req) },
  { method: "POST", path: "/desk", run: (req) => deskRun(req) },
  { method: "POST", path: "/inject", run: (req) => inject(req) },
  { method: "POST", path: "/clock", run: (req) => setClock(req) },
  {
    method: "POST",
    path: "/reset",
    run: () => {
      resetState();
      return ok({ ok: true });
    },
  },
];

/** The latest period with journal activity (the Feb close in the baseline). */
function latestPeriod(s: MockState) {
  return s.journal.reduce((max, e) => (e.period > max ? e.period : max), "2025-01");
}

function match(pattern: string, segs: string[]): Record<string, string> | null {
  const parts = pattern.split("/").filter(Boolean);
  if (parts.length !== segs.length) return null;
  const params: Record<string, string> = {};
  for (let i = 0; i < parts.length; i++) {
    if (parts[i].startsWith(":")) params[parts[i].slice(1)] = segs[i];
    else if (parts[i] !== segs[i]) return null;
  }
  return params;
}

export function route(req: Req): Reply {
  const candidates = routes.map((r) => ({ r, params: match(r.path, req.segs) })).filter((x) => x.params);
  if (!candidates.length) return fail(404, "not_found", `No route /${req.segs.join("/")}.`);
  const hit = candidates.find((x) => x.r.method === req.method);
  if (!hit) return fail(404, "not_found", `${req.method} isn't served on /${req.segs.join("/")}.`);
  return hit.r.run(req, hit.params ?? {});
}
