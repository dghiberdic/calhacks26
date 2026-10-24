import { useEffect, useRef } from "react";
import { useReducedMotion } from "motion/react";

/**
 * When an answer lands below the fold, bring its top under the sticky header (once, on mount). An
 * answer already in view stays put, so nothing jumps while someone is reading.
 */
export function useBringIntoView<T extends HTMLElement>(offset = 72) {
  const ref = useRef<T>(null);
  const reduce = useReducedMotion();
  useEffect(() => {
    const el = ref.current;
    if (!el) return;
    const frame = window.requestAnimationFrame(() => {
      const top = el.getBoundingClientRect().top;
      if (top > window.innerHeight * 0.55 || top < offset - 8) window.scrollTo({ top: Math.max(0, window.scrollY + top - offset), behavior: reduce ? "auto" : "smooth" });
    });
    return () => window.cancelAnimationFrame(frame);
    // Once per answer: the caller keys the element.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);
  return ref;
}
