import type { AccessCell, AccessMatrix, BlameStep, Commit, CommitKind, Question, Role, Rule, StormRun } from "@/api/types";
import { ROLE_LABEL, shortId } from "@/lib/format";
import { stormName } from "@/lib/storms";

// ---------- tabs ----------
export const TABS = ["live", "commits", "blame", "access", "controls"] as const;
export type TraceTab = (typeof TABS)[number];
export const isTab = (v: string | null | undefined): v is TraceTab => !!v && (TABS as readonly string[]).includes(v);

export const TAB_LABEL: Record<TraceTab, string> = { live: "Live", commits: "Commits", blame: "Blame", access: "Access", controls: "Controls" };

// ---------- targets (?target=) ----------
const RULE_REF = /^((?:R|REG|HC)-[A-Z0-9-]+?)(?:@\d+)?$/;
const COUPON_REF = /^([A-Z]{2}\d{1,4}@\d{4}-\d{2}-\d{2}):[0-9A-Z]+$/;

/**
 * Whether an event's ref is about a target: the same id, a coupon of the target flight, the flight of a
 * target coupon, or another version of the same rule.
 */
export function matchesTarget(ref: string | null | undefined, target: string): boolean {
  if (!ref) return false;
  if (ref === target || ref.startsWith(`${target}:`)) return true;
  const coupon = target.match(COUPON_REF);
  if (coupon && ref === coupon[1]) return true;
  const a = ref.match(RULE_REF);
  const b = target.match(RULE_REF);
  return !!a && !!b && a[1] === b[1];
}

/** The tab a bare `?target=` opens: its blame, except questions, which have events rather than a chain. */
export const tabForTarget = (target: string): TraceTab => (/^Q-\d+$/.test(target) ? "live" : "blame");

// ---------- event refs ----------
/** Where an event's `ref` lives in the app: a flight or coupon, a storm, a rule, a journal, a question. */
export function eventRef(ref: string | null | undefined): { to: string | null; label: string } | null {
  if (!ref) return null;
  const flight = ref.match(/^([A-Z]{2}\d{1,4}@\d{4}-\d{2}-\d{2})(?::([0-9A-Z]+))?$/);
  if (flight) return { to: `/flights/${encodeURIComponent(flight[1])}`, label: shortId(ref) };
  if (/^[A-Z]{4}@\d{4}-\d{2}-\d{2}$/.test(ref)) return { to: `/run/${encodeURIComponent(ref)}`, label: stormName(ref) ?? ref };
  const rule = ref.match(/^((?:R|REG|HC)-[A-Z0-9-]+?)(?:@\d+)?$/);
  if (rule) return { to: `/policies#${encodeURIComponent(rule[1])}`, label: ref };
  if (/^JE-\d+/.test(ref)) return { to: "/close", label: ref };
  if (/^Q-\d+$/.test(ref)) return { to: "/questions", label: ref };
  return { to: null, label: ref };
}

// ---------- hashes ----------
/** A git-style prefix of a sha256 commit hash. */
export const shortHash = (hash: string | null | undefined, n = 7) => (hash ? hash.replace(/^sha256:/, "").slice(0, n) : "");

/**
 * Newest first, in chain order: walk parents back from the head (the commit nobody names as a parent).
 * Commit times aren't monotonic along the chain (a decision can carry its known-at), so a date sort would
 * scramble it. Falls back to newest-first by time when the loaded commits aren't one chain.
 * `linked` says whether every loaded commit was reached by following parents.
 */
export function chainOrder(commits: Commit[]): { ordered: Commit[]; linked: boolean } {
  if (commits.length < 2) return { ordered: [...commits], linked: true };
  const byHash = new Map(commits.map((c) => [c.hash, c]));
  const parents = new Set(commits.map((c) => c.parent).filter((p): p is string => !!p && byHash.has(p)));
  const heads = commits.filter((c) => !parents.has(c.hash));
  if (heads.length === 1) {
    const ordered: Commit[] = [];
    const seen = new Set<string>();
    for (let c: Commit | undefined = heads[0]; c && !seen.has(c.hash); c = c.parent ? byHash.get(c.parent) : undefined) {
      seen.add(c.hash);
      ordered.push(c);
    }
    if (ordered.length === commits.length) return { ordered, linked: true };
  }
  return { ordered: [...commits].sort((a, b) => b.at.localeCompare(a.at)), linked: false };
}

/**
 * Whether a newest-first list also runs newest-first in time. Commits and events can carry the time they
 * are about (a journal's event date, a decision's known-at) rather than when they were written, so day
 * headers are only honest when this holds; otherwise each row shows its own date.
 */
