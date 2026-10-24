import { memo, useLayoutEffect, useRef } from "react";
import { cn } from "@/lib/utils";
import { prefersReducedMotion } from "../motion/gsap";

const CHARSET = " ABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789:.,-€/";
const MAX_STEPS = 7;

// One rAF loop for every cell on the page: flips are queued with a due time and run in frame order,
// so a board of ~900 cells costs a few text writes and two compositor animations per flip, not a React render.
// At most PER_FRAME flips run in one frame (the rest slip a frame), so filling the board never stalls a phone.
type Job = { at: number; run: () => void };
let queue: Job[] = [];
let raf = 0;
const PER_FRAME = 140;
function pump() {
  const now = performance.now();
  const due: Job[] = [];
  const later: Job[] = [];
  for (const j of queue) (j.at <= now && due.length < PER_FRAME ? due : later).push(j);
  queue = later;
  for (const j of due) j.run();
  raf = queue.length ? requestAnimationFrame(pump) : 0;
}
function schedule(at: number, run: () => void, owner: Set<Job>) {
  const job = { at, run };
  queue.push(job);
  owner.add(job);
  if (!raf) raf = requestAnimationFrame(pump);
}
function cancel(owner: Set<Job>) {
  if (!owner.size) return;
  queue = queue.filter((j) => !owner.has(j));
  owner.clear();
}

/** The drum between two characters; long runs skip ahead like a real board does. */
function drum(from: string, to: string): string[] {
  const a = Math.max(0, CHARSET.indexOf(from));
  const b = Math.max(0, CHARSET.indexOf(to));
  if (a === b) return [];
  const seq: string[] = [];
  for (let i = (a + 1) % CHARSET.length; ; i = (i + 1) % CHARSET.length) {
    seq.push(CHARSET[i]);
    if (i === b) break;
  }
  return seq.length > MAX_STEPS ? [...seq.slice(0, 2), ...seq.slice(-(MAX_STEPS - 2))] : seq;
}

const PUNCT = new Set([":", ",", "."]);

/** Each cell's four glyph spans and two leaves, found once. */
type Parts = { "flap-top": HTMLElement; "flap-bottom": HTMLElement; "flap-leaf-front": HTMLElement; "flap-leaf-back": HTMLElement; front: HTMLElement; back: HTMLElement };
const parts = new WeakMap<HTMLElement, Parts>();
function partsOf(cell: HTMLElement): Parts {
  let p = parts.get(cell);
  if (!p) {
    const g = (c: string) => cell.querySelector<HTMLElement>(`.${c} > span`)!;
    p = { "flap-top": g("flap-top"), "flap-bottom": g("flap-bottom"), "flap-leaf-front": g("flap-leaf-front"), "flap-leaf-back": g("flap-leaf-back"), front: cell.querySelector<HTMLElement>(".flap-leaf-front")!, back: cell.querySelector<HTMLElement>(".flap-leaf-back")! };
    parts.set(cell, p);
  }
  return p;
}

/** Glyphs live in a data attribute drawn by CSS (::before), so the board's ~900 cells stay out of the page's text. */
function setText(cell: HTMLElement, part: "flap-top" | "flap-bottom" | "flap-leaf-front" | "flap-leaf-back", c: string) {
  const el = partsOf(cell)[part];
  if (!el || el.dataset.c === c) return;
  el.dataset.c = c;
  if (PUNCT.has(c)) el.dataset.p = "";
  else delete el.dataset.p;
}

/** Flip one cell to `target`, starting `delay` ms from now, `step` ms per character. */
function flipCell(cell: HTMLElement, target: string, delay: number, step: number, owner: Set<Job>, instant: boolean) {
  const to = CHARSET.includes(target) ? target : " ";
  if (instant) {
    cell.dataset.c = to;
    setText(cell, "flap-top", to);
    setText(cell, "flap-bottom", to);
    return;
  }
  const seq = drum(cell.dataset.c ?? " ", to);
  const { front, back } = partsOf(cell);
  const t0 = performance.now() + delay;
  seq.forEach((next, k) => {
    schedule(
      t0 + k * step,
      () => {
        const cur = cell.dataset.c ?? " ";
        setText(cell, "flap-top", next);
        setText(cell, "flap-bottom", cur);
        setText(cell, "flap-leaf-front", cur);
        setText(cell, "flap-leaf-back", next);
        front?.animate([{ transform: "rotateX(0deg)", visibility: "visible" }, { transform: "rotateX(-90deg)", visibility: "visible" }], { duration: step / 2, easing: "cubic-bezier(0.55,0,1,0.45)" });
        back?.animate([{ transform: "rotateX(90deg)", visibility: "visible" }, { transform: "rotateX(0deg)", visibility: "visible" }], { duration: step / 2, delay: step / 2, easing: "cubic-bezier(0,0.55,0.45,1)" });
        cell.dataset.c = next;
      },
      owner,
    );
  });
  // the lower half catches up once the last leaf has fallen
  schedule(t0 + seq.length * step, () => setText(cell, "flap-bottom", cell.dataset.c ?? " "), owner);
}

const Cell = () => (
  <span className="flap-cell" aria-hidden="true">
    <span className="flap-half flap-top">
      <span data-c=" " />
    </span>
    <span className="flap-half flap-bottom">
      <span data-c=" " />
    </span>
    <span className="flap-half flap-leaf-front">
      <span data-c=" " />
    </span>
    <span className="flap-half flap-leaf-back">
      <span data-c=" " />
    </span>
    <span className="flap-axis" />
  </span>
);

/** A fixed-width run of Solari cells that flips to `text` whenever it changes. Screen readers read `text`. */
export const FlapText = memo(function FlapText({ text, width, delay = 0, stagger = 26, step = 62, className }: { text: string; width: number; delay?: number; stagger?: number; step?: number; className?: string }) {
  const ref = useRef<HTMLSpanElement>(null);
  const jobs = useRef(new Set<Job>());
  const padded = text.toUpperCase().padEnd(width, " ").slice(0, width);

  useLayoutEffect(() => {
    const cells = ref.current?.querySelectorAll<HTMLElement>(".flap-cell");
    if (!cells) return;
    const owner = jobs.current;
    cancel(owner);
    const instant = prefersReducedMotion();
    cells.forEach((cell, i) => flipCell(cell, padded[i], delay + i * stagger, step, owner, instant));
    return () => cancel(owner);
  }, [padded, delay, stagger, step]);

  return (
    <span ref={ref} className={cn("inline-flex gap-[0.08em]", className)}>
      <span className="sr-only">{text}</span>
      {Array.from({ length: width }, (_, i) => (
        <Cell key={i} />
      ))}
    </span>
  );
});
