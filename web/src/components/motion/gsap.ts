"use client";

import { gsap } from "gsap";
import { ScrollTrigger } from "gsap/ScrollTrigger";
import { DrawSVGPlugin } from "gsap/DrawSVGPlugin";
import { SplitText } from "gsap/SplitText";
import { CustomEase } from "gsap/CustomEase";
import { useGSAP } from "@gsap/react";

let registered = false;

export function registerGsap() {
  if (registered || typeof window === "undefined") return;
  gsap.registerPlugin(ScrollTrigger, DrawSVGPlugin, SplitText, CustomEase, useGSAP);
  // A pen plotter accelerates fast, glides, then settles.
  CustomEase.create("plotter", "M0,0 C0.18,0.02 0.22,0.62 0.48,0.82 0.68,0.97 0.84,1 1,1");
  CustomEase.create("settle", "M0,0 C0.12,0.6 0.24,1.02 0.44,1.01 0.62,1 0.8,1 1,1");
  gsap.defaults({ ease: "power3.out", duration: 0.9 });
  if (process.env.NODE_ENV !== "production") Object.assign(window, { gsap, ScrollTrigger });
  // Reduced motion: time-based tweens resolve instantly; scroll-scrubbed ones stay user-driven.
  if (window.matchMedia("(prefers-reduced-motion: reduce)").matches) gsap.globalTimeline.timeScale(50);
  registered = true;
}

registerGsap();

export const prefersReducedMotion = () =>
  typeof window !== "undefined" && window.matchMedia("(prefers-reduced-motion: reduce)").matches;

export { gsap, ScrollTrigger, DrawSVGPlugin, SplitText, CustomEase, useGSAP };

/**
 * Line art that plots itself without being measured. pathLength=1 normalises every path, so a dash
 * offset of 1.01 → 0 draws it on; the gap of 2 keeps round caps from leaving a dot at either end.
 * DrawSVG measures each path (style recalc, getBBox, getTotalLength): ~250 ms at load across the
 * landing's ~650 line-art paths. Spread PLOTTED on the paths and UNPLOTTED into a .from() tween.
 */
export const PLOTTED = { pathLength: 1, strokeDasharray: "1 2", strokeDashoffset: 0 } as const;
export const UNPLOTTED = { attr: { "stroke-dashoffset": 1.01 } };
