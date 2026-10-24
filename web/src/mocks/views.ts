// Read views for Trace (commits, blame, audit), Access, Controls and Proof.
import type { AccessMatrix, Blame, BlameStep, CalibrationBin, Commit, ControlMapping, EvalReport, JournalEntry } from "@/api/types";
import { bandFor } from "./data/airports";
import { decide, fullEntitlementCents, HERO_FLIGHT, isHeld, isOwed, sampleEntitlements } from "./data/engine";
import { EOWYN_ID } from "./data/flights";
import { eur, hhmmZ, nearestObs } from "./data/util";
import { hubOf, mainWindow, sourceById, type StormDef } from "./data/world";
import { ctxOf, specOf, stormById, type MockState } from "./state";

// ---------- commits ----------
export const newestCommits = (s: MockState, limit: number) => [...s.commits].reverse().slice(0, limit);

function findCommit(s: MockState, ...refs: string[]): Commit {
  for (let i = s.commits.length - 1; i >= 0; i--) if (refs.includes(s.commits[i].payload_ref)) return s.commits[i];
  return s.commits[0];
}

// ---------- blame: € → entitlement → decision → rule@v → ruling quote → facts → span → METAR obs ----------
export function blame(s: MockState, target: string): Blame | null {
  let flightId: string | null = null;
  let jeTarget: JournalEntry | undefined;
  let coupon: string | null = null;
  if (/^JE-\d{6}(:\d+)?$/.test(target)) {
    jeTarget = s.journal.find((e) => e.id === target.split(":")[0]);
    if (!jeTarget) return null;
    flightId = jeTarget.source_decision_id ?? null;
  } else if (target.startsWith("liability:")) flightId = target.slice("liability:".length);
  else if (specOf(s, target)) flightId = target;
  else if (target.includes(":") && specOf(s, target.slice(0, target.lastIndexOf(":")))) {
    coupon = target;
    flightId = target.slice(0, target.lastIndexOf(":"));
  } else if (stormById(s, target)) flightId = target === EOWYN_ID ? HERO_FLIGHT : (stormById(s, target)?.flights.find((f) => f.flight.status === "cancelled")?.flight.id ?? null);
  else if (s.rules.some((r) => `${r.id}@${r.version}` === target || r.id === target)) return ruleBlame(s, target);
  if (!flightId) return jeTarget ? journalOnlyBlame(s, jeTarget) : null;
  const hit = specOf(s, flightId);
  if (!hit) return null;
  const { storm, spec } = hit;
  const f = spec.flight;
  const ctx = ctxOf(s);
  const d = decide(storm, spec, ctx);
  const steps: BlameStep[] = [];
  const band = bandFor(f.origin, f.dest);
  const full = fullEntitlementCents(spec, d, ctx);
  const est = jeTarget ?? s.journal.find((e) => e.source_decision_id === f.id && e.kind === "compensation_estimate");
  if (est) {
    const amount = est.lines.find((l) => l.account === "2140")?.cr_cents ?? est.lines.reduce((t, l) => t + (l.dr_cents ?? 0), 0);
    steps.push({ commit: findCommit(s, `je:${est.id}`), label: `${eur(amount)} · ${est.lines.map((l) => `${l.dr_cents ? "Dr" : "Cr"} ${l.account}`).join(" / ")} · ${est.id} ${est.status === "draft" ? "drafted, pending approval" : est.status}`, quote: est.memo });
  } else if (d && !isOwed(d) && !isHeld(d)) {
    steps.push({ commit: findCommit(s, `entitlement:${f.id}`), label: "€0 compensation · no compensation; refunds and care still due", quote: null });
  }
  if (d) {
    const ent = coupon ? sampleEntitlements(storm, spec, d, ctx).find((e) => e.coupon_id === coupon) : undefined;
    steps.push({
      commit: findCommit(s, `entitlement:${f.id}`),
      label: ent
        ? `${coupon} · ${ent.status.replace("_", " ")} · ${eur(ent.compensation_cents)} (${ent.article})`
        : isOwed(d) || isHeld(d)
          ? `${f.pax} entitlements · ${eur(full)} full Art. 7 entitlement if every passenger claims${f.id === HERO_FLIGHT && ctx.reduction ? " (158 × €600 + 14 × €300)" : ""}`
          : `${f.pax} coupons · no compensation; refunds and care still due`,
      quote: ent?.reason ?? `${band.label} · ${band.article}`,
    });
    steps.push({ commit: findCommit(s, `decision:${f.id}`), label: `${d.cause.replace("_", "-")} · ${d.extraordinary.replace(/_/g, " ")}${d.recoded ? ` · recoded ${d.recode_label}` : ""} · ${d.confidence.label} ${d.confidence.score === null ? "uncalibrated" : `${Math.round(d.confidence.score * 100)}%`}`, quote: d.reason });
    const refs = [...d.rules_applied];
    if (f.id === HERO_FLIGHT && ctx.reduction) refs.push(ctx.reduction.ref);
    if (coupon && ctx.voucher && !refs.includes(ctx.voucher.ref)) refs.push(ctx.voucher.ref);
    for (const ref of refs) {
      const rule = s.rules.find((r) => `${r.id}@${r.version}` === ref);
      steps.push({ commit: findCommit(s, `rule:${ref}`), label: `${ref} · ${rule?.tier.replace(/_/g, " ") ?? "rule"}${rule?.support ? ` · learned ${rule.support}` : ""}`, quote: rule?.origin_example ?? null });
      const ruling = rule?.origin_ruling_id ? s.rulings.find((r) => r.id === rule.origin_ruling_id) : undefined;
      if (ruling) steps.push({ commit: findCommit(s, ruling.id, `ruling:${ruling.id}`), label: `Ruling by the ${ruling.author_role.replace("_", " ")} (${ruling.author}) · ${ruling.at}`, quote: ruling.decision });
    }
    if (d.cause === "technical") steps.push({ commit: findCommit(s, "rule:REG-C549-TECHNICAL@1"), label: "Ruling: CJEU C-549/07 Wallentin-Hermann, read with C-257/14 van der Lans", quote: "a technical problem arising in normal operation is not an extraordinary circumstance" });
    if (d.cause === "weather") steps.push({ commit: findCommit(s, "rule:REG-ART5-3-WEATHER@1"), label: "Ruling: EU261 Art. 5(3) · weather inside the storm window is an extraordinary circumstance", quote: "extraordinary circumstances which could not have been avoided even if all reasonable measures had been taken" });
    const tier1 = d.evidence.filter((e) => e.trust_tier === 1 && !e.source_id.startsWith("metar:"));
    for (const e of tier1.slice(0, 2)) steps.push({ commit: findCommit(s, `fact:${e.source_id}`), label: `fact · ${e.field} = ${typeof e.value === "string" ? e.value : JSON.stringify(e.value)} (${sourceById(e.source_id)?.kind.replace("_", " ") ?? "source"}, tier ${e.trust_tier})`, quote: e.field === "aog.logged_at" ? null : e.quote });
    const span = tier1.find((e) => e.quote && e.field === "aog.logged_at");
    if (span) steps.push({ commit: findCommit(s, `llm:reader:${span.source_id}`), label: `span · verbatim in the source, value re-parsed (${hhmmZ(String(span.value))} → ${span.value})`, quote: span.quote });
    const o = nearestObs(storm.metar, f.origin === hubOf(storm) ? f.sched_dep : f.sched_arr);
    steps.push({ commit: findCommit(s, `fact:metar:${storm.id}`), label: `METAR ${o.valid.slice(11, 16)}Z at ${storm.station}: ${o.sknt ?? "—"} kt${o.gust ? ` gusting ${o.gust}` : ", no gust"}${f.id === HERO_FLIGHT ? " · gusts ≤25 kt from 16:00Z" : ""}`, quote: o.raw });
  } else {
    const o = nearestObs(storm.metar, f.actual_dep ?? f.sched_dep);
    steps.push({ commit: findCommit(s, `fact:metar:${storm.id}`), label: `METAR ${o.valid.slice(11, 16)}Z at ${storm.station}: ${f.number} operated`, quote: o.raw });
  }
  return { target, steps };
}

