import { useEffect, type RefObject } from "react";
import { ScrollTrigger } from "./gsap";

/**
 * Pins measure the page once. When API data lands and a section changes height (the trace, the
 * question cards), every trigger below it is off by that much, so measure again, once things settle.
 */
export function useAutoRefresh(ref: RefObject<HTMLElement | null>) {
  useEffect(() => {
    const el = ref.current;
    if (!el) return;
    let height = el.offsetHeight;
    let timer = 0;
    const ro = new ResizeObserver(() => {
      const next = el.offsetHeight;
      if (Math.abs(next - height) < 2) return;
      height = next;
      window.clearTimeout(timer);
      timer = window.setTimeout(() => {
        ScrollTrigger.refresh();
        height = el.offsetHeight;
      }, 220);
    });
    ro.observe(el);
    return () => {
      ro.disconnect();
      window.clearTimeout(timer);
    };
  }, [ref]);
}

/** Pinned sections refresh top to bottom, whatever order their data arrived in. */
export const PIN_PRIORITY = { hero: 10, window: 8, blueprint: 6, interlude: 4 } as const;
