import type { ComponentType } from "react";
import type { PitchData } from "../data";
import { Architecture } from "./Architecture";
import { Business } from "./Business";
import { CfoLine } from "./CfoLine";
import { Cover } from "./Cover";
import { Judged } from "./Judged";
import { RealSimulated } from "./RealSimulated";

/** `usesData`: the slide shows API figures, so on a cold open the deck waits (briefly) for them before it lays out. */
export type Slide = { id: string; label: string; Component: ComponentType<{ data: PitchData }>; usesData: boolean };

/** The deck, in order. `/pitch/<index>` addresses a slide; 0 is the cover. */
export const SLIDES: Slide[] = [
  { id: "cover", label: "StormCheck", Component: Cover, usesData: false },
  { id: "business", label: "The business", Component: Business, usesData: true },
  { id: "judged", label: "The airline, judged", Component: Judged, usesData: true },
  { id: "architecture", label: "How it works", Component: Architecture, usesData: false },
  { id: "real", label: "Real, simulated, and how we know", Component: RealSimulated, usesData: true },
  { id: "cfo", label: "The CFO line", Component: CfoLine, usesData: true },
];