function stormMetarStep(s: MockState, storm: StormDef): BlameStep {
  const w = mainWindow(storm);
  const o = nearestObs(storm.metar, w?.end ?? `${storm.date}T12:00:00Z`);
  return { commit: findCommit(s, `fact:metar:${storm.id}`), label: `METAR ${o.valid.slice(11, 16)}Z at ${storm.station}: the storm window ${w ? `closes ${hhmmZ(w.end)}` : "never opened"}`, quote: o.raw };
}

function journalOnlyBlame(s: MockState, entry: JournalEntry): Blame {
  const storm = stormById(s, entry.lines[0]?.dims?.storm ?? EOWYN_ID) ?? stormById(s, EOWYN_ID)!;
  return {
    target: entry.id,
    steps: [
      { commit: findCommit(s, `je:${entry.id}`), label: `${entry.id} · ${entry.kind.replace(/_/g, " ")} · ${entry.status === "draft" ? "drafted, pending approval" : entry.status} · built from ${entry.built_from ?? 0} sources`, quote: entry.memo },
      stormMetarStep(s, storm),
    ],
  };
}

function ruleBlame(s: MockState, target: string): Blame {
  const rule = s.rules.find((r) => `${r.id}@${r.version}` === target) ?? s.rules.filter((r) => r.id === target).sort((a, b) => b.version - a.version)[0];
  const ref = `${rule.id}@${rule.version}`;
  const steps: BlameStep[] = [{ commit: findCommit(s, `rule:${ref}`), label: `${ref} · ${rule.tier.replace(/_/g, " ")} · ${rule.status}`, quote: rule.origin_example ?? null }];
  const ruling = rule.origin_ruling_id ? s.rulings.find((r) => r.id === rule.origin_ruling_id) : undefined;
  if (ruling) steps.push({ commit: findCommit(s, ruling.id, `ruling:${ruling.id}`), label: `Ruling by the ${ruling.author_role.replace("_", " ")} (${ruling.author})`, quote: ruling.decision });
  const example = rule.origin_example ? specOf(s, rule.origin_example.split(":").length > 2 ? rule.origin_example.slice(0, rule.origin_example.lastIndexOf(":")) : rule.origin_example) : undefined;
  steps.push(stormMetarStep(s, example?.storm ?? stormById(s, EOWYN_ID)!));
  return { target, steps };
}

