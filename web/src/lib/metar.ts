// Dependency-free METAR/SPECI decoder plus a "storm window" finder, shared by the hero (static
// public/data/<storm>/metar-*.json) and the live judge's desk. Pure functions: safe in server and
// client components, route handlers and Node scripts (npx tsx scripts/metar-selftest.ts).
//
// Decodes the ICAO body (wind, visibility, present weather, cloud, temp, QNH) and stops at the
// TREND (NOSIG/BECMG/TEMPO) or RMK so forecast groups never leak into observed values.

export interface Metar {
  /** Report as given: whitespace collapsed, trailing "=" removed. */
  raw: string;
  station: string | null;
  /** Day of month from the DDHHMMZ group. */
  day: number | null;
  /** Observation time "HH:MM" UTC from the DDHHMMZ group. */
  t: string | null;
  speci: boolean;
  cor: boolean;
  auto: boolean;
  nil: boolean;
  /** Mean wind direction, ° true; null for VRB or missing. */
  dir: number | null;
  /** Mean wind speed, kt (MPS and KMH converted). */
  kt: number | null;
  /** Gust, kt; null when the report has no G group. */
  gust: number | null;
  /** Extremes of a variable direction group such as 130V200. */
  varDir: [number, number] | null;
  /** Prevailing visibility, m. 9999 = 10 km or more (CAVOK → 9999). */
  vis: number | null;
  cavok: boolean;
  /** Present weather groups, e.g. ["-RADZ"], ["+SHRA", "VCTS"]. */
  wx: string[];
  clouds: { cover: string; baseFt: number | null; type: string | null }[];
  temp: number | null;
  dew: number | null;
  /** QNH, hPa (A-groups converted from inHg). */
  qnh: number | null;
  /** Recent weather (RE groups, without the RE prefix), e.g. ["SHRA"]. */
  recent: string[];
  /** Wind-shear groups: runway designators ("R28L") or "ALL RWY". */
  windshear: string[];
  /** TREND text, e.g. "NOSIG" or "TEMPO BKN012". */
  trend: string | null;
}

const DESC = "MI|PR|BC|DR|BL|SH|TS|FZ";
const PHEN = "DZ|RA|SN|SG|IC|PL|GR|GS|UP|BR|FG|FU|VA|DU|SA|HZ|PY|PO|SQ|FC|SS|DS";
const WX = new RegExp(`^(?:[-+]|VC)?(?:(?:${DESC})(?:${PHEN})*|(?:${PHEN})+)$`);
const WIND = /^(\d{3}|VRB|\/{3})(P?\d{2,3}|\/\/)(?:G(P?\d{2,3}))?(KT|MPS|KMH)$/;
const TIME = /^(\d{2})(\d{2})(\d{2})Z$/;
const STATION = /^[A-Z][A-Z0-9]{3}$/;
const CLOUD = /^(FEW|SCT|BKN|OVC|VV)(\d{3}|\/{3})(CB|TCU|\/{3})?$/;
const TEMP = /^(M?\d{2}|\/\/)\/(M?\d{2}|\/\/)?$/;
const TREND = new Set(["NOSIG", "BECMG", "TEMPO"]);
const TO_KT = { KT: 1, MPS: 1.943844, KMH: 0.539957 } as const;

const num = (s: string | undefined) => (s && /\d/.test(s) ? parseInt(s.replace(/\D/g, ""), 10) : null);
const temp = (s: string | undefined) => (s && s !== "//" ? (s[0] === "M" ? -1 : 1) * parseInt(s.replace("M", ""), 10) : null);
/** "1/2" → 0.5, "3" → 3 */
const frac = (s: string) => s.split(" ").reduce((a, p) => a + (p.includes("/") ? +p.split("/")[0] / +p.split("/")[1] : +p), 0);

