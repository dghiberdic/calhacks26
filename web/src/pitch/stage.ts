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

/** The deck's faces, with a sample of the text it sets in them (fontsource splits faces by unicode range). */
const FACES = ['640 156px "Archivo Variable"', '400 34px "Archivo Variable"', '400 18px "Geist Mono Variable"'];
const SAMPLE = "Not weather. Broken plane. €34,650 Éowyn 02:30–15:00Z";

let facesLoaded = false;

/**
 * True once the deck's web fonts are in, so a slide's first layout is its final one (a late font swap reflows
 * the seats line and shifts the cover). The fonts are requested here: nothing on screen asks for them yet.
 */
export function useFontsReady() {
  const [ready, setReady] = useState(() => facesLoaded || typeof document === "undefined" || !document.fonts?.load);
  useEffect(() => {
    if (ready) return;
    let alive = true;
    const done = () => {
      facesLoaded = true;
      if (alive) setReady(true);
    };
    Promise.all(FACES.map((f) => document.fonts.load(f, SAMPLE))).then(done, done);
    return () => {
      alive = false;
    };
  }, [ready]);
  return ready;
}

/** True after `ms`: the deck stops waiting for fonts or data and shows what it has. */
export function useElapsed(ms: number) {
  const [elapsed, setElapsed] = useState(false);
  useEffect(() => {
    const t = window.setTimeout(() => setElapsed(true), ms);
    return () => window.clearTimeout(t);
  }, [ms]);
  return elapsed;
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
