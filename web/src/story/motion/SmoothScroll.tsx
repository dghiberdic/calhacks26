import Lenis from "lenis";
import { useEffect, type ReactNode } from "react";
import { gsap, prefersReducedMotion, ScrollTrigger } from "./gsap";

/**
 * Lenis drives the scroll and GSAP's ticker drives Lenis, so ScrollTrigger never lags a frame.
 * With reduced motion the browser scrolls natively. The story always opens at the top.
 */
export function SmoothScroll({ children }: { children: ReactNode }) {
  useEffect(() => {
    const restoration = history.scrollRestoration;
    history.scrollRestoration = "manual";
    window.scrollTo(0, 0);
    if (prefersReducedMotion()) {
      return () => {
        history.scrollRestoration = restoration;
      };
    }
    const lenis = new Lenis({ lerp: 0.085, wheelMultiplier: 0.9, smoothWheel: true });
    lenis.on("scroll", ScrollTrigger.update);
    const tick = (time: number) => lenis.raf(time * 1000);
    gsap.ticker.add(tick);
    gsap.ticker.lagSmoothing(0);
    // Pins measure the page; late fonts change line heights, so measure again once they're in.
    void document.fonts?.ready.then(() => ScrollTrigger.refresh());
    return () => {
      gsap.ticker.remove(tick);
      gsap.ticker.lagSmoothing(500, 33);
      lenis.destroy();
      history.scrollRestoration = restoration;
    };
  }, []);

  return <>{children}</>;
}