export function parseMetar(input: string): Metar {
  const raw = input.trim().replace(/\s+/g, " ").replace(/=$/, "").trim();
  const m: Metar = {
    raw, station: null, day: null, t: null, speci: false, cor: false, auto: false, nil: false,
    dir: null, kt: null, gust: null, varDir: null, vis: null, cavok: false, wx: [], clouds: [],
    temp: null, dew: null, qnh: null, recent: [], windshear: [], trend: null,
  };
  const tok = raw.split(" ");
  let i = 0;
  // header: [METAR|SPECI] [COR] ICAO DDHHMMZ — IEM puts COR before the station
  for (; i < tok.length && m.day === null; i++) {
    const w = tok[i];
    if (w === "SPECI") m.speci = true;
    else if (w === "COR" || w === "CCA") m.cor = true;
    else if (TIME.test(w)) {
      const [, d, h, mi] = TIME.exec(w)!;
      m.day = +d;
      m.t = `${h}:${mi}`;
    } else if (w !== "METAR" && STATION.test(w) && !m.station) m.station = w;
  }
  let afterQnh = false;
  for (; i < tok.length; i++) {
    const w = tok[i];
    if (w === "RMK") break;
    if (TREND.has(w)) {
      m.trend = tok.slice(i).join(" ").split(" RMK")[0];
      break;
    }
    if (w === "NIL") m.nil = true;
    else if (w === "AUTO") m.auto = true;
    else if (w === "COR") m.cor = true;
    else if (m.kt === null && m.dir === null && WIND.test(w)) {
      const [, d, s, g, unit] = WIND.exec(w)!;
      const k = TO_KT[unit as keyof typeof TO_KT];
      m.dir = d === "VRB" || d === "///" ? null : +d;
      m.kt = num(s) === null ? null : Math.round(num(s)! * k);
      m.gust = g ? Math.round(num(g)! * k) : null;
    } else if (/^\d{3}V\d{3}$/.test(w)) m.varDir = [+w.slice(0, 3), +w.slice(4)];
    else if (w === "CAVOK") {
      m.cavok = true;
      m.vis = 9999;
    } else if (m.vis === null && /^\d{4}(NDV)?$/.test(w)) m.vis = +w.slice(0, 4);
    else if (m.vis === null && /^[MP]?\d+(\/\d+)?SM$/.test(w)) {
      // US statute miles, possibly "1 1/2SM" split over two tokens; P6SM etc. → 9999
      const whole = /^\d$/.test(tok[i - 1] ?? "") ? `${tok[i - 1]} ` : "";
      const metres = frac(whole + w.replace(/^[MP]|SM$/g, "")) * 1609.344;
      m.vis = w.startsWith("P") || metres >= 9999 ? 9999 : Math.round(metres);
    } else if (/^\d{4}(N|NE|E|SE|S|SW|W|NW)$/.test(w) || /^R\d{2}[LCR]?\/[PM]?\d{4}/.test(w)) {
      // directional minimum visibility / RVR — not needed downstream
    } else if (!afterQnh && WX.test(w)) m.wx.push(w);
    else if (CLOUD.test(w)) {
      const [, cover, base, type] = CLOUD.exec(w)!;
      m.clouds.push({ cover, baseFt: base.includes("/") ? null : +base * 100, type: type && type !== "///" ? type : null });
    } else if (/^(NSC|NCD|SKC|CLR)$/.test(w)) m.clouds.push({ cover: w, baseFt: null, type: null });
    else if (TEMP.test(w) && m.temp === null) {
      const [, t, d] = TEMP.exec(w)!;
      m.temp = temp(t);
      m.dew = temp(d);
    } else if (/^Q\d{4}$/.test(w)) {
      m.qnh = +w.slice(1);
      afterQnh = true;
    } else if (/^A\d{4}$/.test(w)) {
      m.qnh = Math.round((+w.slice(1) / 100) * 33.8639 * 10) / 10;
      afterQnh = true;
    } else if (/^RE[A-Z]{2,}$/.test(w)) m.recent.push(w.slice(2));
    else if (w === "WS") {
      if (tok[i + 1] === "ALL" && tok[i + 2] === "RWY") {
        m.windshear.push("ALL RWY");
        i += 2;
      } else if (/^R\d{2}[LCR]?$/.test(tok[i + 1] ?? "")) m.windshear.push(tok[++i]);
    }
  }
  return m;
}

