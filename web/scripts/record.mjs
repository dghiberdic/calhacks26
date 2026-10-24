// Records the demo against a running server so the Devpost build can replay it with no backend (J9).
//
//   node scripts/record.mjs                        # against http://localhost:8000 (make dev / make demo)
//   node scripts/record.mjs --base http://localhost:8001 --out ../demo/recorded
//
// What it saves (demo/recorded/):
//   manifest.json                       steps, the write that unlocks each step, roles, when/where recorded
//   step-<n>/<role>/get/<slug>.json     every GET each role makes on each screen, at each step of the demo
//   posts/<role>/<slug>[__<hash>].json  the response (status + body) to each scripted write
// Steps follow plan §4: baseline → Claims Lead rules on Q1 → Legal on the knock-on returns → Controller
// rejects the Isha release → February month-end. The recorded build advances a step when the presenter
// performs that step's write, so a click-through tells the same story as the live demo.
import { createHash } from "node:crypto";
import { mkdirSync, rmSync, writeFileSync } from "node:fs";
import { join, resolve } from "node:path";

const arg = (name, fallback) => {
  const i = process.argv.indexOf(`--${name}`);
  return i > 0 ? process.argv[i + 1] : fallback;
};
const BASE = arg("base", "http://localhost:8000").replace(/\/$/, "");
const OUT = resolve(arg("out", "../demo/recorded"));
const ROLES = ["judge", "claims_lead", "legal", "controller", "ops", "cfo"];
const NAMES = { judge: "Judge", claims_lead: "Claims Lead", legal: "Legal", controller: "Controller", ops: "Ops", cfo: "CFO" };

