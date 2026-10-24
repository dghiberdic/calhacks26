// Live METAR for any station and day, from the Iowa Environmental Mesonet archive.
// GET /api/metar?station=EIDW&date=2025-12-09&limit=40
// → { station, date, reports: [{ t, raw, dir, kt, gust }], windows: [{ start, end }] }

type Report = { t: string; raw: string; dir: number | null; kt: number | null; gust: number | null };

function parseWind(raw: string) {
  const m = raw.match(/\b(\d{3}|VRB)(\d{2,3})(?:G(\d{2,3}))?(KT|MPS)\b/);
  if (!m) return { dir: null, kt: null, gust: null };
  const k = m[4] === "MPS" ? 1.944 : 1;
  return { dir: m[1] === "VRB" ? null : Number(m[1]), kt: Math.round(Number(m[2]) * k), gust: m[3] ? Math.round(Number(m[3]) * k) : null };
}

const mins = (t: string) => Number(t.slice(0, 2)) * 60 + Number(t.slice(3, 5));
const hhmm = (m: number) => `${String(Math.floor(m / 60) % 24).padStart(2, "0")}:${String(m % 60).padStart(2, "0")}`;

/** Contiguous spans where gusts (or mean wind) reach the limit; dips under two hours are merged. */
function stormWindows(reports: Report[], limit: number) {
  const hits = reports.filter((r) => (r.gust ?? r.kt ?? 0) >= limit).map((r) => mins(r.t));
  const out: { start: number; end: number }[] = [];
  for (const m of hits) {
    const last = out[out.length - 1];
    if (last && m - last.end <= 120) last.end = m;
    else out.push({ start: m, end: m });
  }
  return out.map((w) => ({ start: hhmm(w.start), end: hhmm(Math.min(w.end + 30, 24 * 60 - 1)) }));
}

export async function GET(request: Request) {
  const url = new URL(request.url);
  const station = (url.searchParams.get("station") ?? "EIDW").toUpperCase().replace(/[^A-Z0-9]/g, "").slice(0, 4);
  const date = url.searchParams.get("date") ?? "2025-12-09";
  const limit = Math.max(10, Math.min(90, Number(url.searchParams.get("limit") ?? 40)));
  if (!/^\d{4}-\d{2}-\d{2}$/.test(date)) return Response.json({ error: "Use YYYY-MM-DD" }, { status: 400 });

  const next = new Date(`${date}T00:00:00Z`);
  next.setUTCDate(next.getUTCDate() + 1);
  const ets = next.toISOString().slice(0, 10);
  const src =
    "https://mesonet.agron.iastate.edu/cgi-bin/request/asos.py?" +
    new URLSearchParams({ station, data: "metar", sts: `${date}T00:00Z`, ets: `${ets}T00:00Z`, tz: "Etc/UTC", format: "onlycomma", latlon: "no", missing: "M" }).toString() +
    "&report_type=3&report_type=4";

  try {
    const res = await fetch(src, { next: { revalidate: 3600 } });
    if (!res.ok) return Response.json({ station, date, reports: [], windows: [], error: `METAR archive answered ${res.status}` });
    const text = await res.text();
    const reports: Report[] = text
      .split("\n")
      .slice(1)
      .map((l) => l.split(","))
      .filter((c) => c.length >= 3 && c[2] && c[2] !== "M")
      .map((c) => {
        const raw = c.slice(2).join(",").trim();
        return { t: c[1].slice(11, 16), raw, ...parseWind(raw) };
      });
    if (!reports.length) return Response.json({ station, date, reports, windows: [], error: "No METAR for that station and day" });
    return Response.json({ station, date, limit, reports, windows: stormWindows(reports, limit) });
  } catch {
    return Response.json({ station, date, reports: [], windows: [], error: "METAR archive unreachable" }, { status: 502 });
  }
}
