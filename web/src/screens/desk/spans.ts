/**
 * Where each extracted fact's `span` sits inside the source text. The Reader only keeps a fact whose
 * span is an exact substring of the text after whitespace normalisation (THREAD_FILIP F5), so the
 * match here is the same: runs of whitespace are equal to one space. A span that still can't be
 * found (it shouldn't happen) is reported as unplaced rather than guessed.
 */

export type Range = { start: number; end: number };

/** Collapse whitespace runs to single spaces, remembering where each kept character came from. */
function normalise(text: string): { flat: string; origin: number[] } {
  let flat = "";
  const origin: number[] = [];
  let inSpace = false;
  for (let i = 0; i < text.length; i++) {
    const ch = text[i];
    if (/\s/.test(ch)) {
      if (!inSpace && flat.length) {
        flat += " ";
        origin.push(i);
      }
      inSpace = true;
    } else {
      flat += ch;
      origin.push(i);
      inSpace = false;
    }
  }
  return { flat, origin };
}

/**
 * Every place `span` occurs in `text` (whitespace-insensitive; exact case first, then any case).
 * Returns ranges in the ORIGINAL text.
 */
export function findSpan(text: string, span: string | null | undefined): Range[] {
  if (!text || !span) return [];
  const needle = span.trim().replace(/\s+/g, " ");
  if (!needle) return [];
  const { flat, origin } = normalise(text);
  const search = (hay: string, n: string) => {
    const out: Range[] = [];
    let from = 0;
    for (;;) {
      const at = hay.indexOf(n, from);
      if (at < 0) break;
      const start = origin[at];
      const end = origin[at + n.length - 1] + 1;
      out.push({ start, end });
      from = at + Math.max(1, n.length);
    }
    return out;
  };
  const exact = search(flat, needle);
  return exact.length ? exact : search(flat.toLowerCase(), needle.toLowerCase());
}

export type Segment = { start: number; end: number; text: string; keys: number[] };

/**
 * Split the text at every range boundary so overlapping spans can each be lit: each segment lists
 * the indices (`keys`) of the facts whose span covers it.
 */
export function segment(text: string, marks: { key: number; range: Range }[]): Segment[] {
  const cuts = new Set<number>([0, text.length]);
  for (const { range } of marks) {
    cuts.add(Math.max(0, Math.min(text.length, range.start)));
    cuts.add(Math.max(0, Math.min(text.length, range.end)));
  }
  const points = [...cuts].sort((a, b) => a - b);
  const out: Segment[] = [];
  for (let i = 0; i < points.length - 1; i++) {
    const start = points[i];
    const end = points[i + 1];
    if (end <= start) continue;
    const keys = marks.filter((mk) => mk.range.start <= start && mk.range.end >= end).map((mk) => mk.key);
    out.push({ start, end, text: text.slice(start, end), keys: [...new Set(keys)] });
  }
  return out;
}

/** Place every fact's span; the first occurrence wins unless the span occurs several times (all are lit). */
export function placeSpans<T extends { span?: string | null }>(text: string, facts: T[]) {
  const marks: { key: number; range: Range }[] = [];
  const unplaced: number[] = [];
  facts.forEach((f, key) => {
    if (!f.span) return;
    const ranges = findSpan(text, f.span);
    if (!ranges.length) unplaced.push(key);
    for (const range of ranges) marks.push({ key, range });
  });
  return { segments: segment(text, marks), unplaced, placed: new Set(marks.map((m) => m.key)) };
}
