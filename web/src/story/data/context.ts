import { createContext, useContext } from "react";
import type { useStoryQueries } from "./useStoryQueries";

export type Story = ReturnType<typeof useStoryQueries>;

export const StoryContext = createContext<Story | null>(null);

/** Everything the story shows, asked of the API once (see StoryData). */
export function useStory(): Story {
  const s = useContext(StoryContext);
  if (!s) throw new Error("useStory() outside <StoryData>");
  return s;
}
