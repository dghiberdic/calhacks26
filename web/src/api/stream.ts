import { useEffect } from "react";
import { create } from "zustand";
import { api, apiMode } from "./client";
import { queryClient } from "./queries";
import type { TraceEvent } from "./types";

export type StreamStatus = "connecting" | "live" | "polling" | "offline";

type LiveFeed = {
  events: TraceEvent[];
  lastSeq: number;
  status: StreamStatus;
  add: (events: TraceEvent[]) => void;
  setStatus: (status: StreamStatus) => void;
};

/** Every trace event seen this session, newest last, de-duplicated by seq. */
export const useLiveFeed = create<LiveFeed>((set) => ({
  events: [],
  lastSeq: 0,
  status: "connecting",
  add: (incoming) =>
    set((s) => {
      const fresh = incoming.filter((e) => e.seq > s.lastSeq);
      if (!fresh.length) return s;
      const events = [...s.events, ...fresh].slice(-400);
      return { events, lastSeq: Math.max(s.lastSeq, ...fresh.map((e) => e.seq)) };
    }),
  setStatus: (status) => set({ status }),
}));

/** Merge a screen's initial feed (e.g. StormRun.feed) with what streamed in since, newest first. */
export function mergeFeed(initial: TraceEvent[], live: TraceEvent[]) {
  const bySeq = new Map<number, TraceEvent>();
  for (const e of initial) bySeq.set(e.seq, e);
  for (const e of live) bySeq.set(e.seq, e);
  return [...bySeq.values()].sort((a, b) => b.seq - a.seq);
}

// A burst of events (a ruling settling 31 cases) should cause one refetch, not 31.
let pending: number | undefined;
function invalidateSoon() {
  if (pending) return;
  pending = window.setTimeout(() => {
    pending = undefined;
    void queryClient.invalidateQueries({ predicate: (q) => !["health", "injections", "controls"].includes(String(q.queryKey[0])) });
  }, 350);
}

/**
 * Mounted once by the shell. `EventSource('/api/stream')` resumes by itself (the browser sends
 * Last-Event-ID); after three failed reconnects it falls back to polling `/api/trace?since=seq`
 * every 2 s, as CONTRACTS §3 allows. Mock mode replays the mock world's events instead.
 */
export function useStreamConnection() {
  useEffect(() => {
    const { add, setStatus } = useLiveFeed.getState();
    const mode = apiMode();
    let stopped = false;
    let source: EventSource | undefined;
    let poll: number | undefined;
    let unsubscribe: (() => void) | undefined;

    const receive = (events: TraceEvent[]) => {
      if (stopped || !events.length) return;
      add(events);
      if (events.some((e) => e.kind !== "info")) invalidateSoon();
    };

    const startPolling = () => {
      if (poll) return;
      setStatus("polling");
      const tick = async () => {
        try {
          const events = await api.trace(useLiveFeed.getState().lastSeq);
          receive(events);
          if (useLiveFeed.getState().status === "offline") setStatus("polling");
        } catch {
          setStatus("offline");
        }
      };
      void tick();
      poll = window.setInterval(tick, 2000);
    };

    if (mode === "mock") {
      void import("@/mocks").then((m) => {
        if (stopped) return;
        unsubscribe = m.createMockStream((event) => receive([event]), useLiveFeed.getState().lastSeq);
        setStatus("live");
      });
    } else if (mode === "recorded" || typeof EventSource === "undefined") {
      startPolling();
    } else {
      let failures = 0;
      source = new EventSource("/api/stream");
      source.onopen = () => {
        failures = 0;
        setStatus("live");
      };
      source.addEventListener("trace", (msg) => {
        try {
          receive([JSON.parse((msg as MessageEvent<string>).data) as TraceEvent]);
        } catch {
          /* a malformed event is skipped, never fatal */
        }
      });
      source.onerror = () => {
        failures += 1;
        setStatus("connecting");
        if (failures >= 3) {
          source?.close();
          startPolling();
        }
      };
    }

    return () => {
      stopped = true;
      source?.close();
      if (poll) window.clearInterval(poll);
      unsubscribe?.();
    };
  }, []);
}
