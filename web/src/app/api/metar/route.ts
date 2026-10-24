// Live METAR for any station and day, from the Iowa Environmental Mesonet archive.
// GET /api/metar?station=EIDW&date=2025-12-09&limit=40
// → { station, date, limit, source, reports: [{ t, raw, dir, kt, gust }], windows: [{ start, end }] }
//
// Storm Bram at Dublin is bundled, so the demo's default view works even on bad venue Wi-Fi.
import { parseMetar, stormWindow } from "@/lib/metar";
import BRAM from "@/data/bram-metar.json";

type Report = { t: string; raw: string; dir: number | null; kt: number | null; gust: number | null };

const MERGE_GAP_MIN = 120; // a lull shorter than two hours is the same storm (R-1)

function respond(station: string, date: string, limit: number, reports: Report[], source: string, error?: string) {
  const windows = stormWindow(reports, limit, MERGE_GAP_MIN).map((w) => ({ start: w.start, end: w.end }));
  return Response.json({ station, date, limit, source, reports, windows, ...(error ? { error } : {}) });
}

export async function GET(request: Request) {
  const url = new URL(request.url);
  const station = (url.searchParams.get("station") ?? "EIDW").toUpperCase();
  const date = url.searchParams.get("date") ?? "2025-12-09";
  const limit = Number(url.searchParams.get("limit") ?? 40);

  if (!/^[A-Z0-9]{3,4}$/.test(station)) return Response.json({ error: "Station must be a 3–4 letter ICAO/FAA code" }, { status: 400 });
  const day = new Date(`${date}T00:00:00Z`);
  if (!/^\d{4}-\d{2}-\d{2}$/.test(date) || Number.isNaN(day.getTime()) || day.toISOString().slice(0, 10) !== date)
    return Response.json({ error: "Date must be a real YYYY-MM-DD" }, { status: 400 });
  if (!Number.isFinite(limit) || limit < 15 || limit > 90) return Response.json({ error: "Gust limit must be 15–90 kt" }, { status: 400 });

  const bundled = station === "EIDW" && date === "2025-12-09";
  const fallback = () => respond(station, date, limit, BRAM as Report[], "bundled (IEM archive, fetched 24 Oct 2026)");

  const next = new Date(day);
  next.setUTCDate(next.getUTCDate() + 1);
  const src =
    "https://mesonet.agron.iastate.edu/cgi-bin/request/asos.py?" +
    new URLSearchParams({
      station,
      data: "metar",
      sts: `${date}T00:00Z`,
      ets: `${next.toISOString().slice(0, 10)}T00:00Z`,
      tz: "Etc/UTC",
      format: "onlycomma",
      latlon: "no",
      missing: "M",
    }).toString() +
    "&report_type=3&report_type=4";

  try {
    const res = await fetch(src, { next: { revalidate: 3600 }, signal: AbortSignal.timeout(6000) });
    if (!res.ok) return bundled ? fallback() : respond(station, date, limit, [], "iem", `METAR archive answered ${res.status}`);
    const text = await res.text();
    const reports: Report[] = text
      .split("\n")
      .slice(1)
      .map((l) => l.split(","))
      .filter((c) => c.length >= 3 && c[2] && c[2] !== "M")
      .map((c) => {
        const raw = c.slice(2).join(",").trim();
        const m = parseMetar(raw);
        return { t: c[1].slice(11, 16), raw, dir: m.dir, kt: m.kt, gust: m.gust };
      });
    if (!reports.length) return bundled ? fallback() : respond(station, date, limit, [], "iem", "No METAR for that station and day");
    return respond(station, date, limit, reports, "iem");
  } catch {
    return bundled ? fallback() : respond(station, date, limit, [], "iem", "METAR archive unreachable");
  }
}
