import { memo, useLayoutEffect, useRef } from "react";
import { cn } from "@/lib/utils";
import { prefersReducedMotion } from "../motion/gsap";

const CHARSET = " ABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789:.,-€/";
const MAX_STEPS = 7;

// One rAF loop for every cell on the page: flips are queued with a due time and run in frame order,
// so a board of ~900 cells costs a few text writes and two compositor animations per flip, not a React render.
type Job = { at: number; run: () => void };
let queue: Job[] = [];
let raf = 0;
function pump() {
  const now = performance.now();
  const due = queue.filter((j) => j.at <= now);
  if (due.length) queue = queue.filter((j) => j.at > now);
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

function setText(cell: HTMLElement, part: string, c: string) {
  const el = cell.querySelector<HTMLElement>(`.${part} > span`);
  if (el && el.textContent !== c) el.textContent = c;
}

/** Flip one cell to `target`, starting `delay` ms from now, `step` ms per character. */
function flipCell(cell: HTMLElement, target: string, delay: number, step: number, owner: Set<Job>, instant: boolean) {
  const to = CHARSET.includes(target) ? target : " ";
  if (instant) {
    cell.dataset.c = to;
    for (const part of ["flap-top", "flap-bottom"]) setText(cell, part, to);
    return;
  }
  const seq = drum(cell.dataset.c ?? " ", to);
  const front = cell.querySelector<HTMLElement>(".flap-leaf-front");
  const back = cell.querySelector<HTMLElement>(".flap-leaf-back");
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
      <span> </span>
    </span>
    <span className="flap-half flap-bottom">
      <span> </span>
    </span>
    <span className="flap-half flap-leaf-front">
      <span> </span>
    </span>
    <span className="flap-half flap-leaf-back">
      <span> </span>
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
