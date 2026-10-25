export const PRESETS = [
  { id: "scoped", label: "Keep the scope", note: "The original Claims Lead ruling." },
  { id: "broader_scope", label: "Widen the scope", note: "Include non-EU departures without a new ruling." },
  { id: "missing_guard", label: "Drop consent", note: "Remove the unsigned-voucher condition." },
  { id: "wrong_authority", label: "Change the author", note: "Let an agent claim the authority to rule." },
] as const;
export type Preset = (typeof PRESETS)[number]["id"];
export type Check = { id: string; label: string; group: string; passed: boolean; detail: string };
export type Outcome = { status: string; cash_cents: number; voucher_offset_cents: number; rules_applied: string[] };
export type Case = {
  id: string; label: string; coupon_id: string; group: "intended" | "protected";
  source: string; expected: string; passed: boolean; candidate_matches: boolean;
  expected_match: boolean | null; before: Outcome; after: Outcome;
};
export type RuleLabReport = {
  schema: "stormcheck-rule-lab-v1"; preset: Preset;
  verdict: "ready_for_review" | "blocked"; simulation_ran: boolean;
  scenario: { title: string; description: string };
  ruling: { explanation: string }; candidate: { status: string };
  summary: { intended_cases: number; protected_cases: number; passed_checks: number; failed_checks: number; total_checks: number };
  cases: Case[]; checks: Check[];
  accounting: null | { liability_before_cents: number; liability_after_cents: number; new_entries_on_retry: number; unbalanced_entries: number; approved_entries: number; agent_approval_blocked: boolean };
  fingerprints: Record<string, string>;
  isolation: { activated_rules: number; stored_candidate_status: string };
  limitations: string[];
};
export type Evidence = { report: RuleLabReport; source: "live" | "recorded" };
