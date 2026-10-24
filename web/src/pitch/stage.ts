import { useEffect, useState } from "react";

/** Every slide is laid out on one fixed 1920×1080 canvas; the deck scales it to the screen. */
export const STAGE_W = 1920;
export const STAGE_H = 1080;

export const EASE_OUT: [number, number, number, number] = [0.16, 1, 0.3, 1];

const fit = () => (typeof window === "undefined" ? 1 : Math.min(window.innerWidth / STAGE_W, window.innerHeight / STAGE_H));

/** The largest scale at which the stage fits the window; the rest is letterbox. */
export function useFitScale() {
  const [scale, setScale] = useState(fit);
  useEffect(() => {
    const onResize = () => setScale(fit());
    onResize();
    window.addEventListener("resize", onResize);
    return () => window.removeEventListener("resize", onResize);
  }, []);
  return scale;
}

/** Which way the deck last moved (1 forward, -1 back), kept with React's "adjust state while rendering" pattern. */
export function useDirection(index: number) {
  const [last, setLast] = useState(index);
  const [dir, setDir] = useState(1);
  if (index !== last) {
    setDir(index > last ? 1 : -1);
    setLast(index);
  }
  return dir;
}
