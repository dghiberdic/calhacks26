// Small pure helpers shared by the mock world: time arithmetic, a real (synchronous) SHA-256 for
// commit hashes, the storm-window definition from CONTRACTS §1 / plan §1.2, and € formatting for prose.
import type { InWindow, MetarObs, StormWindow } from "@/api/types";

// ---------- time ----------
const MIN = 60_000;

/** "2025-01-24T16:30:00Z" ± minutes, always serialised with `Z` and no milliseconds. */
export function addMin(at: string, minutes: number): string {
  return isoZ(Date.parse(at) + minutes * MIN);
}

export function isoZ(ms: number): string {
  return new Date(ms).toISOString().replace(/\.\d{3}Z$/, "Z");
}

/** Whole minutes from a to b (b − a). */
export function minutesBetween(a: string, b: string): number {
  return Math.round((Date.parse(b) - Date.parse(a)) / MIN);
}

/** "2025-01-24" + "16:30" → "2025-01-24T16:30:00Z". */
export function utc(date: string, hhmm: string): string {
  return `${date}T${hhmm}:00Z`;
}

/** "16:30Z" from an ISO time, for prose. */
export function hhmmZ(at: string): string {
  return `${at.slice(11, 16)}Z`;
}

// ---------- money (prose only; amounts in payloads are always integer cents) ----------
export function eur(cents: number): string {
  const neg = cents < 0;
  const abs = Math.abs(cents);
  const whole = Math.floor(abs / 100);
  const frac = abs % 100;
  const body = `€${whole.toLocaleString("en-US")}${frac ? `.${String(frac).padStart(2, "0")}` : ""}`;
  return neg ? `(${body})` : body;
}

// ---------- hashing ----------
const K = new Uint32Array([
  0x428a2f98, 0x71374491, 0xb5c0fbcf, 0xe9b5dba5, 0x3956c25b, 0x59f111f1, 0x923f82a4, 0xab1c5ed5, 0xd807aa98, 0x12835b01, 0x243185be,
  0x550c7dc3, 0x72be5d74, 0x80deb1fe, 0x9bdc06a7, 0xc19bf174, 0xe49b69c1, 0xefbe4786, 0x0fc19dc6, 0x240ca1cc, 0x2de92c6f, 0x4a7484aa,
  0x5cb0a9dc, 0x76f988da, 0x983e5152, 0xa831c66d, 0xb00327c8, 0xbf597fc7, 0xc6e00bf3, 0xd5a79147, 0x06ca6351, 0x14292967, 0x27b70a85,
  0x2e1b2138, 0x4d2c6dfc, 0x53380d13, 0x650a7354, 0x766a0abb, 0x81c2c92e, 0x92722c85, 0xa2bfe8a1, 0xa81a664b, 0xc24b8b70, 0xc76c51a3,
  0xd192e819, 0xd6990624, 0xf40e3585, 0x106aa070, 0x19a4c116, 0x1e376c08, 0x2748774c, 0x34b0bcb5, 0x391c0cb3, 0x4ed8aa4a, 0x5b9cca4f,
  0x682e6ff3, 0x748f82ee, 0x78a5636f, 0x84c87814, 0x8cc70208, 0x90befffa, 0xa4506ceb, 0xbef9a3f7, 0xc67178f2,
]);

/** SHA-256 of the UTF-8 bytes of `text`, as 64 lowercase hex chars. Synchronous so fixtures can be built at import time. */
export function sha256(text: string): string {
  const bytes = new TextEncoder().encode(text);
  const bitLen = bytes.length * 8;
  const padded = new Uint8Array(((bytes.length + 9 + 63) >> 6) << 6);
  padded.set(bytes);
  padded[bytes.length] = 0x80;
  const view = new DataView(padded.buffer);
  view.setUint32(padded.length - 8, Math.floor(bitLen / 0x100000000));
  view.setUint32(padded.length - 4, bitLen >>> 0);
  const h = new Uint32Array([0x6a09e667, 0xbb67ae85, 0x3c6ef372, 0xa54ff53a, 0x510e527f, 0x9b05688c, 0x1f83d9ab, 0x5be0cd19]);
  const w = new Uint32Array(64);
  const rotr = (x: number, n: number) => (x >>> n) | (x << (32 - n));
  for (let off = 0; off < padded.length; off += 64) {
    for (let i = 0; i < 16; i++) w[i] = view.getUint32(off + i * 4);
    for (let i = 16; i < 64; i++) {
      const s0 = rotr(w[i - 15], 7) ^ rotr(w[i - 15], 18) ^ (w[i - 15] >>> 3);
      const s1 = rotr(w[i - 2], 17) ^ rotr(w[i - 2], 19) ^ (w[i - 2] >>> 10);
      w[i] = (w[i - 16] + s0 + w[i - 7] + s1) >>> 0;
    }
    let [a, b, c, d, e, f, g, hh] = h;
    for (let i = 0; i < 64; i++) {
      const S1 = rotr(e, 6) ^ rotr(e, 11) ^ rotr(e, 25);
      const ch = (e & f) ^ (~e & g);
      const t1 = (hh + S1 + ch + K[i] + w[i]) >>> 0;
      const S0 = rotr(a, 2) ^ rotr(a, 13) ^ rotr(a, 22);
      const maj = (a & b) ^ (a & c) ^ (b & c);
      const t2 = (S0 + maj) >>> 0;
      hh = g;
      g = f;
      f = e;
      e = (d + t1) >>> 0;
      d = c;
      c = b;
      b = a;
      a = (t1 + t2) >>> 0;
    }
    h[0] = (h[0] + a) >>> 0;
    h[1] = (h[1] + b) >>> 0;
    h[2] = (h[2] + c) >>> 0;
    h[3] = (h[3] + d) >>> 0;
    h[4] = (h[4] + e) >>> 0;
    h[5] = (h[5] + f) >>> 0;
    h[6] = (h[6] + g) >>> 0;
    h[7] = (h[7] + hh) >>> 0;
  }
  return Array.from(h, (x) => x.toString(16).padStart(8, "0")).join("");
}

