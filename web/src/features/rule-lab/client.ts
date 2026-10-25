import type { Evidence, Outcome, Preset, RuleLabReport } from "./types";

const recorded = {
  scoped: () => import("./recorded/scoped.json"),
  broader_scope: () => import("./recorded/broader_scope.json"),
  missing_guard: () => import("./recorded/missing_guard.json"),
  wrong_authority: () => import("./recorded/wrong_authority.json"),
};

const text = (v: unknown): v is string => typeof v === "string";
const integer = (v: unknown): v is number => typeof v === "number" && Number.isSafeInteger(v) && v >= 0;
const outcome = (o: Outcome) => text(o.status) && integer(o.cash_cents) && integer(o.voucher_offset_cents)
  && Array.isArray(o.rules_applied) && o.rules_applied.every(text);

/** Reject mismatched or inconsistent envelopes before a verdict reaches the UI. */
function parseReport(value: unknown, preset: Preset): RuleLabReport {
  const r = value as RuleLabReport;
  try {
    const s = r.summary;
    const valid = r.schema === "stormcheck-rule-lab-v1" && r.preset === preset
      && ["ready_for_review", "blocked"].includes(r.verdict) && typeof r.simulation_ran === "boolean"
      && text(r.ruling.explanation) && text(r.scenario.title) && text(r.scenario.description)
      && [s.intended_cases, s.protected_cases, s.passed_checks, s.failed_checks, s.total_checks].every(integer)
      && Array.isArray(r.checks) && r.checks.every(c => text(c.id) && text(c.label) && text(c.group) && text(c.detail) && typeof c.passed === "boolean")
      && s.total_checks === r.checks.length && s.total_checks === s.passed_checks + s.failed_checks
      && s.failed_checks === r.checks.filter(c => !c.passed).length
      && (r.verdict === "ready_for_review") === (s.failed_checks === 0)
      && Array.isArray(r.cases) && r.cases.every(c => text(c.id) && text(c.label) && text(c.coupon_id)
        && ["intended", "protected"].includes(c.group) && text(c.expected) && text(c.source)
        && typeof c.passed === "boolean" && typeof c.candidate_matches === "boolean"
        && (c.expected_match === null || typeof c.expected_match === "boolean") && outcome(c.before) && outcome(c.after))
      && s.intended_cases === r.cases.filter(c => c.group === "intended").length
      && s.protected_cases === r.cases.filter(c => c.group === "protected").length
      && (r.simulation_ran ? r.accounting !== null && integer(r.accounting.liability_after_cents) : r.accounting === null && r.cases.length === 0)
      && r.candidate.status === "proposed" && r.isolation.activated_rules === 0 && r.isolation.stored_candidate_status === "proposed"
      && Object.keys(r.fingerprints).length > 0 && Object.values(r.fingerprints).every(v => /^[a-f0-9]{64}$/.test(v))
      && Array.isArray(r.limitations) && r.limitations.every(text);
    if (valid) return r;
  } catch { /* An incomplete response must never render a passing verdict. */ }
  throw new Error("The rule evidence could not be verified. Try again.");
}

/** Separate service in dev; production uses saved evidence unless a live route is configured. */
export async function loadRuleLabReport(preset: Preset, signal?: AbortSignal): Promise<Evidence> {
  signal?.throwIfAborted();
  const base = (import.meta.env.VITE_RULE_LAB_API as string | undefined) ?? (import.meta.env.DEV ? "/rule-lab-api" : null);
  if (base) {
    const controller = new AbortController();
    const abort = () => controller.abort(signal?.reason);
    signal?.addEventListener("abort", abort, { once: true });
    const timer = setTimeout(() => controller.abort(), 8000);
    try {
      const response = await fetch(`${base}/report?preset=${encodeURIComponent(preset)}`, { signal: controller.signal, cache: "no-store" });
      if (!response.ok) throw new Error("Rule checks could not be loaded.");
      return { report: parseReport(await response.json(), preset), source: "live" };
    } catch {
      signal?.throwIfAborted();
      // The optional service being unavailable must not take down the story.
    } finally {
      clearTimeout(timer);
      signal?.removeEventListener("abort", abort);
    }
  }
  const data = await recorded[preset]();
  signal?.throwIfAborted();
  return { report: parseReport(data.default, preset), source: "recorded" };
}
