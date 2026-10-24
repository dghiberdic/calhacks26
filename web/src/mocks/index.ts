// The mock API world (J0b): every route in CONTRACTS §3, typed from @/api/types, built from the real
// EIDW METAR (Éowyn, Herminia) and the numbers in IMPLEMENTATION_PLAN.md §1. Stateful and in-memory;
// POST /reset (or resetMockWorld) restores the baseline.
//
// Judgment calls (also in the J0b commit message):
// - Clock vs books: decisions are known_at 25 Jan 06:00Z and the clock starts at 25 Jan 09:00Z (Q1 has
//   waited 3 h, so its reminder shows after a reset), but the books are shown as at the Feb close (Jan
//   locked, Feb month end drafted) so every golden number is visible without scrubbing. Approving a
//   parked draft in a locked period is allowed (it is an approval, not a new entry); new entries and
//   adjustments land in the first open period, so a ruling's change in estimate goes to Feb.
// - The Feb month-end change in estimate (+399,000) and the care-invoice true-up were prepared by the
//   Controller, so approving them as the Controller is the SoD demo (403); the CFO can approve them.
// - Principals are the role itself ("controller", "agent.drafter"): one person per seat in this world.
// - Overnight inbounds use the local departure date in their ids (NS20@2025-01-23), per Flight.date.
// - `aircraft` is the registration (as in the contract tests); the type is in the schedule-line quotes.
// - The mined rule is R-MIN-1 (as asked); THREAD_DAVID calls it R-MINED-REDUCE. Regulation cards are
//   REG-ART5-3-WEATHER, REG-C549-TECHNICAL and the static REG-2026-2202; hard controls are HC-*.
// - StormWindow.obs_count counts the qualifying obs (24 main, 2 minor on Éowyn), not every obs inside.
// - Foreign stations have no METAR in the mock: their end is "out" (calm), never fabricated METAR.
// - Herminia: 3 weather cancellations in its 11:30–13:00Z window, NS112 DUB–LIS miscoded 71 (AOG, owed,
//   31 unsigned in-lieu vouchers) and NS30 BOS→DUB technical (1 voucher). Before R-CL-1 the 32 cases are
//   held under Q1's pattern; after it, 31 settle (cited) and the BOS→DUB case asks again (Q-6).
// - Herminia is not in the books (the plan's books cover Éowyn and the Isha opening balance).
// - Operated flights get a placeholder FlightDecision (cause "unknown", score null): key off flight.status.
// - Additive fields the UI asked for (contracts/requests/justin.md): Question.others_settled,
//   real_context.name, entitlements_summary keys, GET /airports and GET /clock.
import type { ApiFetch } from "@/api/client";
import type { Role, TraceEvent } from "@/api/types";
import { decodeToken, fail, judgeSession, route, type Reply } from "./handlers";
import { emit, onEvent, resetState, S } from "./state";

export type MockFetchOptions = {
  /** Random latency range in ms so loading states show; [0, 0] in tests. */
  latencyMs?: [number, number];
};

const json = (r: Reply) => new Response(JSON.stringify(r.body), { status: r.status, headers: { "Content-Type": "application/json" } });

function header(init: RequestInit, name: string): string | null {
  const h = init.headers;
  if (!h) return null;
  if (h instanceof Headers) return h.get(name);
  if (Array.isArray(h)) return h.find(([k]) => k.toLowerCase() === name.toLowerCase())?.[1] ?? null;
  const rec = h as Record<string, string>;
  const key = Object.keys(rec).find((k) => k.toLowerCase() === name.toLowerCase());
  return key ? rec[key] : null;
}

function handle(path: string, init: RequestInit): Reply {
  const method = (init.method ?? "GET").toUpperCase();
  const [rawPath, rawQuery = ""] = path.split("?");
  const clean = rawPath.replace(/^\/api(?=\/)/, "");
  let segs: string[];
  try {
    segs = clean.split("/").filter(Boolean).map((p) => decodeURIComponent(p));
  } catch {
    return fail(404, "not_found", "That address isn't a StormCheck route.");
  }
  const session = decodeToken(header(init, "Authorization"));
  if (session === "invalid") return fail(403, "forbidden", "That session token isn't valid here. Pick a role again.");
  let body: unknown = undefined;
  if (typeof init.body === "string" && init.body.length) {
    try {
      body = JSON.parse(init.body);
    } catch {
      return fail(422, "validation", "The request body isn't valid JSON.");
    }
  }
  const s = session ?? judgeSession();
  try {
    return route({ method, segs, query: new URLSearchParams(rawQuery), body, session: s, role: s.role as Role });
  } catch (e) {
    // Never a 500 for user input: anything unexpected is a plain, non-technical answer.
    console.error("[mocks]", e);
    return fail(422, "validation", "StormCheck couldn't use that input. Nothing was changed.");
  }
}

/** Serves every route in CONTRACTS §3 from the in-memory mock world. */
export function createMockFetch(options: MockFetchOptions = {}): ApiFetch {
  const [lo, hi] = options.latencyMs ?? [120, 350];
  return async (path, init) => {
    const reply = handle(path, init ?? {});
    const wait = lo + Math.random() * Math.max(0, hi - lo);
    if (wait > 0) await new Promise((r) => setTimeout(r, wait));
    return json(reply);
  };
}

const AMBIENT: Omit<TraceEvent, "seq" | "at">[] = [
  { kind: "info", actor: "agent.engine", summary: "Verified the commit chain · replay identical", ref: null, chip: "INFO", amount_cents: null },
  { kind: "fact", actor: "agent.reader", summary: "Read 1 new NS31 claim email · queued for the Claims Lead's assessment", ref: "NS31@2025-01-24", chip: "INFO", amount_cents: null },
  { kind: "info", actor: "agent.engine", summary: "Invariants re-checked · 2140 ties to GL · 2125 refund clearing = 0", ref: null, chip: "INFO", amount_cents: null },
];

/**
 * Like the stub's SSE: replays the trace after `lastSeq`, one event every ~2 s, then streams new events
 * as the mock world writes them, plus an occasional ambient one. Returns an unsubscribe function.
 */
export function createMockStream(onEventCb: (event: TraceEvent) => void, lastSeq = 0): () => void {
  let cursor = lastSeq;
  const queue: TraceEvent[] = S().trace.filter((e) => e.seq > cursor);
  const off = onEvent((e) => queue.push(e));
  let ambientAt = Date.now() + 25_000 + Math.random() * 15_000;
  let ambientIdx = 0;
  const timer = setInterval(() => {
    const next = queue.shift();
    if (next) {
      if (next.seq > cursor) {
        cursor = next.seq;
        onEventCb(next);
      }
      return;
    }
    if (Date.now() >= ambientAt) {
      ambientAt = Date.now() + 25_000 + Math.random() * 15_000;
      emit(S(), { ...AMBIENT[ambientIdx++ % AMBIENT.length] }, null);
    }
  }, 2000);
  return () => {
    clearInterval(timer);
    off();
  };
}

/** Restore the baseline world (what POST /reset does). */
export function resetMockWorld(): void {
  resetState();
}
