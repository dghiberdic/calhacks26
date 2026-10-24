import type { ComponentType } from "react";
import type { PitchData } from "../data";
import { Architecture } from "./Architecture";
import { Business } from "./Business";
import { CfoLine } from "./CfoLine";
import { Cover } from "./Cover";
import { Judged } from "./Judged";
import { RealSimulated } from "./RealSimulated";

export type Slide = { id: string; label: string; Component: ComponentType<{ data: PitchData }> };

/** The deck, in order. `/pitch/<index>` addresses a slide; 0 is the cover. */
export const SLIDES: Slide[] = [
  { id: "cover", label: "StormCheck", Component: Cover },
  { id: "business", label: "The business", Component: Business },
  { id: "judged", label: "The airline, judged", Component: Judged },
  { id: "architecture", label: "How it works", Component: Architecture },
  { id: "real", label: "Real, simulated, and how we know", Component: RealSimulated },
  { id: "cfo", label: "The CFO line", Component: CfoLine },
];
