/** Deck navigation as pure functions: the URL carries the slide index, keys and clicks turn into a target. */

export type NavAction = { type: "go"; to: number } | { type: "exit" } | { type: "fullscreen" };

/** "/pitch/3" → 3. Missing or junk → 0; past the end → the last slide. */
export function parseSlide(segment: string | undefined, total: number): number {
  const n = Number.parseInt((segment ?? "").split("/")[0] ?? "", 10);
  if (!Number.isFinite(n) || n < 0) return 0;
  return Math.min(n, total - 1);
}

export const clampSlide = (n: number, total: number) => Math.max(0, Math.min(total - 1, n));

type KeyLike = Pick<KeyboardEvent, "key" | "shiftKey" | "metaKey" | "ctrlKey" | "altKey">;

/**
 * → / Space / PageDown (what clickers send) / ↓ next; ← / PageUp / ↑ / Shift+Space previous; Home / End;
 * a digit jumps to that slide; Esc leaves the deck; F toggles full screen. Browser shortcuts pass through.
 */
export function keyToAction(e: KeyLike, index: number, total: number): NavAction | null {
  if (e.metaKey || e.ctrlKey || e.altKey) return null;
  switch (e.key) {
    case "ArrowRight":
    case "ArrowDown":
    case "PageDown":
      return { type: "go", to: index + 1 };
    case " ":
    case "Spacebar":
      return { type: "go", to: e.shiftKey ? index - 1 : index + 1 };
    case "ArrowLeft":
    case "ArrowUp":
    case "PageUp":
      return { type: "go", to: index - 1 };
    case "Home":
      return { type: "go", to: 0 };
    case "End":
      return { type: "go", to: total - 1 };
    case "Escape":
      return { type: "exit" };
    case "f":
    case "F":
      return { type: "fullscreen" };
  }
  if (/^\d$/.test(e.key)) {
    const n = Number(e.key);
    return n < total ? { type: "go", to: n } : null;
  }
  return null;
}

/** A click or tap on the right half moves on, the left half goes back. */
export const clickTarget = (clientX: number, width: number, index: number) => (clientX >= width / 2 ? index + 1 : index - 1);
