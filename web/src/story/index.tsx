import { useEffect, useRef } from "react";
import { Blueprint } from "./aircraft/Blueprint";
import { Board } from "./board/Board";
import { ScrollProgress } from "./chrome/ScrollProgress";
import { SiteNav } from "./chrome/SiteNav";
import { useStory } from "./data/context";
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

/** If the API can't be reached, say so once, quietly: every number on the page comes from it. */
function ApiNote() {
  const { runError } = useStory();
  if (!runError) return null;
  return (
    <p role="status" className="fixed inset-x-0 bottom-4 z-50 mx-auto w-fit max-w-[calc(100vw-32px)] rounded-full bg-navy-900/90 px-4 py-2 text-[13px] text-cloud-300 shadow-lg ring-1 ring-white/10 backdrop-blur">
      The storm run didn&rsquo;t load, so the numbers are waiting on the StormCheck API.
    </p>
  );
}

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
    document.title = "Storm Éowyn, 24 Jan 2025 · StormCheck";
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
          <ApiNote />
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
