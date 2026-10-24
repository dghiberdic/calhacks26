import type { ApiFetch } from "./client";

/**
 * Recorded mode (J9): serves the responses `web/scripts/record.mjs` saved to demo/recorded/, so the
 * Devpost build needs no backend. GETs map to `/recorded/<path>[__<query>].json`; writes replay the
 * response recorded for the same request, or answer with a plain message that this build is read-only.
 */
export function createRecordedFetch(): ApiFetch {
  return async (path, init) => {
    const method = (init.method ?? "GET").toUpperCase();
    const file = recordedFile(method, path);
    const res = await fetch(file);
    if (res.ok) return new Response(await res.text(), { status: 200, headers: { "Content-Type": "application/json" } });
    const message = method === "GET" ? "This page wasn't part of the recorded demo." : "The recorded demo is read-only for this action.";
    return new Response(JSON.stringify({ error: { code: "not_found", message } }), { status: 404, headers: { "Content-Type": "application/json" } });
  };
}

export function recordedFile(method: string, path: string) {
  const [route, query = ""] = path.split("?");
  const slug = route.replace(/^\//, "").replace(/[^A-Za-z0-9@._-]+/g, "_") || "root";
  const q = query ? `__${query.replace(/[^A-Za-z0-9@._=-]+/g, "_")}` : "";
  return `${import.meta.env.BASE_URL}recorded/${method.toLowerCase()}/${slug}${q}.json`;
}
