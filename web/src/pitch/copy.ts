/**
 * The deck's fixed words, verbatim from THREAD_JUSTIN J11 and IMPLEMENTATION_PLAN (§1.1 honest framing,
 * §9 wording). Only world facts from the plan live here ("€1.1B Irish carrier", "2 Claude roles");
 * every passenger count, euro and percentage on a slide is read from the API when it renders.
 */

/** THREAD_JUSTIN J11, word for word. The emphasised spans are only typography. */
export const SEATS_LINE_PARTS: { text: string; strong?: boolean }[] = [
  { text: "StormCheck fills " },
  { text: "two seats", strong: true },
  { text: " at Northstar Air, the " },
  { text: "Passenger Claims Accountant", strong: true },
  { text: " and the " },
  { text: "Revenue Accountant", strong: true },
  { text: ", with one step between them: " },
  { text: "what really caused each cancellation", strong: true },
  { text: ". It drafts every payout and the EU261 compensation liability; the Claims Lead approves every payment." },
];

export const SEATS_LINE = SEATS_LINE_PARTS.map((p) => p.text).join("");

/** Plan §1.1: "say exactly this". */
export const HONEST_FRAMING =
  "Real Dublin weather, real airport traffic, real distances and real EU law. Northstar’s schedule, logs, passengers and claims are simulated on top, with the mess left in.";

/** Plan §9 wording for the "Real" card (THREAD_JUSTIN J11). */
export const REAL_CARD = "Real Dublin weather, traffic and EU law; simulated logs, mess left in";

export const ARCHITECTURE_HEADLINE = "2 Claude roles + 1 deterministic engine";

/** Satellite credit for the cover (public/pitch/eowyn-2025-01-24.webp, cropped from the GIBS mosaic). */
export const COVER_IMAGE_CREDIT = "Storm Éowyn · 24 Jan 2025 · NASA GIBS · MODIS Terra true colour";
