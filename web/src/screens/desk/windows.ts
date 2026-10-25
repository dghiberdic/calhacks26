import type { StormWindow } from "@/api/types";
import { zulu, zuluDay } from "@/lib/format";

export const isOutage = (w: StormWindow) => w.kind === "grid_outage";

/** "02:30Z–15:00Z", with the day on either end that isn't the run's own. */
export function windowSpan(w: StormWindow, runDate: string) {
  const sameDay = (iso: string) => iso.slice(0, 10) === runDate;
  const a = sameDay(w.start) ? zulu(w.start) : zuluDay(w.start);
  const b = sameDay(w.end) ? zulu(w.end) : zuluDay(w.end);
  return `${a}–${b}`;
}

/** A window as its chip says it: a storm by its gusts, a grid outage by its own label, never by wind. */
export function windowChip(w: StormWindow, runDate: string) {
  if (isOutage(w)) return { outage: true, text: `${w.label || "Grid outage"} ${windowSpan(w, runDate)}`, title: w.label ?? undefined };
  return { outage: false, text: `storm window ${windowSpan(w, runDate)} · peak gust ${w.peak_gust_kt} kt${w.obs_count ? ` · ${w.obs_count} obs` : ""}`, title: w.definition };
}
