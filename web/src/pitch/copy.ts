/**
 * The deck's fixed words, with the plan's honest framing and accounting boundaries preserved.
 * The introduction is short enough to understand before the first example;
 * every passenger count, euro and percentage on a slide is read from the API when it renders.
 */

/** Product explanation. The emphasised spans are only typography. */
export const SEATS_LINE_PARTS: { text: string; strong?: boolean }[] = [
  { text: "StormCheck checks cancellation records against " },
  { text: "weather and maintenance evidence", strong: true },
  { text: ", then drafts passenger compensation and accounting entries. " },
  { text: "People approve the payments.", strong: true },
];

export const SEATS_LINE = SEATS_LINE_PARTS.map((p) => p.text).join("");

/** Plan §1.1: "say exactly this". */
export const HONEST_FRAMING =
  "Real Dublin weather, real airport traffic, real distances and real EU law. Northstar’s schedule, logs, passengers and claims are simulated on top, with the mess left in.";

/** Plan §9 wording for the "Real" card (THREAD_JUSTIN J11). */
export const REAL_CARD = "Real Dublin weather, traffic and EU law; simulated logs, mess left in";

export const ARCHITECTURE_HEADLINE = "Claude reads. The engine calculates.";

/**
 * The Business slide's card tags, in plain words (they replaced Hyphenate's `self-learning`, `ai-automated`,
 * `needs-review` and `new-policy`). The app's Learns strip should use the same four.
 */
export const CARD_TAGS = {
  learns: "past decisions",
  runs: "checks the evidence",
  escalates: "human review",
  improves: "saved ruling",
} as const;

/**
 * Satellite credit for the cover. public/pitch/eowyn-2025-01-24.webp is a NASA GIBS WMS export of
 * MODIS_Terra_CorrectedReflectance_TrueColor for 2025-01-24, 48.5°W–8.4°E × 31.83°N–63.83°N at 3840×2160.
 */
export const COVER_IMAGE_CREDIT = "Storm Éowyn · 24 Jan 2025 · NASA GIBS · MODIS Terra true colour";

/**
 * Words and patterns the deck never shows (Justin: "drop the words that sound AI generated"). The e2e suite
 * reads every slide's rendered text against this list.
 */
export const BANNED_WORDS = [
  "seamless",
  "leverage",
  "unlock",
  "empower",
  "revolutionise",
  "revolutionize",
  "cutting-edge",
  "harness",
  "robust",
  "delve",
  "elevate",
  "streamline",
  "game-changer",
  "comprehensive",
  "effortless",
  "intelligent",
  "ai-powered",
  "ai-driven",
  "ai-automated",
  "self-learning",
  "next-gen",
  "state-of-the-art",
  "transform",
  "journey",
  "landscape",
  "ecosystem",
  "synergy",
  "holistic",
  "tapestry",
  "supercharge",
  "smart",
  "magic",
  "insights",
  "actionable",
  "at scale",
  "powerful",
  "world-class",
  "unleash",
  "reimagine",
  "innovative",
  "frictionless",
  "intuitive",
  "end-to-end",
  "stunning",
  "immersive",
  "delight",
  "crafted",
  "elegant",
  "beautiful",
  "the future of",
  "imagine",
  "introducing",
];

/** The first banned word or pattern found in a slide's visible text, or null when it reads clean. */
export function copyProblem(text: string): string | null {
  const lower = text.toLowerCase();
  for (const word of BANNED_WORDS) {
    // Whole words (and their -s/-ed/-ing/-ly forms): "transform" must not catch "transformer" twice, but
    // "transforms" and "transformed" count.
    const re = new RegExp(`(^|[^a-z])${word.replace(/[-]/g, "\\-")}(s|es|ed|d|ing|ly)?([^a-z]|$)`);
    if (re.test(lower)) return `banned word "${word}"`;
  }
  if (text.includes("—")) return "an em dash";
  if (text.includes("!")) return "an exclamation mark";
  if (/\p{Extended_Pictographic}/u.test(text)) return "an emoji";
  if (/\bAI\b/.test(text)) return '"AI" as a selling word';
  // A question mark outside quotes is a rhetorical question on a slide (a quoted “why?” is a label).
  const unquoted = text.replace(/[“"][^”"]*[”"]/g, "");
  if (unquoted.includes("?")) return "a rhetorical question";
  if (/\bit[’']s not\b[^.]*\bit[’']s\b/i.test(text)) return `"It's not X, it's Y"`;
  return null;
}
