import { useState } from "react";
import { Clock3 } from "lucide-react";
import { toast } from "sonner";
import { create } from "zustand";
import { ApiError, api } from "@/api/client";
import { invalidateAfterWrite, qk, queryClient, useServerClock } from "@/api/queries";
import { Popover, PopoverContent, PopoverTrigger } from "@/components/ui/popover";
import { zuluDay } from "@/lib/format";
import { cn } from "@/lib/utils";

/** Moments the demo moves through. The server clock is forward-only, so earlier ones disable once passed. */
export const MOMENTS: { at: string; label: string; note: string }[] = [
  { at: "2025-01-24T05:12:00Z", label: "OCC cancel list", note: "All 27 coded weather" },
  { at: "2025-01-25T09:00:00Z", label: "The morning after", note: "Storm run done" },
  { at: "2025-01-26T13:00:00Z", label: "Storm Herminia", note: "Same ruling, next storm" },
  { at: "2025-01-31T23:59:00Z", label: "January close", note: "6 claims approved" },
  { at: "2025-02-28T23:59:00Z", label: "February month-end", note: "Bornhuetter-Ferguson true-up" },
];

type ClockState = { knownAt: string | null; setKnownAt: (at: string | null) => void };
/** What this tab last set, for servers without GET /clock; the server's answer wins when there is one. */
export const useClock = create<ClockState>((set) => ({ knownAt: null, setKnownAt: (knownAt) => set({ knownAt }) }));

/** POST /api/clock. One injected clock drives every decision, so this is the whole time machine. */
export function TimeScrubber({ className }: { className?: string }) {
  const { knownAt: local, setKnownAt } = useClock();
  const server = useServerClock();
  const knownAt = server.data?.known_at ?? local;
  const [open, setOpen] = useState(false);
  const [custom, setCustom] = useState("");
  const [busy, setBusy] = useState(false);

  const move = async (at: string) => {
    setBusy(true);
    try {
      const res = await api.clock(at);
      setKnownAt(res.known_at);
      queryClient.setQueryData(qk.clock, res);
      await invalidateAfterWrite();
      toast(`Known at ${zuluDay(res.known_at)}`, { description: "Every screen now shows what StormCheck knew then." });
      setOpen(false);
    } catch (e) {
      toast.error(e instanceof ApiError ? e.message : "The clock didn't move.");
    } finally {
      setBusy(false);
    }
  };

  const passed = (at: string) => !!knownAt && new Date(at).getTime() < new Date(knownAt).getTime();

  return (
    <Popover open={open} onOpenChange={setOpen}>
      <PopoverTrigger
        className={cn("inline-flex h-9 items-center gap-2 rounded-full bg-white px-3 text-[13px] text-navy-900 shadow-[inset_0_0_0_1px_var(--color-cloud-200)] hover:bg-cloud-50", className)}
        aria-label="Known-at time"
        data-testid="time-scrubber"
      >
        <Clock3 className="size-3.5 text-slate-400" aria-hidden="true" />
        <span className="font-mono text-[12px] tabular-nums">{knownAt ? zuluDay(knownAt) : "server clock"}</span>
      </PopoverTrigger>
      <PopoverContent align="end" className="w-[320px] p-2">
        <p className="micro px-2 pb-1 pt-1 text-slate-400">Known at</p>
        <ul className="flex flex-col">
          {MOMENTS.map((m) => (
            <li key={m.at}>
              <button
                type="button"
                disabled={busy || passed(m.at)}
                onClick={() => void move(m.at)}
                className="flex w-full items-center justify-between gap-3 rounded-lg px-2 py-2 text-left hover:bg-cloud-50 disabled:cursor-not-allowed disabled:opacity-40"
              >
                <span>
                  <span className="block text-[13.5px] text-navy-900">{m.label}</span>
                  <span className="block text-[12px] text-slate-500">{m.note}</span>
                </span>
                <span className="font-mono text-[11.5px] text-slate-500">{zuluDay(m.at)}</span>
              </button>
            </li>
          ))}
        </ul>
        <form
          className="mt-1 flex items-center gap-2 border-t border-cloud-100 px-2 pt-2.5 pb-1"
          onSubmit={(e) => {
            e.preventDefault();
            if (custom) void move(new Date(`${custom}Z`).toISOString().replace(".000", ""));
          }}
        >
          <label className="sr-only" htmlFor="known-at">
            Custom time (UTC)
          </label>
          <input
            id="known-at"
            type="datetime-local"
            value={custom}
            onChange={(e) => setCustom(e.target.value)}
            className="h-8 min-w-0 flex-1 rounded-md bg-cloud-50 px-2 font-mono text-[12px] outline-none ring-cloud-300 focus:ring-2"
          />
          <button type="submit" disabled={!custom || busy} className="h-8 rounded-md bg-navy-900 px-3 text-[12.5px] font-semibold text-cloud-50 disabled:opacity-40">
            Go
          </button>
        </form>
        <p className="px-2 pb-1 pt-2 text-[11.5px] leading-snug text-slate-400">The clock only moves forward. Locked periods are never rewritten.</p>
      </PopoverContent>
    </Popover>
  );
}