// ---------- audit ----------
export function audit(s: MockState, jeId: string): Record<string, unknown> | null {
  const entry = s.journal.find((e) => e.id === jeId);
  if (!entry) return null;
  const hit = entry.source_decision_id ? specOf(s, entry.source_decision_id) : undefined;
  const ctx = ctxOf(s);
  const d = hit ? decide(hit.storm, hit.spec, ctx) : null;
  const decisionCommit = hit ? findCommit(s, `decision:${hit.spec.flight.id}`) : null;
  const register = hit && d
    ? sampleEntitlements(hit.storm, hit.spec, d, ctx).map((e) => ({
        coupon_id: e.coupon_id,
        entitlement_cents: e.compensation_cents,
        status: e.status,
        article: e.article,
        rules: e.rules_applied ?? [],
        cause_commit: decisionCommit?.hash ?? null,
        confidence: d.confidence.score,
        refund_already_initiated: e.refund_already_initiated ?? false,
        voucher_offset_cents: e.voucher_offset_cents ?? 0,
        je_ids: s.journal.filter((j) => j.source_decision_id === e.flight_id).map((j) => j.id),
        limitation_expiry: `${Number(hit.spec.flight.date.slice(0, 4)) + 6}${hit.spec.flight.date.slice(4)}`,
      }))
    : [];
  const lines = entry.lines.reduce((t, l) => t + (l.dr_cents ?? 0) - (l.cr_cents ?? 0), 0);
  return {
    je: entry,
    balanced: lines === 0,
    period_locked: s.locked.includes(entry.period),
    register,
    decision_commits: [decisionCommit, findCommit(s, `je:${entry.id}`)].filter(Boolean),
    approvals: s.accessLog.filter((a) => a.resource === `journal:${entry.id}`),
    sources: hit && d ? [...new Set(d.evidence.map((e) => e.source_id))].map((id) => ({ id, kind: sourceById(id)?.kind ?? id.split(":")[0], sha256: sourceById(id)?.sha256 ?? null, trust_tier: d.evidence.find((e) => e.source_id === id)?.trust_tier })) : [],
    replay: { identical: true, commits_verified: s.commits.length },
    blame_target: entry.id,
  };
}

