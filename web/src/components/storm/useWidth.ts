import { useEffect, useRef, useState } from "react";

/** Width of an element, kept current with a ResizeObserver (charts draw at their real pixel size). */
export function useWidth<T extends HTMLElement>(initial = 960) {
  const ref = useRef<T>(null);
  const [width, setWidth] = useState(initial);
  useEffect(() => {
    const el = ref.current;
    if (!el) return;
    setWidth(Math.round(el.getBoundingClientRect().width) || initial);
    const ro = new ResizeObserver(([entry]) => setWidth(Math.round(entry.contentRect.width)));
    ro.observe(el);
    return () => ro.disconnect();
  }, [initial]);
  return [ref, width] as const;
}
