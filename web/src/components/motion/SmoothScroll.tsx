"use client";

import Lenis from "lenis";
import { createContext, useContext, useEffect, useState } from "react";
import { gsap, ScrollTrigger, prefersReducedMotion } from "./gsap";

const LenisContext = createContext<Lenis | null>(null);
export const useLenis = () => useContext(LenisContext);

/** Lenis drives the scroll; GSAP's ticker drives Lenis so ScrollTrigger never lags a frame. */
export function SmoothScroll({ children }: { children: React.ReactNode }) {
  const [lenis, setLenis] = useState<Lenis | null>(null);

  useEffect(() => {
    if (prefersReducedMotion()) return;
    const l = new Lenis({ lerp: 0.085, wheelMultiplier: 0.9, smoothWheel: true });
    l.on("scroll", ScrollTrigger.update);
    if (process.env.NODE_ENV !== "production") Object.assign(window, { lenis: l });
    const tick = (time: number) => l.raf(time * 1000);
    gsap.ticker.add(tick);
    gsap.ticker.lagSmoothing(0);
    // eslint-disable-next-line react-hooks/set-state-in-effect -- the instance only exists after mount
    setLenis(l);
    return () => {
      gsap.ticker.remove(tick);
      l.destroy();
      setLenis(null);
    };
  }, []);

  return <LenisContext.Provider value={lenis}>{children}</LenisContext.Provider>;
}
