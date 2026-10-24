/**
 * The desk takes a LOCAL date: the calendar day at the airport (POST /desk {icao, date}). These
 * helpers read what a person types, say which day it is, and which UTC offset that day has there.
 * No clock reads except `todayIn`, which the field uses only to resolve "today" / "yesterday" and to
 * dim days that haven't happened yet. The server is still the one that says "future date".
 */

export type IsoDate = string; // YYYY-MM-DD

const MONTHS = ["jan", "feb", "mar", "apr", "may", "jun", "jul", "aug", "sep", "oct", "nov", "dec"];
const MONTH_NAMES = ["January", "February", "March", "April", "May", "June", "July", "August", "September", "October", "November", "December"];
const SHORT_MONTHS = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"];
const WEEKDAYS = ["Sun", "Mon", "Tue", "Wed", "Thu", "Fri", "Sat"];

const pad = (n: number) => String(n).padStart(2, "0");

export const toIso = (y: number, m: number, d: number): IsoDate => `${y}-${pad(m)}-${pad(d)}`;

export function parts(iso: IsoDate): { y: number; m: number; d: number } {
  const [y, m, d] = iso.split("-").map(Number);
  return { y, m, d };
}

export function isValidDate(y: number, m: number, d: number): boolean {
  if (!Number.isInteger(y) || !Number.isInteger(m) || !Number.isInteger(d)) return false;
  if (y < 1900 || y > 2999 || m < 1 || m > 12 || d < 1) return false;
  return d <= daysInMonth(y, m);
}

export const daysInMonth = (y: number, m: number) => new Date(Date.UTC(y, m, 0)).getUTCDate();

/** Day of week for a calendar date (0 = Sunday), independent of any time zone. */
export const weekday = (iso: IsoDate) => {
  const { y, m, d } = parts(iso);
  return new Date(Date.UTC(y, m - 1, d)).getUTCDay();
};

export function addDays(iso: IsoDate, n: number): IsoDate {
  const { y, m, d } = parts(iso);
  const t = new Date(Date.UTC(y, m - 1, d + n));
  return toIso(t.getUTCFullYear(), t.getUTCMonth() + 1, t.getUTCDate());
}

export function addMonths(iso: IsoDate, n: number): IsoDate {
  const { y, m, d } = parts(iso);
  const first = new Date(Date.UTC(y, m - 1 + n, 1));
  const ny = first.getUTCFullYear();
  const nm = first.getUTCMonth() + 1;
  return toIso(ny, nm, Math.min(d, daysInMonth(ny, nm)));
}

/** "Fri 24 Jan 2025". */
export function dayLabel(iso: IsoDate): string {
  const { y, m, d } = parts(iso);
  return `${WEEKDAYS[weekday(iso)]} ${d} ${SHORT_MONTHS[m - 1]} ${y}`;
}

/** "24 Jan 2025": what the field shows for editing. */
export function editLabel(iso: IsoDate): string {
  const { y, m, d } = parts(iso);
  return `${d} ${SHORT_MONTHS[m - 1]} ${y}`;
}

export const monthTitle = (y: number, m: number) => `${MONTH_NAMES[m - 1]} ${y}`;
export const monthName = (m: number) => MONTH_NAMES[m - 1];
export const WEEKDAY_SHORT = ["Mo", "Tu", "We", "Th", "Fr", "Sa", "Su"];

/** The calendar date right now in an IANA zone ("Europe/Dublin"). Falls back to UTC. */
export function todayIn(tz: string | undefined, now: Date = new Date()): IsoDate {
  try {
    const f = new Intl.DateTimeFormat("en-CA", { timeZone: tz || "UTC", year: "numeric", month: "2-digit", day: "2-digit" });
    const p = Object.fromEntries(f.formatToParts(now).map((x) => [x.type, x.value]));
    return `${p.year}-${p.month}-${p.day}`;
  } catch {
    return now.toISOString().slice(0, 10);
  }
}

/**
 * The zone's offset at local noon on that date, as "UTC+1" / "UTC−5" / "UTC+5:30" / "UTC+0".
 * Noon keeps it clear of the DST switch at 01:00–03:00.
 */
