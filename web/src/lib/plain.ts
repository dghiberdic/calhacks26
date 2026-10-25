import { airport, iataOf } from "./airports";
import { eur, flightLabel, longDate, periodLabel } from "./format";
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

/** Money as the books write it ("€99,000.00", "-€3,600.00"). */
const MONEY = /(-?)€(\d{1,3}(?:,\d{3})+|\d+)(?:\.(\d{2}))?(?!\d)/g;
/** Flight and coupon ids: "NS31@2025-01-24", "NS31@2025-01-24:14C". */
const FLIGHT = /\b[A-Z]{2}\d{1,4}@\d{4}-\d{2}-\d{2}(?::\d{1,3}[A-Z])?(?![\w-])/g;

/**
 * A journal memo the way a controller reads it: "€99,000.00" → "€99,000" (cents only when there are any),
 * "NS31@2025-01-24" → "NS31 · 24 Jan", storm and cohort ids and segments in words (plainIds), bare dates
 * and periods spelled out. Display only: the stored memo is never changed.
 */
export function plainMemo(memo: string): string {
  return plainIds(memo.replace(FLIGHT, (id: string) => flightLabel(id)))
    .replace(MONEY, (_m: string, sign: string, whole: string, frac: string | undefined) => {
      const cents = Number(whole.replace(/,/g, "")) * 100 + Number(frac ?? 0);
      return eur(sign ? -cents : cents, { cents: Number(frac ?? 0) !== 0 });
    })
    .replace(/(?<![\w@-])(\d{4}-\d{2}-\d{2})(?![\w-])/g, (d: string) => longDate(d))
    .replace(/\bperiod (\d{4}-\d{2})\b/g, (_m: string, p: string) => `period ${periodLabel(p)}`);
}
