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
  registered = true;
}

registerGsap();

export const prefersReducedMotion = () =>
  typeof window !== "undefined" && window.matchMedia("(prefers-reduced-motion: reduce)").matches;

export { gsap, ScrollTrigger, DrawSVGPlugin, SplitText, CustomEase, useGSAP };
