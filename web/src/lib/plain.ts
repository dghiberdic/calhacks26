import { airport, iataOf } from "./airports";
import { longDate } from "./format";
import { stormName } from "./storms";

const SEGMENT: [RegExp, string][] = [
  [/\blong_haul(?:_gt\d+)?\b/g, "long-haul"],
  [/\bmedium_haul(?:_\d+_\d+)?\b/g, "medium-haul"],
  [/\bshort_haul(?:_lt\d+)?\b/g, "short-haul"],
];

/**
 * Raw ids in server prose, the way a person says them: "EIDW@2024-01-21" → "Storm Isha (21 Jan 2024)",
 * "long_haul_gt3500" → "long-haul". Flight ids ("NS31@2025-01-24") are left alone. Display only.
 */
export function plainIds(text: string): string {
  let out = text.replace(/\b([A-Z]{4})@(\d{4}-\d{2}-\d{2})\b/g, (id: string, icao: string, date: string) => {
    const name = stormName(id);
    const place = airport(iataOf(icao))?.name.replace(/ Airport$/, "") ?? icao;
    return name ? `${name} (${longDate(date)})` : `${place}, ${longDate(date)}`;
  });
  for (const [re, plain] of SEGMENT) out = out.replace(re, plain);
  return out;
}