// ---------- access & controls ----------
const RESOURCES = ["flights", "ops_logs", "tech_log", "metar", "coupons", "claims", "entitlements", "payouts", "journal", "rules", "questions", "trace", "desk"];
type Cell = AccessMatrix["cells"][string][string];
const row = (cells: Cell[]): Record<string, Cell> => Object.fromEntries(RESOURCES.map((r, i) => [r, cells[i]]));

export function accessMatrix(): AccessMatrix {
  return {
    principals: ["claims_lead", "legal", "controller", "ops", "cfo", "judge", "agent.reader", "agent.drafter", "agent.engine", "agent.crm_bot"],
    resources: RESOURCES,
    cells: {
      //                    flights ops_logs tech_log metar  coupons     claims      entitlements payouts   journal    rules   questions trace   desk
      claims_lead: row(["read", "read", "read", "read", "read", "write", "read", "approve", "read", "write", "write", "read", "none"]),
      legal: row(["read", "read", "read", "read", "redacted", "redacted", "read", "none", "none", "write", "write", "read", "none"]),
      controller: row(["read", "read", "none", "read", "redacted", "redacted", "read", "read", "approve", "write", "write", "read", "none"]),
      ops: row(["read", "write", "read", "read", "redacted", "redacted", "redacted", "none", "none", "read", "read", "read", "none"]),
      cfo: row(["read", "none", "none", "read", "redacted", "redacted", "read", "read", "approve", "read", "read", "read", "none"]),
      judge: row(["read", "read", "read", "read", "redacted", "redacted", "read", "read", "read", "read", "read", "read", "write"]),
      "agent.reader": row(["read", "read", "read", "read", "read", "read", "none", "none", "none", "none", "none", "write", "none"]),
      "agent.drafter": row(["read", "none", "none", "read", "redacted", "redacted", "read", "write", "write", "write", "none", "write", "none"]),
      "agent.engine": row(["write", "read", "read", "read", "redacted", "redacted", "write", "write", "write", "read", "write", "write", "none"]),
      "agent.crm_bot": row(["read", "none", "none", "none", "read", "none", "none", "none", "none", "none", "none", "write", "none"]),
    },
  };
}

