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
import { RuleLabChapter } from "./verdict/RuleLabChapter";
import { AskOnce } from "./verdict/AskOnce";
import { Closing } from "./verdict/Closing";
import { MorningAfter } from "./verdict/MorningAfter";
import { Trace } from "./verdict/Trace";
import { Verdict } from "./verdict/Verdict";
import { StormWindow } from "./window/StormWindow";
import "./story.css";

/** If the storm API can't be reached, explain why the storm's figures are waiting. */
function ApiNote() {
  const { runError } = useStory();
  if (!runError) return null;
  return (
    <p role="status" className="fixed inset-x-0 bottom-4 z-50 mx-auto w-fit max-w-[calc(100vw-32px)] rounded-full bg-navy-900/90 px-4 py-2 text-[13px] text-cloud-300 shadow-lg ring-1 ring-white/10 backdrop-blur">
      The results could not load. Refresh to try again.
    </p>
  );
}

/**
 * /story — the immersive scroll story, outside the app shell. Storm Éowyn, Dublin, 24 Jan 2025:
 * the storm → the board as OCC coded it → the weather's window → the aircraft as evidence → still on
 * stand → the morning after → the euros → the trace → asks once → Rule Lab → two seats.
 * StoryData supplies the storm; Rule Lab supplies its own labeled test evidence. Motion is GSAP
 * ScrollTrigger on Lenis, and reduced motion shows every beat still.
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
            <RuleLabChapter />
            <Closing />
          </main>
        </div>
      </SmoothScroll>
    </StoryData>
  );
}
