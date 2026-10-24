import { gsap } from "gsap";
import { ScrollTrigger } from "gsap/ScrollTrigger";
import { CustomEase } from "gsap/CustomEase";
import { useGSAP } from "@gsap/react";

// Registered once, when the story chunk loads (the app screens use Motion, not GSAP).
gsap.registerPlugin(ScrollTrigger, CustomEase, useGSAP);
// A pen plotter accelerates fast, glides, then settles.
CustomEase.create("plotter", "M0,0 C0.18,0.02 0.22,0.62 0.48,0.82 0.68,0.97 0.84,1 1,1");
gsap.defaults({ ease: "power3.out", duration: 0.9 });
ScrollTrigger.config({ ignoreMobileResize: true });

export const prefersReducedMotion = () => typeof window !== "undefined" && window.matchMedia("(prefers-reduced-motion: reduce)").matches;

/** gsap.matchMedia() conditions every scroll choreography uses: motion allowed, and the phone layout. */
export const MEDIA = { motion: "(prefers-reduced-motion: no-preference)", phone: "(max-width: 767px)", narrow: "(max-width: 1023px)" } as const;

export { gsap, ScrollTrigger, useGSAP };

/**
 * Line art that plots itself without being measured. pathLength=1 normalises every path, so a dash
 * offset of 1.01 → 0 draws it on; the gap of 2 keeps round caps from leaving a dot at either end.
 * (DrawSVG measures each path with getTotalLength: ~250 ms across the story's ~700 line-art paths.)
 * Spread PLOTTED on the paths and tween from UNPLOTTED; without motion the paths are simply drawn.
 */
export const PLOTTED = { pathLength: 1, strokeDasharray: "1 2", strokeDashoffset: 0 } as const;
export const UNPLOTTED = { attr: { "stroke-dashoffset": 1.01 } };
