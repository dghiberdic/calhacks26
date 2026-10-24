// Records the demo against a running server so the Devpost build can replay it with no backend (J9).
//
//   node scripts/record.mjs                        # against http://localhost:8000 (make dev / make demo)
//   node scripts/record.mjs --base http://localhost:8001 --out ../demo/recorded
//
// What it saves (demo/recorded/):
//   manifest.json                       steps, the write that unlocks each step, roles, when/where recorded
//   step-<n>/<role>.json                each role's GETs at that step: slug → blob
//   blobs/<hash>.json                   each distinct response body, once
//   posts/<role>/<slug>[__<hash>].json  the response (status + body) to each scripted write
// Steps follow plan §4: baseline → Claims Lead rules on Q1 → Legal on the knock-on returns → Controller
// rejects the Isha release → February month-end. The recorded build advances a step when the presenter
// performs that step's write, so a click-through tells the same story as the live demo.
import { createHash } from "node:crypto";
import { mkdirSync, readdirSync, rmSync, writeFileSync } from "node:fs";
import { join, resolve } from "node:path";

const arg = (name, fallback) => {
  const i = process.argv.indexOf(`--${name}`);
  return i > 0 ? process.argv[i + 1] : fallback;
};
const BASE = arg("base", "http://localhost:8000").replace(/\/$/, "");
const OUT = resolve(arg("out", "../demo/recorded"));
const ROLES = ["judge", "claims_lead", "legal", "controller", "ops", "cfo"];
/** Options that reject a release proposal (as web/src/screens/questions/lib.ts REJECT_RE). */
const REJECT = /^\s*reject\b|\bnever release\b|\bdo not release\b|\bdon'?t release\b|^\s*keep the (expected )?tail\b/i;
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

// Most responses repeat across roles and steps, so each distinct body is stored once (blobs/<hash>.json) and
// every step and role gets a small index of slug → blob. 200 MB of copies becomes a few MB.
const blobs = new Set();
function blob(data) {
  const text = JSON.stringify(data);
  const hash = createHash("sha256").update(text).digest("hex").slice(0, 16);
  if (!blobs.has(hash)) {
    mkdirSync(join(OUT, "blobs"), { recursive: true });
    writeFileSync(join(OUT, "blobs", `${hash}.json`), text);
    blobs.add(hash);
  }
  return hash;
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
  // Blame and audit only where the demo can click: the flights that aren't plain weather (recoded, held,
  // technical) plus a few weather ones, the estimate and true-up entries and the newest drafts, and every
  // question. Fetching them for every one of 100+ entries at every step was 12 of the first 16 MB.
  const rows = runs.flatMap((r) => r?.flights ?? []);
  const notWeather = rows.filter((f) => f.decision && f.decision.cause !== "weather").map((f) => f.flight.id);
  const someWeather = rows.filter((f) => f.decision?.cause === "weather").slice(0, 4).map((f) => f.flight.id);
  const KIND_ORDER = ["change_in_estimate", "compensation_estimate", "claims_approved", "care_accrual"];
  const keyJournal = [...journal]
    .sort((a, b) => ((KIND_ORDER.indexOf(a.kind) + 1 || 99) - (KIND_ORDER.indexOf(b.kind) + 1 || 99)) || (b.status === "draft") - (a.status === "draft"))
    .slice(0, 14)
    .map((j) => j.id);
  const blameTargets = [...new Set([...notWeather, ...someWeather, ...keyJournal, ...runs.flatMap((r) => (r?.questions ?? []).map((q) => q.id))])];

  const shared = [
    "/health",
    "/storms",
    ...storms.map((s) => `/storms/${encodeURIComponent(s.id)}`),
    ...flightIds.map((id) => `/flights/${encodeURIComponent(id)}`),
    "/rules",
    "/trace?since=0",
    "/commits?limit=100",
    ...blameTargets.map((t) => `/blame?target=${encodeURIComponent(t)}`),
    ...keyJournal.map((id) => `/audit/${encodeURIComponent(id)}`),
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
  const scoped = ["/questions?status=open", "/questions?status=answered", "/questions"];

  for (const role of ROLES) {
    // Role-scoped and redacted responses differ per role, so each role gets its own index; identical bodies share a blob.
    const index = {};
    for (const path of [...shared, ...scoped]) {
      const { status, json } = await call("GET", path, { role });
      if (status === 200) {
        index[slug(path)] = blob(json);
        files += 1;
      }
    }
    save(join(OUT, `step-${step}`, `${role}.json`), index);
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
  // Clear only this recorder's own files: demo/recorded/api/ is `make record`'s (scripts/record.py) and stays.
  mkdirSync(OUT, { recursive: true });
  for (const name of readdirSync(OUT)) if (name === "manifest.json" || name === "posts" || name === "blobs" || /^step-\d+$/.test(name)) rmSync(join(OUT, name), { recursive: true, force: true });
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
      // A release proposal is rejected: through its proposed rule when the server names one, otherwise by
      // answering with the question's own rejecting option (David's server: "Keep the expected tail…").
      q.reason_tag === "release-proposal"
        ? q.proposal_rule_id
          ? await post(role, `/rules/${encodeURIComponent(q.proposal_rule_id)}/reject`, { explanation: scripted[role] })
          : await post(role, `/questions/${encodeURIComponent(q.id)}/answer`, { decision: q.options.find((o) => REJECT.test(o)) ?? q.recommended_option, explanation: scripted[role] })
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

  save(join(OUT, "manifest.json"), { format: 2, recorded_at: new Date().toISOString(), base: BASE, roles: ROLES, steps });
  console.log(`\nRecorded ${files} responses in ${steps.length} steps → ${OUT}`);
}

main().catch((e) => {
  console.error(e.message ?? e);
  process.exit(1);
});