export function utcOffsetLabel(tz: string | undefined, iso: IsoDate): string | null {
  if (!tz) return null;
  try {
    const { y, m, d } = parts(iso);
    // Find the UTC instant whose local wall time in tz is 12:00 on that date (one correction step is enough).
    const guess = Date.UTC(y, m - 1, d, 12);
    const offsetMin = (at: number) => {
      const f = new Intl.DateTimeFormat("en-US", { timeZone: tz, hourCycle: "h23", year: "numeric", month: "2-digit", day: "2-digit", hour: "2-digit", minute: "2-digit" });
      const p = Object.fromEntries(f.formatToParts(new Date(at)).map((x) => [x.type, x.value]));
      const local = Date.UTC(Number(p.year), Number(p.month) - 1, Number(p.day), Number(p.hour) % 24, Number(p.minute));
      return Math.round((local - at) / 60000);
    };
    const off = offsetMin(guess - offsetMin(guess) * 60000);
    if (off === 0) return "UTC+0";
    const sign = off > 0 ? "+" : "−";
    const h = Math.floor(Math.abs(off) / 60);
    const mm = Math.abs(off) % 60;
    return `UTC${sign}${h}${mm ? `:${pad(mm)}` : ""}`;
  } catch {
    return null;
  }
}

const monthIndex = (word: string): number => {
  const w = word.toLowerCase().slice(0, 3);
  if (w === "sep" || word.toLowerCase().startsWith("sept")) return 9;
  const i = MONTHS.indexOf(w);
  return i >= 0 ? i + 1 : 0;
};

const fullYear = (y: number) => (y < 100 ? 2000 + y : y);

/**
 * Read a typed date. Accepts 2025-01-24, 24 Jan 2025, Jan 24 2025, 24 January 25, 24/01/2025,
 * 24.01.2025, "today", "yesterday", and "24 Jan" (the latest one that isn't after `today`).
 * Slashed dates are read day-first unless that can't be a date (01/24/2025 → 24 Jan).
 */
export function parseDate(input: string, today: IsoDate): IsoDate | null {
  const s = input.trim().toLowerCase().replace(/,/g, " ").replace(/\s+/g, " ");
  if (!s) return null;
  if (s === "today") return today;
  if (s === "yesterday") return addDays(today, -1);

  let m = s.match(/^(\d{4})-(\d{1,2})-(\d{1,2})$/);
  if (m) return check(+m[1], +m[2], +m[3]);

  m = s.match(/^(\d{1,2})[/.-](\d{1,2})[/.-](\d{2}|\d{4})$/);
  if (m) {
    const a = +m[1];
    const b = +m[2];
    const y = fullYear(+m[3]);
    if (a > 12 && b <= 12) return check(y, b, a); // 24/01/2025
    if (b > 12 && a <= 12) return check(y, a, b); // 01/24/2025
    return check(y, b, a); // day first
  }

  // 24 jan 2025 · 24th january 25 · 24 jan
  m = s.match(/^(\d{1,2})(?:st|nd|rd|th)? ([a-z]{3,9})\.?(?: (\d{2}|\d{4}))?$/);
  if (m && monthIndex(m[2])) return withYear(+m[1], monthIndex(m[2]), m[3], today);

  // jan 24 2025 · january 24th · jan 24
  m = s.match(/^([a-z]{3,9})\.? (\d{1,2})(?:st|nd|rd|th)?(?: (\d{2}|\d{4}))?$/);
  if (m && monthIndex(m[1])) return withYear(+m[2], monthIndex(m[1]), m[3], today);

  // 24jan2025 (METAR-style)
  m = s.match(/^(\d{1,2})([a-z]{3})(\d{2}|\d{4})$/);
  if (m && monthIndex(m[2])) return check(fullYear(+m[3]), monthIndex(m[2]), +m[1]);

  return null;
}

function check(y: number, m: number, d: number): IsoDate | null {
  return isValidDate(y, m, d) ? toIso(y, m, d) : null;
}

function withYear(d: number, m: number, year: string | undefined, today: IsoDate): IsoDate | null {
  if (year) return check(fullYear(+year), m, d);
  const t = parts(today);
  const thisYear = check(t.y, m, d);
  if (thisYear && thisYear <= today) return thisYear;
  return check(t.y - 1, m, d);
}

/** Monday-first weeks for a month grid: `null` pads the days outside the month. */
export function monthGrid(y: number, m: number): (IsoDate | null)[][] {
  const first = toIso(y, m, 1);
  const lead = (weekday(first) + 6) % 7;
  const cells: (IsoDate | null)[] = Array.from({ length: lead }, () => null);
  for (let d = 1; d <= daysInMonth(y, m); d++) cells.push(toIso(y, m, d));
  while (cells.length % 7) cells.push(null);
  const weeks: (IsoDate | null)[][] = [];
  for (let i = 0; i < cells.length; i += 7) weeks.push(cells.slice(i, i + 7));
  return weeks;
}
