import { useEffect, useRef } from "react";
import { Blueprint } from "./aircraft/Blueprint";
import { Board } from "./board/Board";
import { ScrollProgress } from "./chrome/ScrollProgress";
import { SiteNav } from "./chrome/SiteNav";
import { StoryData } from "./data/StoryData";
import { Hero } from "./hero/Hero";
import { Interlude } from "./interlude/Interlude";
import { SmoothScroll } from "./motion/SmoothScroll";
import { useAutoRefresh } from "./motion/useAutoRefresh";
import { AskOnce } from "./verdict/AskOnce";
import { Closing } from "./verdict/Closing";
import { MorningAfter } from "./verdict/MorningAfter";
import { Trace } from "./verdict/Trace";
import { Verdict } from "./verdict/Verdict";
import { StormWindow } from "./window/StormWindow";
import "./story.css";

/**
 * /story — the immersive scroll story, outside the app shell. Storm Éowyn, Dublin, 24 Jan 2025:
 * the storm → the board as OCC coded it → the weather's window → the aircraft as evidence → still on
 * stand → the morning after → the euros → the trace → asks once → two seats. Every count and euro is
 * the API's (StoryData); motion is GSAP ScrollTrigger on Lenis, and reduced motion shows every beat still.
 */
export default function StoryScreen() {
  const main = useRef<HTMLElement>(null);
  useAutoRefresh(main);
  useEffect(() => {
    const title = document.title;
    document.title = "StormCheck · Every storm leaves a bill";
    return () => {
      document.title = title;
    };
  }, []);

  return (
    <StoryData>
      <SmoothScroll>
        <div className="story">
          <SiteNav />
          <ScrollProgress />
          <main ref={main} id="story-main">
            <Hero />
            <Board />
            <StormWindow />
            <Blueprint />
            <Interlude />
            <MorningAfter />
            <Verdict />
            <Trace />
            <AskOnce />
            <Closing />
          </main>
        </div>
      </SmoothScroll>
    </StoryData>
  );
}
