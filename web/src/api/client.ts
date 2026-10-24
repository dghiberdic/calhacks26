import type {
  AccessDecision,
  Airport,
  AccessMatrix,
  AnswerRequest,
  AnswerResponse,
  ApiErrorBody,
  Blame,
  CfoMetrics,
  ChallengeResponse,
  ClaimCurve,
  Commit,
  ConfirmResponse,
  ControlMapping,
  CurveSegment,
  EstimateCard,
  EvalReport,
  FlightFile,
  Health,
  InjectRequest,
  InjectResponse,
  Injection,
  InvariantResult,
  JournalEntry,
  MonthEndResponse,
  Question,
  ReplayDiff,
  Role,
  Rollforward,
  Rule,
  RuleProposal,
  SessionResponse,
  StormRun,
  StormSummary,
  TraceEvent,
} from "./types";

/**
 * Where /api requests go. Everything above this line is the same in every mode:
 * - "http": the real server or the contract stub, through the Vite proxy (`/api` → API_TARGET).
 * - "mock": in-memory handlers typed from CONTRACTS.md (`src/mocks/`), for work before the stub exists.
 * - "recorded": the frozen responses in demo/recorded/ (J9), so the Devpost build has no backend to go down.
 * Pick with VITE_API_MODE, or `?api=mock|http|recorded` in the URL (remembered for the tab).
 */
export type ApiMode = "http" | "mock" | "recorded";

export type ApiFetch = (path: string, init: RequestInit) => Promise<Response>;

const MODE_KEY = "stormcheck.api-mode";

export function apiMode(): ApiMode {
  const valid = (m: string | null | undefined): m is ApiMode => m === "http" || m === "mock" || m === "recorded";
  if (typeof window !== "undefined") {
    const fromUrl = new URLSearchParams(window.location.search).get("api");
    if (valid(fromUrl)) {
      try {
        sessionStorage.setItem(MODE_KEY, fromUrl);
      } catch {
        /* storage can be blocked; the URL still wins for this load */
      }
      return fromUrl;
    }
    try {
      const remembered = sessionStorage.getItem(MODE_KEY);
      if (valid(remembered)) return remembered;
    } catch {
      /* ignore */
    }
  }
  // `vite --mode mock|recorded` picks the transport by itself: the repo ignores .env.* files, so a mode file can't carry it.
  const fromEnv = (import.meta.env.VITE_API_MODE as string | undefined) ?? import.meta.env.MODE;
  return valid(fromEnv) ? fromEnv : "http";
}

const httpFetch: ApiFetch = (path, init) => fetch(`/api${path}`, init);

let transport: ApiFetch = httpFetch;

/** Swap the transport (mock / recorded). Called once at startup by `src/api/boot.ts`. */
export function setTransport(next: ApiFetch) {
  transport = next;
}

// ---------- session token ----------
let token: string | null = null;
let tokenRole: Role = "judge";

export function setToken(next: string | null, role: Role = "judge") {
  token = next;
  tokenRole = role;
}
export const currentRole = () => tokenRole;

// ---------- errors ----------
export class ApiError extends Error {
  readonly status: number;
  readonly code: string;
  constructor(status: number, code: string, message: string) {
    super(message);
    this.name = "ApiError";
    this.status = status;
    this.code = code;
  }
  /** A 422 from the desk or inject carries a plain message meant for the person at the keyboard. */
  get isUserFacing() {
    return this.status === 422 || this.status === 403 || this.status === 404;
  }
}

type Query = Record<string, string | number | boolean | null | undefined>;

function withQuery(path: string, query?: Query) {
  if (!query) return path;
  const params = new URLSearchParams();
  for (const [k, v] of Object.entries(query)) if (v !== undefined && v !== null && v !== "") params.set(k, String(v));
  const qs = params.toString();
  return qs ? `${path}?${qs}` : path;
}

