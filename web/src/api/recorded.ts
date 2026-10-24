import type { ApiFetch } from "./client";
import { currentRole } from "./client";
import type { TraceEvent } from "./types";

/**
 * Recorded mode (J9): replays what `web/scripts/record.mjs` saved to demo/recorded/, so the Devpost build
 * needs no backend and can't go down. GETs come from the current step of the demo for the current role;
 * a scripted write returns its recorded response and, if it is the write that unlocks the next step
 * (a ruling confirmed, the month-end run), moves every screen forward to that step.
 */

type Manifest = { format?: number; recorded_at: string; base: string; roles: string[]; steps: { name: string; unlock: { method: string; path: string } | null }[] };
type Recorded = { status: number; json: unknown };

const ROOT = `${import.meta.env.BASE_URL}recorded`;
const STEP_KEY = "stormcheck.recorded-step";
let manifest: Manifest | null = null;
let manifestLoad: Promise<Manifest | null> | null = null;

export function slug(path: string) {
  const [route, query = ""] = path.split("?");
  const s = route.replace(/^\//, "").replace(/[^A-Za-z0-9@._-]+/g, "_") || "root";
  return query ? `${s}__${query.replace(/[^A-Za-z0-9@._=-]+/g, "_")}` : s;
}

async function bodyHash(body: string) {
  const digest = await crypto.subtle.digest("SHA-256", new TextEncoder().encode(body));
  return [...new Uint8Array(digest)].map((b) => b.toString(16).padStart(2, "0")).join("").slice(0, 10);
}

function getStep() {
  try {
    return Number(sessionStorage.getItem(STEP_KEY) ?? 0) || 0;
  } catch {
    return 0;
  }
}
function setStep(step: number) {
  try {
    sessionStorage.setItem(STEP_KEY, String(step));
  } catch {
    /* the step then lasts until reload */
  }
}

/** Back to the start of the recorded demo (POST /reset in recorded mode). */
export const resetRecorded = () => setStep(0);

async function loadManifest() {
  if (manifest) return manifest;
  manifestLoad ??= fetch(`${ROOT}/manifest.json`)
    .then((r) => (r.ok ? (r.json() as Promise<Manifest>) : null))
    .catch(() => null);
  manifest = await manifestLoad;
  return manifest;
}

async function getJson(url: string): Promise<unknown | undefined> {
  try {
    const res = await fetch(url);
    if (!res.ok) return undefined;
    const text = await res.text();
    // Static hosts answer unknown paths with index.html; only JSON counts.
    if (text.trimStart().startsWith("<")) return undefined;
    return JSON.parse(text);
  } catch {
    return undefined;
  }
}

// Format 2: each step and role has a small index (slug → blob); bodies are stored once in blobs/<hash>.json.
const indexes = new Map<string, Promise<Record<string, string> | undefined>>();
async function fromIndex(step: number, role: string, key: string): Promise<unknown | undefined> {
  const id = `${step}/${role}`;
  if (!indexes.has(id)) indexes.set(id, getJson(`${ROOT}/step-${step}/${role}.json`) as Promise<Record<string, string> | undefined>);
  const hash = (await indexes.get(id))?.[key];
  return hash ? getJson(`${ROOT}/blobs/${hash}.json`) : undefined;
}

const json = (status: number, body: unknown) => new Response(JSON.stringify(body), { status, headers: { "Content-Type": "application/json" } });
const notRecorded = (message: string) => json(404, { error: { code: "not_found", message } });

export function createRecordedFetch(): ApiFetch {
  return async (path, init) => {
    const m = await loadManifest();
    if (!m) return json(503, { error: { code: "upstream", message: "The recorded demo files are missing from this build." } });
    const method = (init.method ?? "GET").toUpperCase();
    const role = currentRole();
    const step = Math.min(getStep(), m.steps.length - 1);

    if (method === "GET") {
      // The live feed polls /trace?since=N: serve the step's whole trace and filter it here.
      const tracePoll = path.match(/^\/trace\?since=(\d+)/);
      const lookup = tracePoll ? "/trace?since=0" : path;
      for (let s = step; s >= 0; s--) {
        for (const r of [role, "judge"]) {
          const body = m.format === 2 ? await fromIndex(s, r, slug(lookup)) : await getJson(`${ROOT}/step-${s}/${r}/get/${slug(lookup)}.json`);
          if (body === undefined) continue;
          if (tracePoll) return json(200, (body as TraceEvent[]).filter((e) => e.seq > Number(tracePoll[1])));
          return json(200, body);
        }
      }
      return notRecorded("This view wasn't part of the recorded demo.");
    }

    // Writes
    const body = typeof init.body === "string" ? init.body : "";
    if (path === "/reset") {
      resetRecorded();
      return json(200, { ok: true });
    }
    if (path === "/clock") return json(200, JSON.parse(body || "{}"));
    if (path === "/session") {
      const asRole = (JSON.parse(body || "{}") as { role?: string }).role ?? "judge";
      const rec = (await getJson(`${ROOT}/posts/${asRole}/session.json`)) as Recorded | undefined;
      return rec ? json(rec.status, rec.json) : json(200, { token: `recorded.${asRole}`, session: { principal: `person:${asRole}`, role: asRole, name: asRole, issued_at: m.recorded_at } });
    }

    const base = `${ROOT}/posts/${role}/${slug(path)}`;
    const candidates = [`${base}__${await bodyHash(body)}.json`];
    if (/\/challenge$/.test(path)) candidates.push(`${base}__${/airbus|manufacturer|defect|batch|notice/i.test(body) ? "new_legal_pattern" : "assertion"}.json`);
    if (path === "/desk") {
      const d = JSON.parse(body || "{}") as { icao?: string; date?: string };
      candidates.push(`${base}__${(d.icao ?? "").toUpperCase()}_${d.date ?? ""}.json`);
    }
    // Desk days and injections replay only what was recorded; everything else falls back to the route's response.
    if (path !== "/desk" && path !== "/inject") candidates.push(`${base}.json`);

    for (const url of candidates) {
      const rec = (await getJson(url)) as Recorded | undefined;
      if (!rec) continue;
      const unlocks = m.steps.findIndex((s) => s.unlock && s.unlock.method === method && s.unlock.path === path);
      if (unlocks > step && rec.status < 400) setStep(unlocks);
      return json(rec.status, rec.json);
    }
    if (path === "/desk") return json(422, { error: { code: "validation", message: "This recorded build has Dublin on 24 and 26 Jan 2025. The live build takes any airport and date." } });
    if (path === "/inject") return json(422, { error: { code: "validation", message: "This recorded build replays the 8 rehearsed scenarios. The live build reads anything you paste." } });
    return notRecorded("This action wasn't part of the recorded demo.");
  };
}
