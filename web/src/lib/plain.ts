import { airport, iataOf } from "./airports";
import { longDate } from "./format";
import { stormName } from "./storms";

/** Distance segments as the engine names them: long_haul_gt3500, medium_1500_3500, short_le1500, short_haul. */
const SEGMENT = /\b(long|medium|short)(?:_haul)?(?:_(?:gt|ge|lt|le)?\d+)*\b/g;

/**
 * Raw ids in server prose, the way a person says them: "EIDW@2024-01-21" → "Storm Isha (21 Jan 2024)",
 * "long_haul_gt3500" → "long-haul". Flight ids ("NS31@2025-01-24") are left alone. Display only.
 */
export function plainIds(text: string): string {
  const out = text.replace(/\b([A-Z]{4})@(\d{4}-\d{2}-\d{2})\b/g, (id: string, icao: string, date: string) => {
    const name = stormName(id);
    const place = airport(iataOf(icao))?.name.replace(/ Airport$/, "") ?? icao;
    return name ? `${name} (${longDate(date)})` : `${place}, ${longDate(date)}`;
  });
  return out.replace(SEGMENT, (seg: string, band: string) => (seg.includes("_") ? `${band}-haul` : seg));
}
