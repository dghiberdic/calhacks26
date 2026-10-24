import { useEffect, useState } from "react";
import { create } from "zustand";
import { ApiError, api } from "@/api/client";
import { invalidateAfterWrite } from "@/api/queries";
import { useLiveFeed } from "@/api/stream";
import type { FlightFile, InjectKind, InjectRequest, InjectResponse, StormRun } from "@/api/types";
import { useReducedMotion } from "motion/react";
import type { AirportChoice } from "./airports";
import { KINDS } from "./templates";

/** What the Flight File said about a flight at one moment (before and after an injection). */
export type FlightSnapshot = Pick<FlightFile, "decision">;

/** A flight id from any affected id ("NS31@2025-01-24:14C" → "NS31@2025-01-24"); null for anything else. */
export const flightOf = (id: string | null | undefined) => (id && /^[A-Z0-9]{2}\d{1,4}[A-Z]?@\d{4}-\d{2}-\d{2}/.test(id) ? id.split(":")[0] : null);

/** Best effort: a flight the server doesn't know (or a slow answer) is simply left out of the diff. */
async function snapshot(ids: string[], timeoutMs: number): Promise<Record<string, FlightSnapshot | null>> {
  const out: Record<string, FlightSnapshot | null> = {};
  const all = Promise.all(
    ids.map(async (id) => {
      try {
        const file = await api.flight(id);
        out[id] = file?.decision ? { decision: file.decision } : null;
      } catch {
        out[id] = null;
      }
    }),
  );
  await Promise.race([all, new Promise((r) => window.setTimeout(r, timeoutMs))]);
  return out;
}

/** A failed request said plainly, and which input it's about (so that field is marked). */
export type DeskProblem = { message: string; code: string; field?: "airport" | "date"; network?: boolean };

export function problemOf(e: unknown): DeskProblem {
  if (e instanceof ApiError) {
    const field = e.code === "unknown_airport" ? "airport" : e.code === "future_date" || e.code === "no_metar" ? "date" : undefined;
    return { message: e.message, code: e.code, field, network: e.code === "network" };
  }
  return { message: "Something went wrong on this page. Nothing was changed.", code: "client" };
}

type DayState = {
  airport: AirportChoice | null;
  airportText: string;
  date: string | null;
  dateText: string;
  pending: { icao: string; date: string } | null;
  run: StormRun | null;
  /** The inputs that produced `run` (the run itself says station + date, this keeps the label). */
  ranFor: { icao: string; date: string; airport?: AirportChoice["airport"] } | null;
  problem: DeskProblem | null;
  token: number;
};

type InjectState = {
  kind: InjectKind;
  drafts: Record<InjectKind, string>;
  flightId: string;
  pending: InjectRequest | null;
  scenarioId: string | null;
  result: {
    request: InjectRequest;
    response: InjectResponse;
    startSeq: number;
    scenarioId: string | null;
    before: Record<string, FlightSnapshot | null>;
    after: Record<string, FlightSnapshot | null> | null;
  } | null;
  problem: DeskProblem | null;
};

type DeskStore = DayState & {
  inject: InjectState;
  setAirport: (airport: AirportChoice | null, text: string) => void;
  setDate: (date: string | null, text: string) => void;
  clearProblem: () => void;
  runDay: (icao: string, date: string, airport?: AirportChoice["airport"]) => Promise<void>;
  setKind: (kind: InjectKind) => void;
  setDraft: (kind: InjectKind, text: string) => void;
  resetDraft: (kind: InjectKind) => void;
  setFlightId: (id: string) => void;
  runInject: (req: InjectRequest, scenarioId?: string | null) => Promise<void>;
};

const templates = () => Object.fromEntries(KINDS.map((k) => [k.kind, k.template])) as Record<InjectKind, string>;

export const useDesk = create<DeskStore>((set, get) => ({
  airport: null,
  airportText: "",
  date: null,
  dateText: "",
  pending: null,
  run: null,
  ranFor: null,
  problem: null,
  token: 0,
  inject: { kind: "tech_log", drafts: templates(), flightId: "", pending: null, scenarioId: null, result: null, problem: null },

  setAirport: (airport, airportText) => set((s) => ({ airport, airportText, problem: s.problem?.field === "airport" ? null : s.problem })),
  setDate: (date, dateText) => set((s) => ({ date, dateText, problem: s.problem?.field === "date" ? null : s.problem })),
  clearProblem: () => set({ problem: null }),

  async runDay(icao, date, airport) {
    const token = get().token + 1;
    set({ pending: { icao, date }, problem: null, token });
    try {
      const run = await api.desk(icao, date);
      if (get().token !== token) return; // a newer run started
      set({ run, ranFor: { icao, date, airport }, pending: null });
      void invalidateAfterWrite();
    } catch (e) {
      if (get().token !== token) return;
      set({ problem: problemOf(e), pending: null });
    }
  },

  setKind: (kind) => set((s) => ({ inject: { ...s.inject, kind, problem: null } })),
  setDraft: (kind, text) => set((s) => ({ inject: { ...s.inject, drafts: { ...s.inject.drafts, [kind]: text }, problem: null } })),
  resetDraft: (kind) => set((s) => ({ inject: { ...s.inject, drafts: { ...s.inject.drafts, [kind]: templates()[kind] } } })),
  setFlightId: (flightId) => set((s) => ({ inject: { ...s.inject, flightId } })),

  async runInject(request, scenarioId = null) {
    set((s) => ({
      inject: {
        ...s.inject,
        kind: request.kind,
        drafts: { ...s.inject.drafts, [request.kind]: request.text },
        flightId: request.flight_id ?? "",
        pending: request,
        scenarioId,
        problem: null,
      },
    }));
    try {
      const target = flightOf(request.flight_id);
      const before = target ? await snapshot([target], 1200) : {};
      if (get().inject.pending !== request) return;
      const startSeq = useLiveFeed.getState().lastSeq;
      const response = await api.inject(request);
      if (get().inject.pending !== request) return;
      set((s) => ({ inject: { ...s.inject, pending: null, result: { request, response, startSeq, scenarioId, before, after: null } } }));
      void invalidateAfterWrite();
      const ids = [...new Set(response.affected.map(flightOf).filter((x): x is string => !!x))].slice(0, 6);
      if (ids.length) {
        const after = await snapshot(ids, 4000);
        set((s) => (s.inject.result?.response === response ? { inject: { ...s.inject, result: { ...s.inject.result, after } } } : s));
      }
    } catch (e) {
      if (get().inject.pending !== request) return;
      set((s) => ({ inject: { ...s.inject, pending: null, problem: problemOf(e) } }));
    }
  },
}));

/**
 * Progress lines for a request that answers in one go: step through them on a timer and hold on the
 * last until the answer lands. They name what the server does, in order; none claims to be done.
 * Mount it per request (key) so each one starts from the first line.
 */
export function useSteps(count: number, everyMs = 900) {
  const [step, setStep] = useState(0);
  const reduce = useReducedMotion();
  useEffect(() => {
    const t = window.setInterval(() => setStep((s) => Math.min(count - 1, s + 1)), reduce ? everyMs * 1.5 : everyMs);
    return () => window.clearInterval(t);
  }, [count, everyMs, reduce]);
  return step;
}
