import type { Role, Rule, RuleStatus, RuleTier } from "@/api/types";
import { clauseText } from "@/components/rule-sentence";
import { longDate, zulu } from "@/lib/format";
import { stormName } from "@/lib/storms";

/**
 * Where a rule came from. Plan §2 rule 3: rules come only from mined history, rulings, rejections and
 * regulation versions; hard controls are code. The screen groups by origin and never offers a way to
 * author one.
 */
export type Origin = "learned" | "ruled" | "rejected" | "regulation" | "hard";

export const ORIGIN_ORDER: Origin[] = ["learned", "ruled", "rejected", "regulation", "hard"];

export const ORIGIN_COPY: Record<Origin, { title: string; blurb: string }> = {
  learned: { title: "Learned", blurb: "Mined from past decisions at onboarding. Each shows its support." },
  ruled: { title: "Ruled", blurb: "A person ruled once. The ruling became a scoped, versioned rule." },
  rejected: { title: "Rejected", blurb: "A rejection, kept as a rule so the proposal never comes back." },
  regulation: { title: "Regulation", blurb: "Versions of the law, each with its dates." },
  hard: { title: "Hard controls are code", blurb: "Not rules: nothing can widen, revert or override them." },
};

/** Precedence, highest first (plan §2 rule 4). */
export const PRECEDENCE: RuleTier[] = ["hard_control", "regulation", "legal_ruling", "controller_ruling", "claims_lead_ruling", "mined"];

/** A rejection teaches by forbidding: the Controller's "never release the tail" becomes deny_release / keep_tail. */
function isRejection(rule: Pick<Rule, "kind" | "action" | "origin_ruling_id">) {
  return rule.kind === "release" || rule.action === "deny_release" || rule.action === "keep_tail" || /rej/i.test(rule.origin_ruling_id ?? "");
}

export function originOf(rule: Pick<Rule, "tier" | "kind" | "action" | "origin_ruling_id">): Origin {
  if (rule.tier === "hard_control") return "hard";
  if (rule.tier === "regulation") return "regulation";
  if (rule.tier === "mined") return "learned";
  return isRejection(rule) ? "rejected" : "ruled";
}

/** The person whose ruling a tier records (the avatar on a Ruled or Rejected card). */
export const RULER: Partial<Record<RuleTier, Role>> = {
  legal_ruling: "legal",
  controller_ruling: "controller",
  claims_lead_ruling: "claims_lead",
};

// ---------- versions ----------

/** Every version of one rule id, oldest first, with the one the engine applies now. */
export type RuleFamily = {
  id: string;
  versions: Rule[];
  /** The version in force: the newest active (or suspect) one; before any is confirmed, the newest draft. */
  current: Rule;
  /** A newer version waiting for confirmation (a widen's shadow version, or a proposal). */
  pending: Rule | null;
};

const IN_FORCE: RuleStatus[] = ["active", "suspect"];
const DRAFT: RuleStatus[] = ["shadow", "proposed"];

export function families(rules: Rule[]): RuleFamily[] {
  const byId = new Map<string, Rule[]>();
  for (const r of rules) byId.set(r.id, [...(byId.get(r.id) ?? []), r]);
  return [...byId.entries()].map(([id, list]) => {
    const versions = [...list].sort((a, b) => a.version - b.version);
    const newestFirst = [...versions].reverse();
    const current =
      newestFirst.find((v) => IN_FORCE.includes(v.status)) ?? newestFirst.find((v) => v.status === "shadow") ?? newestFirst.find((v) => v.status === "proposed") ?? newestFirst[0];
    const pending = newestFirst.find((v) => v.version > current.version && DRAFT.includes(v.status)) ?? null;
    return { id, versions, current, pending };
  });
}