async function request<T>(method: "GET" | "POST", path: string, opts: { query?: Query; body?: unknown } = {}): Promise<T> {
  const headers: Record<string, string> = { Accept: "application/json" };
  if (opts.body !== undefined) headers["Content-Type"] = "application/json";
  if (token) headers.Authorization = `Bearer ${token}`;
  let res: Response;
  try {
    res = await transport(withQuery(path, opts.query), { method, headers, body: opts.body === undefined ? undefined : JSON.stringify(opts.body) });
  } catch {
    throw new ApiError(0, "network", "Can't reach the StormCheck server.");
  }
  if (res.ok) {
    if (res.status === 204) return undefined as T;
    return (await res.json()) as T;
  }
  let body: Partial<ApiErrorBody> | null = null;
  try {
    body = (await res.json()) as ApiErrorBody;
  } catch {
    /* not JSON */
  }
  const code = body?.error?.code ?? (res.status === 422 ? "validation" : "upstream");
  const message = body?.error?.message ?? (res.status >= 500 ? "The server had a problem. Nothing was changed." : res.statusText || "Request failed.");
  throw new ApiError(res.status, code, message);
}

const get = <T>(path: string, query?: Query) => request<T>("GET", path, { query });
const post = <T>(path: string, body?: unknown) => request<T>("POST", path, { body });
const seg = (id: string) => encodeURIComponent(id);

/** Every route in CONTRACTS §3, one typed function each. */
export const api = {
  health: () => get<Health>("/health"),
  storms: () => get<StormSummary[]>("/storms"),
  storm: (id: string) => get<StormRun>(`/storms/${seg(id)}`),
  flight: (id: string) => get<FlightFile>(`/flights/${seg(id)}`),
  /** "all" is the route without a status (CONTRACTS §3 names only ?status=open; the stub filters on any value). */
  questions: (status: "open" | "answered" | "all" = "open") => get<Question[]>("/questions", status === "all" ? {} : { status }),
  rules: () => get<Rule[]>("/rules"),
  trace: (since = 0) => get<TraceEvent[]>("/trace", { since }),
  commits: (limit = 100) => get<Commit[]>("/commits", { limit }),
  blame: (target: string) => get<Blame>("/blame", { target }),
  audit: (jeId: string) => get<Record<string, unknown>>(`/audit/${seg(jeId)}`),
  rollforward: (period: string) => get<Rollforward>("/books/rollforward", { period }),
  estimate: (cohort: string) => get<EstimateCard>("/books/estimate", { cohort }),
  journal: (period?: string, status?: string) => get<JournalEntry[]>("/books/journal", { period, status }),
  curve: (segment: CurveSegment) => get<ClaimCurve>("/books/curve", { segment }),
  cfo: () => get<CfoMetrics>("/books/cfo"),
  invariants: () => get<InvariantResult[]>("/books/invariants"),
  accessMatrix: () => get<AccessMatrix>("/access/matrix"),
  accessLog: () => get<AccessDecision[]>("/access/log"),
  controls: () => get<ControlMapping[]>("/controls"),
  injections: () => get<Injection[]>("/injections"),
  evalReport: () => get<EvalReport>("/eval"),

  session: (role: Role, name: string) => post<SessionResponse>("/session", { role, name }),
  challenge: (flightId: string, text: string) => post<ChallengeResponse>(`/flights/${seg(flightId)}/challenge`, { text }),
  answer: (questionId: string, body: AnswerRequest) => post<AnswerResponse>(`/questions/${seg(questionId)}/answer`, body),
  confirm: (ruleId: string) => post<ConfirmResponse>(`/proposals/${seg(ruleId)}/confirm`),
  reject: (ruleId: string, explanation: string) => post<AnswerResponse>(`/rules/${seg(ruleId)}/reject`, { explanation }),
  widen: (ruleId: string) => post<RuleProposal>(`/rules/${seg(ruleId)}/widen`),
  revert: (ruleId: string) => post<ReplayDiff>(`/rules/${seg(ruleId)}/revert`),
  approveJournal: (jeId: string) => post<JournalEntry>(`/books/journal/${seg(jeId)}/approve`),
  monthEnd: (period: string) => post<MonthEndResponse>("/books/month-end", { period }),
  lockPeriod: (period: string) => post<{ locked: unknown }>("/books/lock", { period }),
  desk: (icao: string, date: string) => post<StormRun>("/desk", { icao, date }),
  inject: (body: InjectRequest) => post<InjectResponse>("/inject", body),
  clock: (knownAt: string) => post<{ known_at: string }>("/clock", { known_at: knownAt }),
  /** Additive (contracts/requests/justin.md #1): the World's airports; a server without it answers 404. */
  airports: () => get<Airport[]>("/airports"),
  /** Additive (contracts/requests/justin.md #2): the current known-at; absent on a server without it. */
  clockNow: () => get<{ known_at: string }>("/clock"),
  reset: () => post<{ ok: boolean }>("/reset"),
};

export type Api = typeof api;
