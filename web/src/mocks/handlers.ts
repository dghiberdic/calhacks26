// The mock router: every route in CONTRACTS §3, answered from state.ts. Paths arrive as the API client
// sends them (after `/api`, segments URI-encoded, query string attached). Errors use the contract
// envelope {"error":{"code","message"}} with plain messages; user input never produces a 500.
import type { CfoMetrics, Role, Session } from "@/api/types";
import { AIRPORTS } from "./data/airports";
import { cfoMetrics, COHORT_ISHA, COHORT_LH, estimateCard, rollforward } from "./data/books";
import { decide, fullEntitlementCents, HERO_FLIGHT, liabilityCents, stormMoney } from "./data/engine";
import { EOWYN_ID } from "./data/flights";
import { cohortEntitlement, ctxOf, flightFile, publicQuestion, rulesView, S, specOf, stormById, stormRun, stormSummaries, type MockState } from "./state";

export type Reply = { status: number; body: unknown };
export type Req = { method: string; segs: string[]; query: URLSearchParams; body: unknown; session: Session; role: Role };

export const ok = (body: unknown, status = 200): Reply => ({ status, body });
export const fail = (status: number, code: string, message: string): Reply => ({ status, body: { error: { code, message } } });

export const PEOPLE: Role[] = ["claims_lead", "legal", "controller", "ops", "cfo", "judge"];
export const ROLES: Role[] = [...PEOPLE, "agent.reader", "agent.drafter", "agent.engine", "agent.crm_bot"];
export const ROLE_NAME: Record<Role, string> = {
  claims_lead: "Claims Lead",
  legal: "Legal",
  controller: "Controller",
  ops: "Ops",
  cfo: "CFO",
  judge: "Judge",
  "agent.reader": "Reader agent",
  "agent.drafter": "Drafter agent",
  "agent.engine": "Engine",
  "agent.crm_bot": "CRM bot",
};

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
      const status = req.query.get("status") ?? "open";
      if (!["open", "answered", "all"].includes(status)) return fail(422, "validation", "status must be open, answered or all.");
      const s = S();
      const role = req.role;
      const visible = s.questions.filter((q) => (role === "cfo" || role === "judge" ? true : q.routed_to === role));
      const byStatus = visible.filter((q) => status === "all" || (status === "answered" ? q.status === "answered" : q.status !== "answered"));
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
];

export function addRoutes(more: Route[]) {
  routes.push(...more);
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