/** Group families by origin and order each group: precedence, then most cited, then id. */
export function byOrigin(rules: Rule[]): Record<Origin, RuleFamily[]> {
  const out: Record<Origin, RuleFamily[]> = { learned: [], ruled: [], rejected: [], regulation: [], hard: [] };
  for (const f of families(rules)) out[originOf(f.current)].push(f);
  for (const list of Object.values(out)) {
    list.sort(
      (a, b) =>
        Number(a.current.static_card ?? false) - Number(b.current.static_card ?? false) ||
        PRECEDENCE.indexOf(a.current.tier) - PRECEDENCE.indexOf(b.current.tier) ||
        (b.current.times_cited ?? 0) - (a.current.times_cited ?? 0) ||
        a.id.localeCompare(b.id, "en", { numeric: true }),
    );
  }
  return out;
}

// ---------- support ("41 of 42") ----------

export function parseSupport(support: string | null | undefined): { hits: number; of: number } | null {
  const m = support?.match(/(\d[\d,]*)\s*(?:of|\/)\s*(\d[\d,]*)/i);
  if (!m) return null;
  const hits = Number(m[1].replace(/,/g, ""));
  const of = Number(m[2].replace(/,/g, ""));
  return Number.isFinite(hits) && Number.isFinite(of) && of > 0 && hits <= of ? { hits, of } : null;
}

// ---------- scope ----------

/** Scope keys copied from the case (`case:<value>`): the ones a Widen can still drop, one per yes. */
export function caseKeys(rule: Pick<Rule, "scope">): string[] {
  return Object.entries(rule.scope ?? {})
    .filter(([, v]) => typeof v === "string" && v.startsWith("case:"))
    .map(([k]) => k);
}

/** The `case:` keys a proposal dropped (or turned into grounded values). */
export function droppedCaseKeys(before: Pick<Rule, "scope">, after: Pick<Rule, "scope">): { key: string; value: string }[] {
  const next = after.scope ?? {};
  return caseKeys(before)
    .filter((k) => next[k] === undefined || next[k] !== before.scope[k])
    .map((k) => ({ key: k, value: String(before.scope[k]).slice(5) }));
}

/**
 * What the sentence should say: the condition plus any grounded scope it doesn't already state. Case-only
 * scope is shown apart (it is what a Widen can drop), and a scope key the condition already tests with
 * the same value would only make the sentence say it twice.
 */
export function withoutCaseScope<T extends Pick<Rule, "scope" | "condition">>(rule: T): T {
  const keys = caseKeys(rule);
  const said = eqClauses(rule.condition);
  const scope = Object.fromEntries(Object.entries(rule.scope ?? {}).filter(([k, v]) => !keys.includes(k) && !(said.has(k) && said.get(k) === v)));
  return Object.keys(scope).length === Object.keys(rule.scope ?? {}).length ? rule : { ...rule, scope };
}

/** `feature → value` for every top-level `eq` clause under `all` (or a single clause). */
function eqClauses(condition: unknown): Map<string, unknown> {
  const out = new Map<string, unknown>();
  const visit = (n: unknown) => {
    if (!n || typeof n !== "object") return;
    const o = n as Record<string, unknown>;
    if (typeof o.f === "string" && o.op === "eq") out.set(o.f, o.v);
    if (Array.isArray(o.all)) o.all.forEach(visit);
  };
  visit(condition);
  return out;
}

/** True for an id ("NS31@2025-01-24:14C", "EIDW@2024-01-21"), false for a sentence. */
export const isId = (s: string | null | undefined) => !!s && !/\s/.test(s.trim());

/**
 * A regulation's source line, "EU261 Art. 5(3): extraordinary circumstances … · weather inside the window":
 * the citation, what it says, and StormCheck's gloss after " · ".
 */
export function splitSource(text: string): { cite: string | null; body: string; gloss: string | null } {
  const [head, ...rest] = text.split(" · ");
  const m = head.match(/^([^:]{2,90}):\s+(.+)$/);
  return { cite: m ? m[1] : null, body: m ? m[2] : head, gloss: rest.length ? rest.join(" · ") : null };
}

