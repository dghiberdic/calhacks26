import { QueryClient, useQuery } from "@tanstack/react-query";
import { useSession } from "@/app/session";
import { ApiError, api } from "./client";
import type { CurveSegment } from "./types";

export const queryClient = new QueryClient({
  defaultOptions: {
    queries: {
      staleTime: 20_000,
      refetchOnWindowFocus: false,
      // 4xx are answers, not outages: don't hammer the server with them.
      retry: (failures, error) => !(error instanceof ApiError && error.status >= 400 && error.status < 500) && failures < 2,
    },
  },
});

/** Query keys, grouped so a trace event can invalidate exactly what it changed. */
export const qk = {
  storms: ["storms"] as const,
  storm: (id: string) => ["storms", id] as const,
  flight: (id: string) => ["flights", id] as const,
  questions: (role: string, status: string) => ["questions", role, status] as const,
  rules: ["rules"] as const,
  trace: ["trace"] as const,
  commits: (limit: number) => ["commits", limit] as const,
  blame: (target: string) => ["blame", target] as const,
  audit: (je: string) => ["books", "audit", je] as const,
  rollforward: (period: string) => ["books", "rollforward", period] as const,
  estimate: (cohort: string) => ["books", "estimate", cohort] as const,
  journal: (period?: string, status?: string) => ["books", "journal", period ?? "", status ?? ""] as const,
  curve: (segment: string) => ["books", "curve", segment] as const,
  cfo: ["books", "cfo"] as const,
  invariants: ["books", "invariants"] as const,
  accessMatrix: ["access", "matrix"] as const,
  accessLog: ["access", "log"] as const,
  controls: ["controls"] as const,
  injections: ["injections"] as const,
  evalReport: ["eval"] as const,
  health: ["health"] as const,
  clock: ["clock"] as const,
  airports: ["airports"] as const,
};

/** The World's airports (GET /airports, additive). Static per run; a server without it 404s and callers fall back. */
export const useAirports = () => useQuery({ queryKey: qk.airports, queryFn: api.airports, retry: false, staleTime: Infinity });
/** The server's known-at (GET /clock, additive). A server without it answers 404 and the scrubber says "server clock". */
export const useServerClock = () => useQuery({ queryKey: qk.clock, queryFn: api.clockNow, retry: false, staleTime: 30_000 });
export const useHealth = () => useQuery({ queryKey: qk.health, queryFn: api.health, staleTime: 60_000, retry: false });
export const useStorms = () => useQuery({ queryKey: qk.storms, queryFn: api.storms });
export const useStormRun = (id: string | undefined) => useQuery({ queryKey: qk.storm(id ?? ""), queryFn: () => api.storm(id!), enabled: !!id });
export const useFlightFile = (id: string | undefined) => useQuery({ queryKey: qk.flight(id ?? ""), queryFn: () => api.flight(id!), enabled: !!id });

/** Questions are role-scoped and redacted server-side, so the role is part of the key. */
export function useQuestions(status: "open" | "answered" | "all" = "open") {
  const role = useSession((s) => s.role);
  return useQuery({ queryKey: qk.questions(role, status), queryFn: () => api.questions(status) });
}

export const useRules = () => useQuery({ queryKey: qk.rules, queryFn: api.rules });
export const useTrace = () => useQuery({ queryKey: qk.trace, queryFn: () => api.trace(0) });
export const useCommits = (limit = 100) => useQuery({ queryKey: qk.commits(limit), queryFn: () => api.commits(limit) });
export const useBlame = (target: string | undefined) => useQuery({ queryKey: qk.blame(target ?? ""), queryFn: () => api.blame(target!), enabled: !!target });
export const useAudit = (je: string | undefined) => useQuery({ queryKey: qk.audit(je ?? ""), queryFn: () => api.audit(je!), enabled: !!je });
export const useRollforward = (period: string) => useQuery({ queryKey: qk.rollforward(period), queryFn: () => api.rollforward(period) });
export const useEstimate = (cohort: string) => useQuery({ queryKey: qk.estimate(cohort), queryFn: () => api.estimate(cohort) });
export const useJournal = (period?: string, status?: string) => useQuery({ queryKey: qk.journal(period, status), queryFn: () => api.journal(period, status) });
export const useCurve = (segment: CurveSegment) => useQuery({ queryKey: qk.curve(segment), queryFn: () => api.curve(segment) });
export const useCfo = () => useQuery({ queryKey: qk.cfo, queryFn: api.cfo });
export const useInvariants = () => useQuery({ queryKey: qk.invariants, queryFn: api.invariants });
export const useAccessMatrix = () => useQuery({ queryKey: qk.accessMatrix, queryFn: api.accessMatrix });
export const useAccessLog = () => useQuery({ queryKey: qk.accessLog, queryFn: api.accessLog });
export const useControls = () => useQuery({ queryKey: qk.controls, queryFn: api.controls });
export const useInjections = () => useQuery({ queryKey: qk.injections, queryFn: api.injections });
export const useEvalReport = () => useQuery({ queryKey: qk.evalReport, queryFn: api.evalReport });

/** After any write: refetch everything a write can change (cheap at demo scale, never stale). */
export function invalidateAfterWrite() {
  return queryClient.invalidateQueries({ predicate: (q) => q.queryKey[0] !== "health" && q.queryKey[0] !== "injections" });
}
