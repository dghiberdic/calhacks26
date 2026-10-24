import type { Flight, TimelineMark } from "@/api/types";
import { zulu, zuluDay } from "@/lib/format";
import { capitalize, markKind, markText, type MarkKey } from "./lib";

/**
 * The flight timeline strip's data and label layout, kept pure so the guarantees can be tested: labels never
 * overlap in a lane, no leader line crosses a label, and the marks that decide the case get labels first.
 */

export type Tone = ReturnType<typeof markKind>["tone"];
export type Item = { at: number; iso: string; key: MarkKey; kind: string; label: string; text: string; machine: boolean; tone: Tone };

/** Which marks earn a label first when the strip is crowded: the flight itself, then the evidence that decided it. */
export const PRIORITY: Record<MarkKey, number> = { schedule: 0, tech: 1, occ: 2, mcc: 3, crm: 4, operated: 5, metar: 6, spares: 7, pss: 8, claim: 9, other: 10, window: 11 };

/** `hub` is the storm station's airport: the end of a sector where its storm window applies. */
export function toItems(marks: TimelineMark[], flight: Flight, hub: string): Item[] {
  const items: Item[] = [];
  for (const m of marks) {
    if (!m.at) continue;
    const at = Date.parse(m.at);
    if (Number.isNaN(at)) continue;
    const k = markKind(m);
    const label = capitalize(typeof m.label === "string" && m.label ? m.label : k.label);
    const text = markText(m);
    items.push({ at, iso: m.at, key: k.key, kind: k.label, label, text: text === label ? "" : text, machine: k.machine, tone: k.tone });
  }
  if (!items.some((i) => i.tone === "flight")) {
    if (flight.origin === hub) items.push({ at: Date.parse(flight.sched_dep), iso: flight.sched_dep, key: "schedule", kind: "Schedule", label: `${flight.number} STD`, text: `Scheduled departure ${flight.origin} → ${flight.dest}`, machine: false, tone: "flight" });
    if (flight.dest === hub) items.push({ at: Date.parse(flight.sched_arr), iso: flight.sched_arr, key: "schedule", kind: "Schedule", label: `${flight.number} STA`, text: `Scheduled arrival at ${flight.dest}`, machine: false, tone: "flight" });
  }
  return items.sort((a, b) => a.at - b.at);
}

/** "05:12Z" on the flight's own day, "23 Jan 21:40Z" on any other. */
export function when(iso: string, flightDate: string) {
  return iso.slice(0, 10) === flightDate ? zulu(iso) : zuluDay(iso);
}

export const MAX_LANES = 4;
export const LABEL_MAX = 168;
const LABEL_FONT = '500 12.5px "Archivo Variable", ui-sans-serif, system-ui, sans-serif';
const META_FONT = '400 11px "Archivo Variable", ui-sans-serif, system-ui, sans-serif';

let canvas: CanvasRenderingContext2D | null | undefined;
/** Rendered text width (canvas, the page's own font); a per-character estimate where there is no canvas. */
export function textWidth(text: string, font: string) {
  if (canvas === undefined) {
    try {
      // jsdom (unit tests) has no canvas: estimate there instead of asking.
      const noCanvas = typeof document === "undefined" || (typeof navigator !== "undefined" && /jsdom/i.test(navigator.userAgent));
      canvas = noCanvas ? null : document.createElement("canvas").getContext("2d");
    } catch {
      canvas = null;
    }
  }
  if (!canvas) return text.length * 7;
  canvas.font = font;
  return canvas.measureText(text).width;
}

export type Placed = { it: Item; cx: number; cy: number; left: number; w: number; lane: number; meta: string };
type Sized = Item & { cx: number; cy: number; w: number; meta: string };

/** Would this label (or its leader line) touch one already placed? Leaders run from a label down to its mark. */
export function clashes(c: Placed, placed: Placed[], width: number) {
  if (c.left < 0 || c.left + c.w > width) return true;
  for (const p of placed) {
    if (p.lane === c.lane && c.left < p.left + p.w + 8 && c.left + c.w + 8 > p.left) return true;
    if (p.lane > c.lane && p.cx > c.left - 3 && p.cx < c.left + c.w + 3) return true; // p's leader would cross c
    if (p.lane < c.lane && c.cx > p.left - 3 && c.cx < p.left + p.w + 3) return true; // c's leader would cross p
  }
  return false;
}

/** Right to left, each label in the lowest lane that fits: clusters build a staircase whose leaders never cross. */
function staircase(items: Sized[], width: number): Placed[] | null {
  const placed: Placed[] = [];
  for (const it of [...items].sort((a, b) => b.at - a.at)) {
    let best: Placed | null = null;
    for (let lane = 0; lane < MAX_LANES && !best; lane++)
      for (const left of [it.cx - 7, it.cx + 7 - it.w]) {
        const c = { it, cx: it.cx, cy: it.cy, left, w: it.w, lane, meta: it.meta };
        if (!clashes(c, placed, width)) {
          best = c;
          break;
        }
      }
    if (!best) return null;
    placed.push(best);
  }
  return placed;
}

/**
 * Which marks get a label: the longest run of the priority order (the flight, the tech log, OCC, MCC, CRM, …)
 * that fits in the lanes without a label or leader touching another. The rest keep a tick and a tooltip.
 */
export function placeLabels<T extends Item & { cx: number; cy: number }>(items: T[], width: number, flightDate: string) {
  const sized: (T & Sized)[] = items.map((it) => {
    const meta = `${when(it.iso, flightDate)} · ${it.kind}`;
    return { ...it, meta, w: Math.min(LABEL_MAX, Math.ceil(Math.max(textWidth(it.label, LABEL_FONT), textWidth(meta, META_FONT)) * 1.04) + 14) };
  });
  const ranked = [...sized].sort((a, b) => PRIORITY[a.key] - PRIORITY[b.key] || a.at - b.at);
  for (let k = ranked.length; k > 0; k--) {
    const chosen = new Set(ranked.slice(0, k));
    const placed = staircase(sized.filter((s) => chosen.has(s)), width);
    if (placed) return { placed, unplaced: sized.filter((s) => !chosen.has(s)) };
  }
  return { placed: [] as Placed[], unplaced: sized };
}