export const CONTROLS: ControlMapping[] = [
  { control: "ACL broker for people and agents: every read goes through broker.read(principal, resource); PII is redacted per role", framework_ref: "CC6.1", implemented_by: "engine/acl.py", evidence_endpoint: "/api/access/matrix" },
  { control: "Least privilege and segregation of duties: preparer ≠ approver; payouts need the Claims Lead", framework_ref: "CC6.3", implemented_by: "engine/controls.py · books.approve raises SoDViolation", evidence_endpoint: "/api/access/log" },
  { control: "Denial log: every refused action is an access_denied commit and a trace event", framework_ref: "CC7.2", implemented_by: "engine/trace.py", evidence_endpoint: "/api/trace?since=0" },
  { control: "Versioned rules, replayed before confirm: every rule change shows what it flips and the € delta first", framework_ref: "CC8.1", implemented_by: "engine/lifecycle.py · RuleProposal.would_flip", evidence_endpoint: "/api/rules" },
  { control: "Processing-integrity invariants checked on every post: 2140 ties to GL, 2125 clears to 0, one payment per coupon", framework_ref: "PI1", implemented_by: "books/invariants.py", evidence_endpoint: "/api/books/invariants" },
];

// ---------- proof ----------
// MOCK until eval/proof.json: Filip's eval writes the real EvalReport; these are plausible placeholders
// with the contract's shape (Wilson intervals are computed from n and accuracy).
function wilson(lo: number, hi: number, n: number, accuracy: number): CalibrationBin {
  const z = 1.96;
  const p = accuracy;
  const denom = 1 + (z * z) / n;
  const center = (p + (z * z) / (2 * n)) / denom;
  const half = (z * Math.sqrt((p * (1 - p)) / n + (z * z) / (4 * n * n))) / denom;
  const r3 = (x: number) => Math.round(x * 1000) / 1000;
  return { lo, hi, n, accuracy, wilson_lo: r3(Math.max(0, center - half)), wilson_hi: r3(Math.min(1, center + half)) };
}

export const EVAL_REPORT: EvalReport = {
  split: { learn: "2023-07-01..2024-12-31", score: "2025-01-01..2025-06-30" },
  n_storms: 6,
  n_passengers: 21_486,
  straight_through_pct: 96.4,
  miscodes_caught: 11,
  miscodes_total: 12,
  miscodes_eur_cents: 31_680_000,
  false_holds: 2,
  repeat_questions: 0,
  out_of_scope_auto: 0,
  liability_vs_actual: { M3: 0.97, M6: 1.02 },
  calibration: {
    cause: [wilson(0.5, 0.6, 14, 0.571), wilson(0.6, 0.7, 22, 0.682), wilson(0.7, 0.8, 41, 0.756), wilson(0.8, 0.9, 96, 0.865), wilson(0.9, 1.0, 1184, 0.968)],
    voucher: [wilson(0.3, 0.5, 11, 0.455), wilson(0.5, 0.7, 19, 0.632), wilson(0.7, 0.9, 37, 0.811), wilson(0.9, 1.0, 88, 0.943)],
    release: [wilson(0.6, 0.8, 9, 0.667), wilson(0.8, 1.0, 6, 0.833)],
    claim_validity: [],
  },
  coverage_at_90: { cause: 0.87, voucher: 0.57, release: 0.4 },
  baseline: { model: "claude-opus-5-5", runs: 3, liability_eur: [99000, 41580, 0], cause_accuracy: [0.74, 0.7, 0.78], hash_identical: false },
  stormcheck_runs: { runs: 3, liability_eur: [34650, 34650, 34650], hash_identical: true, hash: "9c1f4e8b2a7d3f60e5b1c8a94d2e7f3016b5a9c4e8d2f7a1b3c6e9d0f4a2b8c5" },
  injections: { rehearsed: 8, fuzz: 20, blocked: 3, escalated: 9, server_errors: 0 },
  real_vs_simulated: {
    real: ["EIDW METAR (Iowa Environmental Mesonet)", "Eurocontrol airport traffic (179 departures on 24 Jan 2025)", "OurAirports distances (great circle, R = 6,371 km)", "EU261 text and CJEU case law", "Met Éireann warnings (red 06:00–11:00)"],
    simulated: ["Northstar's schedule and tails", "AMOS tech log, MCC and OCC logs", "passengers, coupons and elections", "claims and CRM events", "care invoices"],
  },
  label: "calibrated on synthetic labels; validates the pipeline, not the world",
};

