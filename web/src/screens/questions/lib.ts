import type { Question, ReplayDiff, Role, Rule } from "@/api/types";
import { count, eur, idDate, longDate, ROLE_LABEL, routedTo } from "@/lib/format";
import { stormName } from "@/lib/storms";

/** "sources-disagree" → "sources disagree", for `confidence 39% · sources disagree`. */
export const reasonText = (tag: string) => tag.replace(/-/g, " ");

/** The six RuleProposal checks, as sentences a ruler can read. */
export const CHECK_LABEL: Record<string, string> = {
  compiles: "Compiles to the rule language",
  reproduces_case: "Reproduces your ruling on this case",
  no_hard_control: "Overrides no hard control",
  grounded: "Every value is grounded in your words",
  author_has_authority: "You hold the authority it automates",
  no_conflict: "No conflict with an active rule",
};
export const CHECK_ORDER = ["compiles", "reproduces_case", "grounded", "author_has_authority", "no_hard_control", "no_conflict"];

export function checkLabel(key: string) {
  return CHECK_LABEL[key] ?? key.replace(/_/g, " ");
}

function hoursText(fromIso: string, toIso: string): string | null {
  const ms = Date.parse(toIso) - Date.parse(fromIso);
  if (!Number.isFinite(ms) || ms <= 0) return null;
  const min = Math.round(ms / 60_000);
  return min < 60 ? `${min} min` : `${Math.round(min / 60)}h`;
}

/**
 * "Waiting on Claims Lead 3h · reminder sent · 4,761 others settled" (Q5): from asked_at, remind_at, status
 * and the additive `others_settled` (contracts/requests/justin.md #4) when the server sends it.
 */
export function reminderText(q: Question): string | null {
  const who = ROLE_LABEL[q.routed_to];
  const settled = q.others_settled ? ` · ${count(q.others_settled)} others settled` : "";
  if (q.status === "reminded") {
    const waited = q.remind_at ? hoursText(q.asked_at, q.remind_at) : null;
    return `Waiting on ${who}${waited ? ` ${waited}` : ""} · reminder sent${settled}`;
  }
  if (q.remind_at) return `Waiting on ${who} · reminder due ${q.remind_at.slice(11, 16)}Z${settled}`;
  return null;
}

export type CaseKind = "passenger" | "flight" | "cohort" | "rule" | "case";

/** What a case ref points at: a coupon (a passenger), a flight, a storm cohort, or a rule (a widening question). */
export function caseKind(ref: string): CaseKind {
  if (/^[A-Z0-9]{2}\d+@[\d-]+:/.test(ref)) return "passenger";
  if (/^[A-Z0-9]{2}\d+@/.test(ref)) return "flight";
  if (/^[A-Z]{4}@/.test(ref)) return "cohort";
  if (/^(R|REG|HC)-[A-Z0-9-]+(@\d+)?$/.test(ref)) return "rule";
  return "case";
}

/** "3 flights", "1 passenger", "1 cohort". */
export function caseCount(refs: string[]): string {
  const kinds = new Set(refs.map(caseKind));
  const k = kinds.size === 1 ? [...kinds][0] : "case";
  const noun = { passenger: "passenger", flight: "flight", cohort: "cohort", rule: "rule", case: "case" }[k];
  return `${count(refs.length)} ${noun}${refs.length === 1 ? "" : "s"}`;
}

/** Flight file for a coupon or flight ref ("NS31@2025-01-24:14C" → /flights/NS31@2025-01-24). */
export function caseHref(ref: string): string | null {
  const k = caseKind(ref);
  if (k === "passenger" || k === "flight") return `/flights/${encodeURIComponent(ref.split(":")[0])}`;
  if (k === "cohort") return `/close`;
  if (k === "rule") return `/policies#${encodeURIComponent(ref.split("@")[0])}`;
  return null;
}

export const caseLabel = (ref: string) => {
  const k = caseKind(ref);
  if (k === "cohort") return `${stormName(ref) ?? ref} cohort`;
  if (k === "rule") return ref;
  const [head, seat] = ref.split(":");
  const flight = head.split("@")[0];
  return seat ? `${flight} · ${seat}` : flight;
};

/** Every feature a DSL condition names ({all|any|not} trees of {f, op, v} clauses). */
export function conditionFeatures(node: unknown, out = new Set<string>()): Set<string> {
  if (!node || typeof node !== "object") return out;
  const n = node as Record<string, unknown>;
  if (typeof n.f === "string") out.add(n.f);
  for (const key of ["all", "any"]) if (Array.isArray(n[key])) for (const kid of n[key] as unknown[]) conditionFeatures(kid, out);
  if (n.not) conditionFeatures(n.not, out);
  return out;
}

/**
 * The rule as it should read: scope keys the condition already states are dropped, so the sentence names
 * each fact once ("…, and the flight leaves the EU: …"), while case-only scope ("the voucher is €300") stays.
 */