// ── storm windows ─────────────────────────────────────────────────────────────────────────────

/** Anything with a time and a gust: parsed Metar, the static JSON rows, or a live API record. */
export interface WindowReport {
  t: string | null;
  gust: number | null;
  kt?: number | null;
  day?: number | null;
  /** Absolute time (ISO string, epoch ms or Date). Preferred over day/t when present. */
  time?: string | number | Date;
}

export interface StormWindow {
  /** First report at/above the limit, "HH:MM" UTC. */
  start: string;
  /** First report back below the limit (a METAR stands until superseded); = last when ongoing. */
  end: string;
  /** Last report at/above the limit. */
  last: string;
  /** Minutes on the series' own timeline (absolute when `time` is given, else day·1440 + h·60 + m). */
  startMin: number;
  endMin: number;
  durationMin: number;
  peakGust: number;
  peakAt: string;
  /** Reports at/above the limit inside the window. */
  reports: number;
  /** Still at/above the limit in the latest report. */
  ongoing: boolean;
}

const hm = (t: string | null) => (t && /^\d{2}:\d{2}$/.test(t) ? +t.slice(0, 2) * 60 + +t.slice(3) : null);

/**
 * Contiguous spells where the gust (or the mean wind, if higher / no G group) is ≥ gustLimitKt.
 * A spell opens at the first report at/above the limit and closes at the first report back below
 * it; spells separated by a lull shorter than mergeGapMin (end of one → start of the next) merge.
 * Rows without `time` are read in order and unwrapped across midnight / month ends.
 */
export function stormWindow(reports: readonly WindowReport[], gustLimitKt = 40, mergeGapMin = 60): StormWindow[] {
  let prev = -Infinity;
  let offset = 0;
  const rows = reports
    .map((r) => {
      let at: number | null = null;
      let label = r.t;
      if (r.time != null) {
        const d = new Date(r.time);
        at = Math.round(d.getTime() / 60000);
        label = d.toISOString().slice(11, 16);
      } else {
        const mins = hm(r.t);
        if (mins !== null) {
          const base = (r.day ?? 0) * 1440 + mins;
          if (base + offset < prev - 720) offset += r.day != null ? Math.ceil((prev - base - offset) / 1440) * 1440 : 1440;
          at = base + offset;
          prev = at;
        }
      }
      const peak = Math.max(r.gust ?? -Infinity, r.kt ?? -Infinity);
      return { at, label: label ?? "", peak };
    })
    .filter((r): r is { at: number; label: string; peak: number } => r.at !== null && Number.isFinite(r.at))
    .sort((a, b) => a.at - b.at);

  type Open = Omit<StormWindow, "end" | "endMin" | "durationMin" | "ongoing"> & { lastMin: number; endAt: number | null; endLabel: string };
  const out: Open[] = [];
  let cur: Open | null = null;
  for (const r of rows) {
    if (r.peak >= gustLimitKt) {
      if (cur && (cur.endAt === null || r.at - cur.endAt < mergeGapMin)) {
        cur.endAt = null;
        cur.last = r.label;
        cur.lastMin = r.at;
        cur.reports++;
        if (r.peak > cur.peakGust) [cur.peakGust, cur.peakAt] = [r.peak, r.label];
      } else {
        cur = { start: r.label, startMin: r.at, last: r.label, lastMin: r.at, endAt: null, endLabel: "", peakGust: r.peak, peakAt: r.label, reports: 1 };
        out.push(cur);
      }
    } else if (cur && cur.endAt === null) {
      cur.endAt = r.at;
      cur.endLabel = r.label;
    }
  }
  return out.map(({ lastMin, endAt, endLabel, ...w }) => ({
    ...w,
    end: endAt === null ? w.last : endLabel,
    endMin: endAt ?? lastMin,
    durationMin: (endAt ?? lastMin) - w.startMin,
    ongoing: endAt === null,
  }));
}