export const slug = (path) => {
  const [route, query = ""] = path.split("?");
  const s = route.replace(/^\//, "").replace(/[^A-Za-z0-9@._-]+/g, "_") || "root";
  return query ? `${s}__${query.replace(/[^A-Za-z0-9@._=-]+/g, "_")}` : s;
};
export const bodyHash = (body) => createHash("sha256").update(body ?? "").digest("hex").slice(0, 10);

const tokens = {};
async function call(method, path, { role = "judge", body } = {}) {
  const headers = { Accept: "application/json" };
  if (tokens[role]) headers.Authorization = `Bearer ${tokens[role]}`;
  if (body !== undefined) headers["Content-Type"] = "application/json";
  const res = await fetch(`${BASE}/api${path}`, { method, headers, body: body === undefined ? undefined : JSON.stringify(body) });
  const text = await res.text();
  let json = null;
  try {
    json = JSON.parse(text);
  } catch {
    json = { error: { code: "upstream", message: text.slice(0, 200) } };
  }
  return { status: res.status, json };
}

function save(file, data) {
  mkdirSync(join(file, ".."), { recursive: true });
  writeFileSync(file, JSON.stringify(data));
}

let files = 0;
async function snapshot(step) {
  // Discover what to fetch from the API itself: storms → runs → flights, journals → audits, …
  const storms = (await call("GET", "/storms")).json ?? [];
  const runs = [];
  for (const s of storms) runs.push((await call("GET", `/storms/${encodeURIComponent(s.id)}`)).json);
  const flightIds = [...new Set(runs.flatMap((r) => (r?.flights ?? []).map((f) => f.flight.id)))];
  const journal = (await call("GET", "/books/journal")).json ?? [];
  const periods = [...new Set(["2025-01", "2025-02", ...journal.map((j) => j.period)])];
  const blameTargets = [...new Set([...flightIds.slice(0, 40), ...journal.map((j) => j.id), ...runs.flatMap((r) => (r?.questions ?? []).map((q) => q.id))])];

  const shared = [
    "/health",
    "/storms",
    ...storms.map((s) => `/storms/${encodeURIComponent(s.id)}`),
    ...flightIds.map((id) => `/flights/${encodeURIComponent(id)}`),
    "/rules",
    "/trace?since=0",
    "/commits?limit=100",
    ...blameTargets.map((t) => `/blame?target=${encodeURIComponent(t)}`),
    ...journal.map((j) => `/audit/${encodeURIComponent(j.id)}`),
    ...periods.map((p) => `/books/rollforward?period=${p}`),
    ...storms.map((s) => `/books/estimate?cohort=${encodeURIComponent(s.id)}`),
    "/books/journal",
    ...periods.map((p) => `/books/journal?period=${p}`),
    ...["long_haul_gt3500", "medium_1500_3500", "short_le1500"].map((s) => `/books/curve?segment=${s}`),
    "/books/cfo",
    "/books/invariants",
    "/access/matrix",
    "/access/log",
    "/controls",
    "/injections",
    "/eval",
  ];
  const scoped = ["/questions?status=open", "/questions?status=answered", "/questions?status=all"];

  for (const role of ROLES) {
    // Role-scoped and redacted responses differ per role; everything is saved per role so the replay is exact.
    for (const path of [...shared, ...scoped]) {
      const { status, json } = await call("GET", path, { role });
      if (status === 200) {
        save(join(OUT, `step-${step}`, role, "get", `${slug(path)}.json`), json);
        files += 1;
      }
    }
  }
  return { storms, runs };
}

async function post(role, path, body, { key } = {}) {
  const res = await call("POST", path, { role, body });
  // Saved three ways so the replay can match it: the exact body (hash), a readable key, and the route alone.
  save(join(OUT, "posts", role, `${slug(path)}__${bodyHash(body === undefined ? "" : JSON.stringify(body))}.json`), res);
  if (key) save(join(OUT, "posts", role, `${slug(path)}__${key}.json`), res);
  save(join(OUT, "posts", role, `${slug(path)}.json`), res);
  console.log(`  ${role.padEnd(11)} POST ${path} → ${res.status}`);
  return res;
}

/** Each draft JE, approved by each seat that could try: the response is saved per role. Read-only replays of SoD. */
async function recordApprovals() {
  const journal = (await call("GET", "/books/journal")).json ?? [];
  for (const je of journal.filter((j) => j.status === "draft").slice(0, 12)) {
    for (const role of ["controller", "cfo", "claims_lead"]) {
      const res = await call("POST", `/books/journal/${encodeURIComponent(je.id)}/approve`, { role });
      save(join(OUT, "posts", role, `${slug(`/books/journal/${encodeURIComponent(je.id)}/approve`)}.json`), res);
    }
  }
}

async function main() {
  const health = await call("GET", "/health").catch(() => null);
  if (!health || health.status !== 200) throw new Error(`No server at ${BASE}. Start it first (make dev / make demo / make stub).`);
  rmSync(OUT, { recursive: true, force: true });
  mkdirSync(OUT, { recursive: true });
  await call("POST", "/reset");
  for (const role of ROLES) {
    const s = await call("POST", "/session", { body: { role, name: NAMES[role] } });
    tokens[role] = s.json?.token;
    save(join(OUT, "posts", role, "session.json"), s);
  }

  const steps = [];
  console.log("step 0 · baseline");
  const { runs } = await snapshot(0);
  steps.push({ name: "baseline", unlock: null });

  // Live-demo writes that don't change the story's state: challenges, the desk, injections.
  const hero = runs[0];
  const recoded = hero?.flights?.find((f) => f.decision?.recoded)?.flight?.id;
  if (recoded) {
    await post("judge", `/flights/${encodeURIComponent(recoded)}/challenge`, { text: "The storm would have grounded it anyway" }, { key: "assertion" });
    await post("judge", `/flights/${encodeURIComponent(recoded)}/challenge`, { text: "Airbus operator notice: hidden defect in this EDP batch" }, { key: "new_legal_pattern" });
  }
  for (const [icao, date] of [["EIDW", "2025-01-24"], ["EIDW", "2025-01-26"], ["EGLL", "2025-01-24"], ["EIDW", "2030-01-01"], ["XXXX", "2025-01-24"]]) {
    await post("judge", "/desk", { icao, date }, { key: `${icao}_${date}` });
  }
  const injections = (await call("GET", "/injections")).json ?? [];
  for (const inj of injections) await post("judge", "/inject", inj.request, { key: inj.id });

  // The story's state changes, one step per ruling, as in plan §4.
  const questions = runs.flatMap((r) => r?.questions ?? []);
  const byRole = (role) => questions.find((q) => q.routed_to === role && q.status !== "answered");
  // Character for character the plan's scripted texts (§1.4, §2): LLM calls are cached by exact input.
  const scripted = {
    claims_lead: "No signed acceptance, no offset: pay €600 cash; the voucher stays as goodwill.",
    legal: "A return sector of a storm-cancelled rotation is extraordinary only if no aircraft and crew could operate it within 3 h of STD, and passengers were offered the earliest reroute on any carrier (C-74/19).",
    controller: "Never release the tail. At M12 keep (ultimate − M12 rate) × entitlement until the six-year limitation.",
  };
  for (const role of ["claims_lead", "legal", "controller"]) {
    const q = byRole(role);
    if (!q) continue;
    const answer =
      q.reason_tag === "release-proposal"
        ? await post(role, `/rules/${encodeURIComponent(q.id)}/reject`, { explanation: scripted[role] })
        : await post(role, `/questions/${encodeURIComponent(q.id)}/answer`, { decision: q.recommended_option, explanation: scripted[role] });
    const ruleId = answer.json?.proposal?.rule?.id;
    if (ruleId) await post(role, `/proposals/${encodeURIComponent(ruleId)}/confirm`);
    const step = steps.length;
    console.log(`step ${step} · after ${role} ruled on ${q.id}`);
    await snapshot(step);
    steps.push({ name: `${role} ruled on ${q.id}`, unlock: ruleId ? { method: "POST", path: `/proposals/${encodeURIComponent(ruleId)}/confirm` } : { method: "POST", path: `/questions/${encodeURIComponent(q.id)}/answer` } });
  }

  await post("controller", "/books/month-end", { period: "2025-02" });
  console.log(`step ${steps.length} · after February month-end`);
  await snapshot(steps.length);
  // Approval attempts by each finance seat, after the last snapshot so they can't leak into the story's state;
  // the preparer's own attempt is how the SoD denial is shown.
  await recordApprovals();
  steps.push({ name: "February month-end", unlock: { method: "POST", path: "/books/month-end" } });

  save(join(OUT, "manifest.json"), { recorded_at: new Date().toISOString(), base: BASE, roles: ROLES, steps });
  console.log(`\nRecorded ${files} responses in ${steps.length} steps → ${OUT}`);
}

main().catch((e) => {
  console.error(e.message ?? e);
  process.exit(1);
});
