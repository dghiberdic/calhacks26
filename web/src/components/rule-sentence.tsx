import { Fragment, type ReactNode } from "react";
import type { DslNode, Rule, RuleAction } from "@/api/types";
import { ROLE_LABEL } from "@/lib/format";
import { cn } from "@/lib/utils";

/**
 * Rules are data, never a free-text editor (plan §2 rule 3): this renders the DSL (CONTRACTS §4) as the
 * sentence a person would say, and shows which words of the ruling ground each literal.
 */

type Clause = { f: string; op: string; v?: unknown };

const isClause = (n: unknown): n is Clause => !!n && typeof n === "object" && "f" in (n as Record<string, unknown>);

/** Plain phrases for the allowlisted features. Anything else falls back to `feature op value` in mono. */
const FEATURE: Record<string, (op: string, v: unknown) => string | null> = {
  "voucher.in_lieu": (op, v) => (truthy(op, v) ? "the voucher was given in lieu of compensation" : "the voucher wasn't given in lieu of compensation"),
  "voucher.signed": (op, v) => (truthy(op, v) ? "the passenger signed for it" : "there is no signed acceptance"),
  "voucher.amount_cents": (op, v) => `the voucher is ${opWord(op)} €${Number(v) / 100}`,
  "flight.departs_eu": (op, v) => (truthy(op, v) ? "the flight leaves the EU" : "the flight doesn't leave the EU"),
  "flight.arrives_eu": (op, v) => (truthy(op, v) ? "the flight lands in the EU" : "the flight doesn't land in the EU"),
  "flight.operating_carrier_eu": (op, v) => (truthy(op, v) ? "the operating carrier is an EU carrier" : "the operating carrier isn't an EU carrier"),
  "flight.is_return_sector": (op, v) => (truthy(op, v) ? "it's a return sector" : "it isn't a return sector"),
  "flight.in_window_dep": (op, v) => `the departure is ${op === "ne" ? "not " : ""}${String(v)} the storm window`,
  "flight.in_window_arr": (op, v) => `the arrival is ${op === "ne" ? "not " : ""}${String(v)} the storm window`,
  "flight.window_margin_min": (op, v) => `the window margin is ${opWord(op)} ${v} min`,
  "flight.distance_km": (op, v) => `the flight is ${opWord(op)} ${Number(v).toLocaleString("en-IE")} km`,
  "flight.band_eur": (op, v) => `the compensation band is ${opWord(op)} €${v}`,
  "flight.route_region": (op, v) => `the route is ${op === "ne" ? "not " : ""}${String(v).replace("_", "–")}`,
  "flight.ops_cause_code": (op, v) => `OCC coded it ${op === "ne" ? "anything but " : ""}${String(v)}`,
  "aog.before_window": (op, v) => (truthy(op, v) ? "the aircraft was grounded before the storm window" : "the aircraft wasn't grounded before the window"),
  "aog.inside_window": (op, v) => (truthy(op, v) ? "the aircraft was grounded inside the storm window" : "the grounding wasn't inside the window"),
  "aog.ata_chapter": (_op, v) => `the defect is in ATA chapter ${String(v)}`,
  "aog.root_cause_internal": (op, v) => (truthy(op, v) ? "the root cause is internal to the airline" : "the root cause is external"),
  "aog.mel_relief": (op, v) => (truthy(op, v) ? "the MEL allows dispatch" : "there is no MEL relief"),
  "rotation.prev_cancelled": (op, v) => (truthy(op, v) ? "the previous rotation was cancelled" : "the previous rotation operated"),
  "rotation.prev_cause": (_op, v) => `the previous rotation's cause was ${String(v)}`,
  "spare.available_within_h": (op, v) => (op === "gt" || op === "ge" ? `no aircraft and crew could operate it within ${v} h` : `a spare could operate it within ${v} h`),
  "pax.notice_days": (op, v) => `passengers had ${opWord(op)} ${v} days' notice`,
  "pax.arrival_delay_min": (op, v) => `passengers arrived ${opWord(op)} ${Number(v) / 60} h late`,
  "pax.election": (_op, v) => `the passenger chose ${String(v).replace(/_/g, " ")}`,
  "pax.reroute_earliest_offered": (op, v) => (truthy(op, v) ? "passengers were offered the earliest reroute on any carrier" : "the earliest reroute wasn't offered"),
  "pax.fare_type": (_op, v) => `the ticket is ${String(v) === "staff_id90" ? "a staff ID90 ticket" : "a revenue ticket"}`,
  "claim.channel": (_op, v) => `the claim came ${String(v) === "agency" ? "through an agency" : "directly"}`,
  "claim.authority": (_op, v) => `the agency's authority is ${String(v)}`,
  "claim.duplicate": (op, v) => (truthy(op, v) ? "the claim is a duplicate" : "the claim isn't a duplicate"),
  "claim.age_months": (op, v) => `the claim is ${opWord(op)} ${v} months old`,
  "claim.after_limitation": (op, v) => (truthy(op, v) ? "the claim arrived after the limitation period" : "the claim is within the limitation period"),
  "claim.regime": (_op, v) => `the claim cites ${String(v)}`,
  "cohort.age_months": (op, v) => `the cohort is ${opWord(op)} ${v} months old`,
  "cohort.months_since_last_claim": (op, v) => `there have been no new claims for ${opWord(op)} ${v} months`,
  "cohort.limitation_expired": (op, v) => (truthy(op, v) ? "the six-year limitation has expired" : "the six-year limitation hasn't expired"),
  "sources.disagree": (op, v) => (truthy(op, v) ? "the sources disagree" : "the sources agree"),
  "precedent.count": (op, v) => `there ${Number(v) === 1 ? "is" : "are"} ${opWord(op)} ${v} precedent${Number(v) === 1 ? "" : "s"}`,
};