/** Canonical JSON (sorted keys), the shape the backend hashes with orjson OPT_SORT_KEYS. */
export function canonical(value: unknown): string {
  if (value === null || typeof value !== "object") return JSON.stringify(value);
  if (Array.isArray(value)) return `[${value.map(canonical).join(",")}]`;
  const entries = Object.entries(value as Record<string, unknown>)
    .filter(([, v]) => v !== undefined)
    .sort(([a], [b]) => (a < b ? -1 : a > b ? 1 : 0));
  return `{${entries.map(([k, v]) => `${JSON.stringify(k)}:${canonical(v)}`).join(",")}}`;
}

export const hashOf = (value: unknown) => sha256(canonical(value));

// ---------- storm windows (CONTRACTS §1 StormWindow.definition; plan §1.2) ----------
export const WINDOW_DEFINITION = "gust>=35kt or sknt>=30kt or vsby<0.5sm or wx in {SN,FZ,TS,GR}; gaps<2h merged";

export function qualifies(o: MetarObs): boolean {
  if ((o.gust ?? 0) >= 35) return true;
  if ((o.sknt ?? 0) >= 30) return true;
  if (o.vsby_sm !== null && o.vsby_sm !== undefined && o.vsby_sm < 0.5) return true;
  return /SN|FZ|TS|GR/.test(o.wxcodes ?? "");
}

/**
 * Contiguous qualifying obs, merging gaps strictly under 2 h. `obs_count` counts the qualifying obs
 * inside each window (judgment call: not every obs between start and end). Computed from the data, never hard-coded.
 */
export function stormWindows(obs: MetarObs[], station: string): StormWindow[] {
  const flagged = [...obs].filter(qualifies).sort((a, b) => Date.parse(a.valid) - Date.parse(b.valid));
  const out: StormWindow[] = [];
  for (const o of flagged) {
    const last = out[out.length - 1];
    if (last && minutesBetween(last.end, o.valid) < 120) {
      last.end = o.valid;
      last.peak_gust_kt = Math.max(last.peak_gust_kt, o.gust ?? o.sknt ?? 0);
      last.obs_count = (last.obs_count ?? 0) + 1;
    } else {
      out.push({ station, start: o.valid, end: o.valid, peak_gust_kt: o.gust ?? o.sknt ?? 0, definition: WINDOW_DEFINITION, obs_count: 1 });
    }
  }
  return out;
}

/**
 * Where time `t` sits against the windows at a station: `in` when inside a window, `out` otherwise,
 * `unknown` when no obs lies within ±60 min. `margin_min` = whole minutes to the nearest window edge
 * (always ≥ 0; `pos` says which side), null when there is no window at all.
 */
export function position(obs: MetarObs[], windows: StormWindow[], t: string): { pos: InWindow; margin_min: number | null } {
  const near = obs.some((o) => Math.abs(minutesBetween(o.valid, t)) <= 60);
  if (!near) return { pos: "unknown", margin_min: null };
  let best: number | null = null;
  for (const w of windows) {
    const inside = Date.parse(t) >= Date.parse(w.start) && Date.parse(t) <= Date.parse(w.end);
    if (inside) return { pos: "in", margin_min: Math.min(minutesBetween(w.start, t), minutesBetween(t, w.end)) };
    const m = Math.min(Math.abs(minutesBetween(w.end, t)), Math.abs(minutesBetween(t, w.start)));
    if (best === null || m < best) best = m;
  }
  return { pos: "out", margin_min: best };
}

/** The obs nearest to `t` (for quoting a METAR line as evidence). */
export function nearestObs(obs: MetarObs[], t: string): MetarObs {
  return obs.reduce((a, b) => (Math.abs(minutesBetween(b.valid, t)) < Math.abs(minutesBetween(a.valid, t)) ? b : a));
}

/** Deterministic pseudo-random in [0, 1) from a string seed (mulberry32 over a string hash). */
export function seeded(seed: string): () => number {
  let s = parseInt(sha256(seed).slice(0, 8), 16) >>> 0;
  return () => {
    s = (s + 0x6d2b79f5) >>> 0;
    let t = s;
    t = Math.imul(t ^ (t >>> 15), t | 1);
    t ^= t + Math.imul(t ^ (t >>> 7), t | 61);
    return ((t ^ (t >>> 14)) >>> 0) / 4294967296;
  };
}

export function clone<T>(value: T): T {
  return structuredClone(value);
}