export function readableRule<T extends Pick<Rule, "condition" | "scope">>(rule: T): T {
  const named = conditionFeatures(rule.condition);
  const scope = Object.fromEntries(Object.entries(rule.scope ?? {}).filter(([k]) => !named.has(k)));
  return { ...rule, scope };
}

/** A release proposal (Q3) is rejected, not just answered. */
export const isReleaseProposal = (q: Question) => q.reason_tag === "release-proposal" || /release/.test(q.pattern);

/** The proposed rule a release question is about, when the server models it as one. */
export function findProposalRule(rules: Rule[] | undefined, q: Question): Rule | null {
  const open = (rules ?? []).filter((r) => r.status === "proposed" || r.status === "shadow");
  return (
    open.find((r) => r.origin_example && (q.case_refs.includes(r.origin_example) || r.origin_example === q.id)) ??
    open.find((r) => r.kind === "release" && q.case_refs.some((ref) => JSON.stringify(r.scope).includes(ref))) ??
    open.find((r) => r.kind === "release") ??
    null
  );
}

/** Option text that already means "reject the proposal" ("Reject: never release the tail…"). */
export const REJECT_RE = /^\s*reject\b|\bnever release\b|\bdo not release\b|\bdon'?t release\b|^\s*keep the (expected )?tail\b/i;

/**
 * "↻ Next storm, Storm Herminia: 31 cases settled, ruling cited · 1 asks again": read off the confirm
 * replay, counting flips on days after the question's own cases. Nothing here is typed in.
 */
export function nextStormLine(replay: ReplayDiff | null | undefined, caseRefs: string[]): { settled: string; asks: string | null } | null {
  if (!replay?.flips.length) return null;
  const own = new Set(caseRefs.map(idDate).filter(Boolean));
  const later = replay.flips.filter((f) => {
    const d = idDate(f.entity_id);
    return d && !own.has(d) && [...own].every((o) => d > o);
  });
  if (!later.length) return null;
  const byDate = new Map<string, { settled: number; asks: number }>();
  for (const f of later) {
    const d = idDate(f.entity_id);
    const row = byDate.get(d) ?? { settled: 0, asks: 0 };
    if (typeof f.after === "string" && /needs_ruling|asked|held|escalat/i.test(f.after)) row.asks += 1;
    else row.settled += 1;
    byDate.set(d, row);
  }
  const [date, n] = [...byDate.entries()].sort(([a], [b]) => a.localeCompare(b))[0];
  const name = (stormName(`EIDW@${date}`) ?? longDate(date)).replace(/^Storm /, "");
  return {
    settled: `Next storm (${name}): ${count(n.settled)} case${n.settled === 1 ? "" : "s"} settled, ruling cited`,
    asks: n.asks ? `${count(n.asks)} outside the rule's scope ${n.asks === 1 ? "asks" : "ask"} again` : null,
  };
}

/**
 * "↻ 3 flights settled, ruling cited 3× · Δ (€47,496)": what the confirm replay changed on the question's own
 * storm (its cases and their day), read off the flips. Later storms are `nextStormLine`'s.
 */
export function settledHereLine(replay: ReplayDiff | null | undefined, caseRefs: string[]): string | null {
  if (!replay?.flips.length) return null;
  const flights = new Set(caseRefs.map((r) => r.split(":")[0]));
  const days = new Set(caseRefs.map(idDate).filter(Boolean));
  const here = replay.flips.filter((f) => flights.has(f.entity_id.split(":")[0]) || caseRefs.includes(f.entity_id) || days.has(idDate(f.entity_id)));
  if (!here.length) return null;
  const ids = [...new Set(here.map((f) => f.entity_id))];
  const kinds = new Set(ids.map(caseKind));
  const kind = kinds.size === 1 ? [...kinds][0] : "case";
  const noun = { passenger: "case", flight: "flight", cohort: "cohort", rule: "rule", case: "case" }[kind];
  const verb = kind === "cohort" ? "changed" : "settled";
  const delta = here.reduce((s, f) => s + (f.delta_cents ?? 0), 0);
  return `${count(ids.length)} ${noun}${ids.length === 1 ? "" : "s"} ${verb}, ruling cited ${count(ids.length)}×${delta ? ` · Δ ${eur(delta, { signed: true })}` : ""}`;
}

/** Server-side PII masks, recognised so they render as a quiet "hidden" mark instead of raw symbols. */
export const MASK_RE = /(\[(?:redacted|masked|pii)[^\]]*\]|█{2,}|•{3,}|\*{3,}|░{2,})/gi;

/** How a seat reads mid-sentence, as `routedTo` writes it: "the Claims Lead", "the Controller", "Legal", "Ops". */
export const seatPhrase = (role: Role) => routedTo(role).replace(/^Routed to /, "");
