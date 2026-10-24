import type { ReactNode } from "react";
import { StoryContext } from "./context";
import { useStoryQueries } from "./useStoryQueries";

/** Asks the API once for everything the story shows; every section reads it with useStory(). */
export function StoryData({ children }: { children: ReactNode }) {
  const story = useStoryQueries();
  return <StoryContext.Provider value={story}>{children}</StoryContext.Provider>;
}
