// Placeholder: replaced by the full mock world (J0b). The real module serves every route in CONTRACTS §3.
import type { ApiFetch } from "@/api/client";
import type { TraceEvent } from "@/api/types";

export function createMockFetch(): ApiFetch {
  return async () => new Response(JSON.stringify({ error: { code: "upstream", message: "Mocks not loaded yet." } }), { status: 501 });
}

/** Replays trace events like the stub's SSE (one every 2 s). Returns an unsubscribe function. */
export function createMockStream(onEvent: (event: TraceEvent) => void, lastSeq = 0): () => void {
  void onEvent;
  void lastSeq;
  return () => {};
}