export const timeOrdered = (items: { at: string }[]) => items.every((x, i) => i === 0 || items[i - 1].at >= x.at);

/** Commit kinds in the order a storm night produces them. */
export const KIND_ORDER: CommitKind[] = ["fact", "llm_call", "decision", "entitlement", "question", "ruling", "rule_event", "journal_event", "period_lock", "revert", "access_denied", "clock"];

// ---------- principals (people and agents) ----------
const ROLES = Object.keys(ROLE_LABEL) as Role[];
const PEOPLE_ORDER: Role[] = ["claims_lead", "legal", "controller", "ops", "cfo", "judge"];
const AGENT_ORDER: Role[] = ["agent.reader", "agent.drafter", "agent.engine", "agent.crm_bot"];

/**
 * The role behind a principal string, wherever the API puts it: "agent.drafter", "claims_lead",
 * "person:claims_lead", "claims_lead:Aoife", "agent:drafter", "drafter". Unknown principals stay null
 * and are shown as written.
 */
export function principalRole(principal: string | null | undefined): Role | null {
  if (!principal) return null;
  const parts = principal
    .trim()
    .toLowerCase()
    .split(/[:/]/)
    .map((p) => p.trim().replace(/\s+/g, "_"))
    .filter(Boolean);
  for (const p of parts) {
    if ((ROLES as string[]).includes(p)) return p as Role;
    if ((ROLES as string[]).includes(`agent.${p}`)) return `agent.${p}` as Role;
  }
  if (parts[0] === "agent" && parts[1] && (ROLES as string[]).includes(`agent.${parts[1]}`)) return `agent.${parts[1]}` as Role;
  const byLabel = ROLES.find((r) => ROLE_LABEL[r].toLowerCase().replace(/\s+/g, "_") === parts.join("_"));
  return byLabel ?? null;
}

export const isAgent = (principal: string) => principal.toLowerCase().startsWith("agent") || (principalRole(principal) ?? "").startsWith("agent.");

/** People first (in seat order), then agents, then anything unknown, keeping the API's order otherwise. */
export function orderPrincipals(principals: string[]): string[] {
  const rank = (p: string) => {
    const r = principalRole(p);
    if (r && PEOPLE_ORDER.includes(r)) return PEOPLE_ORDER.indexOf(r);
    if (r && AGENT_ORDER.includes(r)) return 10 + AGENT_ORDER.indexOf(r);
    return isAgent(p) ? 30 : 20;
  };
  return principals.map((p, i) => ({ p, i })).sort((a, b) => rank(a.p) - rank(b.p) || a.i - b.i).map(({ p }) => p);
}

/** "Claims Lead", "Drafter agent", or the principal as written. */
export function principalLabel(principal: string): string {
  const role = principalRole(principal);
  return role ? ROLE_LABEL[role] : principal;
}

// ---------- access ----------
/** Strongest first. `redacted` reads the record with PII masked. */
export const CELL_ORDER: AccessCell[] = ["approve", "write", "read", "redacted", "none"];

export const CELL_HINT: Record<AccessCell, string> = {
  approve: "Can approve (and read)",
  write: "Can write drafts (and read)",
  read: "Can read",
  redacted: "Reads it with PII masked",
  none: "No access",
};

/**
 * The resource that holds passenger PII: one the broker names that way, else one it serves `redacted` to some
 * seat (that is what redacted means), preferring claims, where a passenger's own words and name live.
 */
export function piiResource(matrix: AccessMatrix | undefined): string | null {
  if (!matrix) return null;
  const named = matrix.resources.find((r) => /pii|passenger|personal/i.test(r));
  if (named) return named;
  const redacted = matrix.resources.filter((r) => matrix.principals.some((p) => matrix.cells[p]?.[r] === "redacted"));
  return redacted.find((r) => /claim/i.test(r)) ?? redacted[0] ?? null;
}