/** "the route is EU–US" for an allowlisted feature, else "cohort = Storm Isha". */
export function caseClause(key: string, raw: unknown): string {
  const value = String(raw).replace(/^case:/, "");
  const phrase = clauseText({ f: key, op: "eq", v: value === "true" ? true : value === "false" ? false : value });
  if (!phrase.startsWith(`${key} `)) return phrase;
  const storm = stormName(value);
  return `${key.split(".").pop()?.replace(/_/g, " ")} = ${storm ?? value.replace(/_/g, " ")}`;
}

// ---------- dates ----------

/** "25 Jan 2025 · 09:14Z". */
export const stamp = (iso: string | null | undefined) => (iso ? `${longDate(iso)} · ${zulu(iso)}` : "—");

/** Plan §2 rule 7: a null `valid_from` is a legal interpretation, so it applies to past flights too. */
export function validFromText(rule: Pick<Rule, "valid_from">): { short: string; long: string } {
  if (!rule.valid_from) return { short: "past flights too", long: "Legal interpretation: applies to past flights too" };
  return { short: `from ${longDate(rule.valid_from)}`, long: `Applies to flights from ${longDate(rule.valid_from)} (prospective)` };
}

// ---------- the static regulation card ----------

/**
 * Reg (EU) 2026/2202 is a static, future-dated card (`static_card: true`, plan §1.1): display only, no
 * engine logic. Its facts come from the rule: in force on `recorded_at`, applies from `valid_from`, and
 * a claim window when the condition carries one.
 */
export function staticCardFacts(rule: Rule) {
  const title = regulationTitle(rule);
  const windowMonths = claimWindowMonths(rule.condition) ?? claimWindowMonths(rule.scope);
  const fromText = rule.origin_example?.match(/(\d+)[-\s]month/i)?.[1];
  return {
    title,
    inForce: rule.recorded_at,
    appliesFrom: rule.valid_from,
    claimWindowMonths: windowMonths ?? (fromText ? Number(fromText) : null),
  };
}

export function regulationTitle(rule: Pick<Rule, "id" | "origin_example">): string {
  const fromExample = rule.origin_example?.split(" · ")[0]?.trim();
  if (fromExample && /reg|eu|art/i.test(fromExample)) return fromExample;
  const num = `${rule.id} ${rule.origin_example ?? ""}`.match(/(20\d\d)[/_-](\d{3,4})/);
  return num ? `Reg (EU) ${num[1]}/${num[2]}` : rule.id;
}

function claimWindowMonths(node: unknown): number | null {
  if (!node || typeof node !== "object") return null;
  if (Array.isArray(node)) {
    for (const n of node) {
      const hit = claimWindowMonths(n);
      if (hit !== null) return hit;
    }
    return null;
  }
  const o = node as Record<string, unknown>;
  if (o.f === "claim.age_months" && (o.op === "le" || o.op === "lt") && typeof o.v === "number") return o.v;
  if (typeof o["claim.age_months"] === "number") return o["claim.age_months"] as number;
  for (const k of ["all", "any", "not"]) {
    const hit = claimWindowMonths(o[k]);
    if (hit !== null) return hit;
  }
  return null;
}

// ---------- deep links ----------

/** `#R-CL-1` or `#R-CL-1@1` → the family id. */
export function familyFromHash(hash: string): string | null {
  const raw = decodeURIComponent(hash.replace(/^#/, "")).trim();
  if (!raw) return null;
  return raw.split("@")[0] || null;
}

/** A flight or coupon id inside an origin example ("NS31@2025-01-24:14C" → "NS31@2025-01-24"). */
export function flightOf(example: string | null | undefined): string | null {
  const m = example?.match(/\b([A-Z]{2}\d{1,4}@\d{4}-\d{2}-\d{2})\b/);
  return m ? m[1] : null;
}