function truthy(op: string, v: unknown) {
  return op === "eq" ? v === true || v === "true" : op === "ne" ? !(v === true || v === "true") : op === "exists";
}

function opWord(op: string) {
  return { eq: "", ne: "not", lt: "under", le: "at most", gt: "over", ge: "at least", in: "one of", nin: "none of", exists: "" }[op] ?? op;
}

export function clauseText(c: Clause): string {
  const phrase = FEATURE[c.f]?.(c.op, c.v);
  return phrase ?? `${c.f} ${c.op} ${JSON.stringify(c.v)}`;
}

const ACTION: Record<RuleAction, (arg?: string | null) => string> = {
  set_extraordinary: () => "treat it as extraordinary: no compensation; refunds and care still due",
  set_not_extraordinary: () => "treat it as not extraordinary: compensation is owed",
  allow_offset: () => "allow the voucher to offset the compensation",
  deny_offset: () => "no offset: pay the compensation in cash; the voucher stays as goodwill",
  deny_release: () => "don't release the liability",
  keep_tail: () => "keep the expected tail until the six-year limitation, then derecognise",
  apply_7_2_reduction: () => "apply the Art. 7(2) 50% reduction",
  route_to: (arg) => `route it to ${arg ? (ROLE_LABEL[arg as keyof typeof ROLE_LABEL] ?? arg) : "a person"}`,
};

export const actionText = (rule: Pick<Rule, "action" | "action_arg">) => ACTION[rule.action]?.(rule.action_arg) ?? rule.action;

function flatten(node: unknown, mode: "all" | "any" = "all"): { clauses: Clause[]; mode: "all" | "any"; negated: Clause[] } {
  if (isClause(node)) return { clauses: [node], mode, negated: [] };
  const n = node as Partial<Record<"all" | "any" | "not", unknown>>;
  if (Array.isArray(n.all) || Array.isArray(n.any)) {
    const kids = (n.all ?? n.any) as unknown[];
    const m: "all" | "any" = n.all ? "all" : "any";
    const out = { clauses: [] as Clause[], mode: m, negated: [] as Clause[] };
    for (const k of kids) {
      const f = flatten(k, m);
      out.clauses.push(...f.clauses);
      out.negated.push(...f.negated);
    }
    return out;
  }
  if (n.not) {
    const f = flatten(n.not, mode);
    return { clauses: [], mode, negated: [...f.clauses, ...f.negated] };
  }
  return { clauses: [], mode, negated: [] };
}

/** Scope entries become clauses too; `case:` values are the ones a "Widen" can still remove. */
function scopeClauses(scope: Record<string, unknown>) {
  return Object.entries(scope).map(([f, raw]) => {
    const fromCase = typeof raw === "string" && raw.startsWith("case:");
    const v = fromCase ? parse((raw as string).slice(5)) : raw;
    return { clause: { f, op: "eq", v } as Clause, fromCase };
  });
}

function parse(s: string): unknown {
  if (s === "true") return true;
  if (s === "false") return false;
  const n = Number(s);
  return Number.isFinite(n) && s.trim() !== "" ? n : s;
}