/** The short reason in `agent.drafter approve_payout → DENIED · SoD`. */
export function denialTag(reason: string | null | undefined): string {
  const r = (reason ?? "").toLowerCase();
  if (/\bsod\b|sod_|segregation|preparer|same person/.test(r)) return "SoD";
  if (/\bpii\b|redact|personal data/.test(r)) return "PII";
  if (/lock/.test(r)) return "locked period";
  if (/external/.test(r)) return "external party";
  if (/materiality|material\b/.test(r)) return "materiality";
  if (/authority|authori[sz]/.test(r)) return "authority";
  if (/least.privilege|scope|not permitted|forbidden|no access/.test(r)) return "least privilege";
  const head = (reason ?? "").split(/[.:;(]/)[0].trim();
  return head || "denied";
}

// ---------- controls ----------
/** Where a control's evidence endpoint can be seen in the app. */
export function evidenceTarget(endpoint: string): { to: string; label: string } | null {
  const path = endpoint
    .replace(/^(GET|POST)\s+/i, "")
    .replace(/^https?:\/\/[^/]+/i, "")
    .replace(/^\/api(?=\/)/, "")
    .trim();
  const table: [RegExp, string, string][] = [
    [/^\/access\/log/, "/trace?tab=access#denied", "Denied log"],
    [/^\/access/, "/trace?tab=access", "Access matrix"],
    [/^\/(commits|trace)/, "/trace?tab=commits", "Commits"],
    [/^\/blame/, "/trace?tab=blame", "Blame"],
    [/^\/(rules|proposals)/, "/policies", "Policies"],
    [/^\/books\/invariants/, "/close#invariants", "Invariants"],
    [/^\/(books|audit)/, "/close", "Liability & Close"],
    [/^\/questions/, "/questions", "Questions"],
    [/^\/eval/, "/proof", "Proof"],
    [/^\/controls/, "/trace?tab=controls", "Controls"],
  ];
  for (const [re, to, label] of table) if (re.test(path)) return { to, label };
  return null;
}

/** SOC 2 trust-services references sort CC6.1 < CC6.3 < CC7.2 < CC8.1 < PI1.x. */
export function compareFrameworkRef(a: string, b: string) {
  return a.localeCompare(b, "en", { numeric: true });
}

// ---------- blame ----------
export type StepKind = "money" | "entitlement" | "rule" | "ruling" | "decision" | "fact" | "span" | "metar" | "other";

/** A raw METAR line ("EIDW 241630Z 24012KT …"). */
export const METAR_LINE = /\b[A-Z]{4} \d{6}Z\b/;

/** How a blame step reads on the receipt. The API gives labels and commits; this only picks the styling. */
export function stepKind(step: Pick<BlameStep, "label" | "quote"> & { commit: Pick<Commit, "kind"> }): StepKind {
  const label = step.label.toLowerCase();
  if (/\bmetar\b/.test(label) || (!!step.quote && METAR_LINE.test(step.quote) && step.commit.kind === "fact")) return "metar";
  if (step.commit.kind === "ruling" || /^(ruling|ruled)\b/.test(label)) return "ruling";
  if (step.commit.kind === "rule_event" || /^rule\b/.test(label)) return "rule";
  if (step.commit.kind === "entitlement" || /^entitlement/.test(label)) return "entitlement";
  if (step.commit.kind === "journal_event" || /€|liabilit/.test(label)) return "money";
  if (/\bspan\b|verbatim|quote/.test(label)) return "span";
  if (step.commit.kind === "decision" || /^decision\b/.test(label)) return "decision";
  if (step.commit.kind === "fact") return "fact";
  return "other";
}

export const STEP_NAME: Record<StepKind, string> = {
  money: "Amount",
  entitlement: "Entitlement",
  rule: "Rule",
  ruling: "Ruling",
  decision: "Decision",
  fact: "Fact",
  span: "Source span",
  metar: "METAR obs",
  other: "Step",
};

/** A rule reference inside a label: "R-LEG-1@1", "REG-C549-TECHNICAL@1", "HC-SOD-1". */
export const ruleRefIn = (text: string) => text.match(/\b(?:R|REG|HC)-[A-Z0-9]+(?:-[A-Z0-9]+)*(?:@\d+)?\b/)?.[0] ?? null;

/** A ref the blame tab can walk back from: a flight or coupon, a journal, or a rule version. */
export function blameTarget(ref: string): string | null {
  const bare = ref.replace(/^(decision|entitlement|rule|je|journal|question|ruling|fact|flight|coupon):/i, "");
  return /^[A-Z]{2}\d{1,4}@\d{4}-\d{2}-\d{2}(:[0-9A-Z]+)?$/.test(bare) || /^(?:R|REG|HC)-[A-Z0-9-]+@\d+$/.test(bare) || /^JE-\d+$/.test(bare) ? bare : null;
}

/** The plain-text receipt an auditor can paste into a working paper. */
export function receiptText(target: string, steps: BlameStep[], origin: string) {
  const lines = [`StormCheck blame · ${target}`, ""];
  steps.forEach((s, i) => {
    lines.push(`${String(i + 1).padStart(2, "0")}  ${s.label}`);
    if (s.quote) lines.push(`    "${s.quote}"`);
    lines.push(`    ${s.commit.kind} · ${shortHash(s.commit.hash, 12)} · ${s.commit.actor} · ${s.commit.at}`);
  });
  lines.push("", `${origin}/trace?tab=blame&target=${encodeURIComponent(target)}`);
  return lines.join("\n");
}

// ---------- blame targets ----------
export type BlameTarget = { id: string; title: string; hint: string };

const RULING_TIERS: Rule["tier"][] = ["legal_ruling", "controller_ruling", "claims_lead_ruling"];
const COUPON = /^[A-Z]{2}\d{1,4}@\d{4}-\d{2}-\d{2}:[0-9A-Z]+$/;

/**
 * A few targets worth walking back, found in the data rather than typed in: the recoded flight's
 * liability, a weather flight, a knock-on return, and each ruling's own case and rule.
 */
export function suggestTargets(run: StormRun | undefined, rules: Rule[] | undefined): BlameTarget[] {
  const out: BlameTarget[] = [];
  const rows = run?.flights ?? [];
  const owed = rows.find((r) => r.decision?.recoded && r.decision.extraordinary === "not_extraordinary") ?? rows.find((r) => r.decision?.extraordinary === "not_extraordinary");
  if (owed) out.push({ id: owed.flight.id, title: `${owed.flight.number} liability`, hint: owed.decision?.recode_label ? `recoded ${owed.decision.recode_label}` : "owed" });
  const weather = rows.find((r) => r.flight.status === "cancelled" && r.decision?.extraordinary === "extraordinary" && r.decision.cause === "weather");
  if (weather) out.push({ id: weather.flight.id, title: `${weather.flight.number} · weather`, hint: "no compensation; refunds and care still due" });
  const knock = rows.find((r) => r.decision?.cause === "knock_on");
  if (knock) out.push({ id: knock.flight.id, title: `${knock.flight.number} · knock-on return`, hint: "ruled on by Legal" });
  // Rules in force only: a widened version waiting in shadow isn't something to audit yet.
  const ruled = (rules ?? []).filter((r) => RULING_TIERS.includes(r.tier) && (r.status === "active" || r.status === "suspect"));
  ruled.sort((a, b) => RULING_TIERS.indexOf(b.tier) - RULING_TIERS.indexOf(a.tier));
  for (const r of ruled) {
    if (r.origin_example && COUPON.test(r.origin_example)) out.push({ id: r.origin_example, title: `${shortId(r.origin_example)} · ${ROLE_LABEL[r.authority_required]} ruling`, hint: `cites ${r.id}@${r.version}` });
    out.push({ id: `${r.id}@${r.version}`, title: `${r.id}@${r.version}`, hint: `${ROLE_LABEL[r.authority_required]} ruling → rule` });
  }
  const seen = new Set<string>();
  return out.filter((t) => (seen.has(t.id) ? false : (seen.add(t.id), true)));
}

// ---------- the PII record ----------
/** What the API puts where it removed PII. */
export const REDACTED = "[redacted]";

/** Evidence fields that carry a person's identity (a name, an email, a phone number, a booking reference). */
export const isPiiField = (field: string) => /(^|[._])(name|email|e_mail|phone|address|dob|passport|booking_ref|pnr)$/i.test(field);

export type PiiRecord = { question: Question; fields: { field: string; value: string }[]; text: string; values: string[] };

/** The first served question that carries passenger identity in its evidence, with the PII values in the clear (if this seat got them). */
export function findPiiRecord(questions: Question[] | undefined): PiiRecord | null {
  for (const q of questions ?? []) {
    const fields = q.evidence.filter((e) => isPiiField(e.field)).map((e) => ({ field: e.field, value: String(e.value ?? e.quote ?? "") }));
    if (!fields.length) continue;
    const values = [...new Set(fields.map((f) => f.value).filter((v) => v && v !== REDACTED))];
    return { question: q, fields, text: q.found, values };
  }
  return null;
}

/** Split text into plain runs and PII runs: the clear values this seat was given, and the API's redaction marks. */
export function splitPii(text: string, values: string[]): { text: string; pii: boolean }[] {
  const needles = [...values, REDACTED].filter(Boolean).sort((a, b) => b.length - a.length);
  const out: { text: string; pii: boolean }[] = [];
  let rest = text;
  while (rest) {
    let best: { at: number; len: number } | null = null;
    for (const n of needles) {
      const at = rest.indexOf(n);
      if (at >= 0 && (!best || at < best.at)) best = { at, len: n.length };
    }
    if (!best) {
      out.push({ text: rest, pii: false });
      break;
    }
    if (best.at > 0) out.push({ text: rest.slice(0, best.at), pii: false });
    out.push({ text: rest.slice(best.at, best.at + best.len), pii: true });
    rest = rest.slice(best.at + best.len);
  }
  return out;
}