/** "When …, and …: <action>." with case-only scope marked. */
/** Every feature a DSL condition names ({all|any|not} trees of {f, op, v} clauses). */
function namedFeatures(node: unknown, out = new Set<string>()): Set<string> {
  if (!node || typeof node !== "object") return out;
  const n = node as Record<string, unknown>;
  if (typeof n.f === "string") out.add(n.f);
  for (const key of ["all", "any"]) if (Array.isArray(n[key])) for (const kid of n[key] as unknown[]) namedFeatures(kid, out);
  if (n.not) namedFeatures(n.not, out);
  return out;
}

export function RuleSentence({ rule, className }: { rule: Pick<Rule, "condition" | "scope" | "action" | "action_arg">; className?: string }) {
  const { clauses, mode, negated } = flatten(rule.condition as DslNode);
  // Scope keys the condition already states would read twice ("…the flight leaves the EU, and the flight
  // leaves the EU"); only case-specific scope ("the voucher is €300") adds anything.
  const named = namedFeatures(rule.condition);
  const scope = scopeClauses(Object.fromEntries(Object.entries(rule.scope ?? {}).filter(([k]) => !named.has(k))));
  const parts: { text: string; fromCase?: boolean; negated?: boolean }[] = [
    ...clauses.map((c) => ({ text: clauseText(c) })),
    ...negated.map((c) => ({ text: `not: ${clauseText(c)}`, negated: true })),
    ...scope.map((s) => ({ text: clauseText(s.clause), fromCase: s.fromCase })),
  ];
  const joiner = mode === "any" ? " or " : ", and ";
  return (
    <p className={cn("text-[15px] leading-relaxed text-navy-900", className)}>
      {parts.length ? "When " : "Always: "}
      {parts.map((p, i) => (
        <Fragment key={i}>
          {i > 0 ? (i === parts.length - 1 && mode === "all" ? ", and " : joiner) : null}
          <span className={cn(p.fromCase && "rounded bg-cloud-100 px-1 text-slate-600")} title={p.fromCase ? "Copied from the case; a Widen can drop it" : undefined}>
            {p.text}
            {p.fromCase ? <span className="ml-1 font-mono text-[10.5px] text-slate-400">case</span> : null}
          </span>
        </Fragment>
      ))}
      {parts.length ? ": " : ""}
      <strong className="font-semibold">{actionText(rule)}</strong>.
    </p>
  );
}

/**
 * The ruler's own words, with each grounding phrase highlighted (`grounding`: literal → phrase).
 * This is what makes a rule auditable: every literal in it points at words a person wrote.
 */
export function GroundedQuote({ text, grounding, className }: { text: string; grounding?: Record<string, string>; className?: string }) {
  const phrases = Object.entries(grounding ?? {})
    .map(([literal, phrase]) => ({ literal, phrase }))
    .filter((g) => g.phrase && text.toLowerCase().includes(g.phrase.toLowerCase()))
    .sort((a, b) => b.phrase.length - a.phrase.length);
  if (!phrases.length) return <blockquote className={cn("text-[14.5px] leading-relaxed text-navy-900", className)}>&ldquo;{text}&rdquo;</blockquote>;

  const lower = text.toLowerCase();
  const marks: { start: number; end: number; literal: string }[] = [];
  for (const g of phrases) {
    const start = lower.indexOf(g.phrase.toLowerCase());
    if (start >= 0 && !marks.some((m) => start < m.end && start + g.phrase.length > m.start)) marks.push({ start, end: start + g.phrase.length, literal: g.literal });
  }
  marks.sort((a, b) => a.start - b.start);
  const out: ReactNode[] = [];
  let at = 0;
  marks.forEach((m, i) => {
    if (m.start > at) out.push(text.slice(at, m.start));
    out.push(
      <mark key={i} className="rounded-sm bg-metar-wash px-0.5 text-navy-900 shadow-[inset_0_-2px_0_var(--color-metar)]" title={`grounds ${m.literal}`}>
        {text.slice(m.start, m.end)}
      </mark>,
    );
    at = m.end;
  });
  if (at < text.length) out.push(text.slice(at));
  return <blockquote className={cn("text-[14.5px] leading-relaxed text-navy-900", className)}>&ldquo;{out}&rdquo;</blockquote>;
}

export const TIER_LABEL: Record<Rule["tier"], string> = {
  hard_control: "hard control",
  regulation: "regulation",
  legal_ruling: "Legal ruling",
  controller_ruling: "Controller ruling",
  claims_lead_ruling: "Claims Lead ruling",
  mined: "learned from history",
};

/** "R-CL-1@1". */
export const ruleRef = (rule: Pick<Rule, "id" | "version">) => `${rule.id}@${rule.version}`;
