// Writes (CONTRACTS §3): rulings → rule proposals → confirm/reject/widen/revert, journal approval with
// segregation of duties, month end, period lock, the forward-only clock, and challenges. Every write
// appends trace events (and commits); every view is recomputed from the stores on the next read.
import type { ChallengeResponse, Evidence, JournalLine, ReplayDiff, Rule, RuleProposal, Ruling } from "@/api/types";
import { bandFor } from "./data/airports";
import { cr, dr, COHORT_ISHA, COHORT_LH, COHORT_MED, COHORT_SHORT, je, MONTH_END_IDS, rollforward } from "./data/books";
import { decide, HERO_FLIGHT, isHeld, voucherCases, voucherSettled } from "./data/engine";
import { EOWYN_ID, HERMINIA_ID } from "./data/flights";
import { allCohortsQuestion, bosDubQuestion, hiddenDefectQuestion, opsQuestion, type MockQuestion } from "./data/questions";
import { ground, proposeQ1, proposeQ2, proposeQ3, ruleRef, widenOnce, type Proposed } from "./data/rules";
import { addMin, eur, hhmmZ, isoZ, nearestObs } from "./data/util";
import { hubOf, mainWindow, metarEv, scheduleEv, windowLabel, type StormDef } from "./data/world";
import { bodyOf, fail, ok, ROLE_NAME, str, type Reply, type Req } from "./reply";
import { diffSnaps, simulate, snapshot, withActive, type Snap } from "./replay";
import {
  activeRule,
  addCommit,
  citations,
  commitDecision,
  ctxOf,
  emit,
  nextAt,
  nextJeId,
  nextQuestionId,
  nextRulingId,
  openPeriod,
  publicQuestion,
  rulesView,
  S,
  specOf,
  stormOfFlight,
  type MockState,
} from "./state";

const CHECKS_OK = { compiles: true, reproduces_case: true, no_hard_control: true, grounded: true, author_has_authority: true, no_conflict: true };
const refOf = (r: Pick<Rule, "id" | "version">) => ruleRef(r);
const nextVersion = (s: MockState, id: string) => Math.max(0, ...s.rules.filter((r) => r.id === id).map((r) => r.version)) + 1;

/** "R-CL-1@1" exactly, or "R-CL-1" → the latest pending proposal, else the latest active version. */
function resolveRule(s: MockState, ref: string, prefer: "pending" | "active"): Rule | undefined {
  if (ref.includes("@")) return s.rules.find((r) => refOf(r) === ref);
  const versions = s.rules.filter((r) => r.id === ref).sort((a, b) => b.version - a.version);
  const pending = versions.find((r) => s.proposals.has(refOf(r)));
  const active = versions.find((r) => r.status === "active");
  return prefer === "pending" ? (pending ?? active ?? versions[0]) : (active ?? pending ?? versions[0]);
}

const ruleQuestion = (s: MockState, r: Rule) => {
  const ruling = s.rulings.find((x) => x.id === r.origin_ruling_id);
  return ruling?.question_id ? s.questions.find((q) => q.id === ruling.question_id) : undefined;
};

/** The coupon a voucher question was asked about is the ruling itself, so would_flip lists the other cases it reaches. */
const flipExclusions = (q: MockQuestion | undefined) => (q?.pattern === "voucher_in_lieu_unsigned" ? q.case_refs : []);

/** Adjustments land in the first open period: on the clock's date if that period is open, else at its month end. */
function adjustmentDate(s: MockState) {
  const p = openPeriod(s, s.knownAt.slice(0, 7));
  if (p === s.knownAt.slice(0, 7)) return s.knownAt.slice(0, 10);
  const [y, m] = p.split("-").map(Number);
  return isoZ(Date.UTC(y, m, 0)).slice(0, 10);
}

/** Éowyn's 2140 cohorts: NS31 is the long-haul cohort; other owed or held flights accrue by segment. Other storms aren't in the books. */
function cohortOf(s: MockState, entityId: string): string | null {
  const flightId = entityId.split(":")[0];
  if (flightId === HERO_FLIGHT) return COHORT_LH;
  const hit = specOf(s, flightId);
  if (!hit || hit.storm.id !== EOWYN_ID) return null;
  const seg = bandFor(hit.spec.flight.origin, hit.spec.flight.dest).segment;
  return seg === "medium_1500_3500" ? COHORT_MED : seg === "short_le1500" ? COHORT_SHORT : COHORT_LH;
}

/** Books an Éowyn change in estimate for the flips' € deltas (Dr/Cr 2140 by cohort against 4090). Returns the JE id or null. */
export function postEstimateChange(s: MockState, diff: ReplayDiff, memo: string, sourceDecision: string | null): string | null {
  const byCohort = new Map<string, number>();
  for (const f of diff.flips) {
    const cohort = cohortOf(s, f.entity_id);
    if (!cohort || !f.delta_cents) continue;
    byCohort.set(cohort, (byCohort.get(cohort) ?? 0) + f.delta_cents);
  }
  const total = [...byCohort.values()].reduce((a, b) => a + b, 0);
  if (!byCohort.size || total === 0) return null;
  const lines: JournalLine[] = [];
  for (const [cohort, delta] of byCohort) {
    const dims = { storm: EOWYN_ID, cohort };
    lines.push(delta < 0 ? dr("2140", -delta, dims) : cr("2140", delta, dims));
  }
  lines.push(total < 0 ? cr("4090", -total, { storm: EOWYN_ID }) : dr("4090", total, { storm: EOWYN_ID }));
  const ordered = [...lines.filter((l) => l.dr_cents), ...lines.filter((l) => l.cr_cents)];
  const id = nextJeId(s);
  const entry = je({ id, event_date: adjustmentDate(s), memo, lines: ordered, kind: "change_in_estimate", ias8_class: "change_in_estimate", status: "draft", preparer: "agent.engine", source_decision_id: sourceDecision, built_from: diff.flips.length, ties_to: ["2140"] });
  s.journal.push(entry);
  addCommit(s, "journal_event", "agent.engine", nextAt(s), entry, `je:${id}`, memo);
  return id;
}

// ---------- answer ----------
export function answerQuestion(req: Req, qid: string): Reply {
  const s = S();
  const q = s.questions.find((x) => x.id === qid);
  if (!q) return fail(404, "not_found", `No question ${qid}.`);
  if (req.role !== q.routed_to) return fail(403, "forbidden", `Only the ${ROLE_NAME[q.routed_to]} can answer ${qid}.`);
  if (q.status === "answered") return fail(422, "validation", `${qid} is already answered.`);
  const b = bodyOf(req);
  const decision = str(b.decision);
  const explanation = str(b.explanation);
  if (!decision) return fail(422, "validation", "Pick an option or write the decision first.");
  const at = nextAt(s);
  const rulingId = nextRulingId(s);
  const text = explanation ? `${decision} ${explanation}` : decision;
  let kind: Ruling["kind"] = "answer";
  let proposed: Proposed | null = null;
  let after: (() => void) | null = null;

  switch (q.pattern) {
    case "voucher_in_lieu_unsigned": {
      const offset = /\boffset\b/i.test(decision) && !/\bno offset\b/i.test(decision);
      if (/confirm in writing|ask the passenger|ask legal|hold the/i.test(decision)) break;
      if (q.id === "Q-1" || !activeRule(s, "R-CL-1")) proposed = proposeQ1(text, rulingId, at, offset);
      else {
        // The BOS→DUB case: the same answer for flights that don't leave the EU widens R-CL-1 past departs_eu.
        const current = activeRule(s, "R-CL-1");
        const scope = { ...current.scope };
        delete scope["flight.departs_eu"];
        const condition = { all: [{ f: "voucher.in_lieu", op: "eq", v: true }, { f: "voucher.signed", op: "eq", v: false }] };
        const g = ground(text, { departs_eu: ["here too", "for non-EU departures", "every flight", "any departure"] });
        proposed = {
          rule: { ...current, version: current.version + 1, scope, condition, action: offset ? "allow_offset" : "deny_offset", origin_ruling_id: rulingId, origin_example: q.case_refs[0], grounding: { ...current.grounding, ...g.grounding }, recorded_at: at, status: "shadow", supersedes: refOf(current), times_cited: 0 },
          checks: { ...CHECKS_OK, no_hard_control: !offset },
          widen_next: null,
        };
      }
      break;
    }
    case "knock_on_return": {
      const mode = /not extraordinary|compensate/i.test(decision) ? "owed" : /no conditions|every return/i.test(decision) ? "always" : "conditional";
      proposed = proposeQ2(text, rulingId, at, mode);
      break;
    }
    case "cohort_release": {
      if (/reject|never release|keep the tail|keep \(ultimate/i.test(decision)) {
        kind = "rejection";
        proposed = proposeQ3(text, rulingId, at);
      } else if (!/re-test|next quarter/i.test(decision)) after = () => derecogniseIsha(s, rulingId);
      break;
    }
    case "rule_widen": {
      const current = activeRule(s, "R-CTL-1");
      if (current && /^yes|every storm cohort|all storm cohorts/i.test(decision)) {
        const w = widenOnce(current, at);
        if (w) proposed = { rule: { ...w.rule, origin_ruling_id: rulingId, grounding: { ...w.rule.grounding, ...ground(text, { cohort: ["every storm cohort", "all storm cohorts", "every"] }).grounding } }, checks: { ...CHECKS_OK }, widen_next: null };
      }
      break;
    }
    default:
      break; // new legal patterns and Ops checks are recorded as rulings; no rule is drafted from them here
  }

  const ruling: Ruling = { id: rulingId, question_id: qid, author_role: req.role, author: req.session.name, kind, decision, explanation, at };
  s.rulings.push(ruling);
  q.status = "answered";
  emit(s, { at, kind: "ruling", actor: req.session.principal, summary: `${ROLE_NAME[req.role]} ${kind === "rejection" ? "rejected the proposal in" : "ruled on"} ${qid}: "${decision}"`, ref: rulingId, chip: "RULED", amount_cents: q.holds_cents ?? null }, q.storm_id, { payload: ruling });

  let proposal: RuleProposal | null = null;
  if (proposed) {
    const version = Math.max(proposed.rule.version, nextVersion(s, proposed.rule.id));
    const rule: Rule = { ...proposed.rule, version };
    const ref = refOf(rule);
    const would_flip = diffSnaps(snapshot(s), simulate(s, withActive(s, rule)), ref, s.knownAt, s.locked, flipExclusions(q));
    proposal = { rule, checks: proposed.checks, would_flip, widen_next: proposed.widen_next };
    s.rules.push(rule);
    s.proposals.set(ref, proposal);
    emit(s, { kind: "rule", actor: "agent.drafter", summary: `Drafted ${ref} from the ruling · would change ${would_flip.flips.length} past decisions · Δ${eur(would_flip.total_delta_cents)} · waiting for confirm`, ref, chip: "INFO" }, q.storm_id, { payload: proposal, inputs: [`ruling:${rulingId}`, "prompt:drafter-v1"] });
  }
  after?.();
  return ok({ ruling, proposal });
}

function derecogniseIsha(s: MockState, rulingId: string) {
  const id = nextJeId(s);
  const memo = `Storm Isha cohort tail derecognised on the Controller's ruling (${rulingId}) · €3,600 · drafted, pending approval`;
  const entry = je({ id, event_date: adjustmentDate(s), memo, lines: [dr("2140", 360_000, { cohort: COHORT_ISHA }), cr("4090", 360_000, { cohort: COHORT_ISHA })], kind: "derecognition", ias8_class: "change_in_estimate", status: "draft", preparer: "agent.engine", built_from: 1, ties_to: ["2140"] });
  s.journal.push(entry);
  emit(s, { kind: "journal", actor: "agent.engine", summary: memo, ref: id, chip: "DRAFTED", amount_cents: -360_000 }, EOWYN_ID, { payload: entry });
}

// ---------- confirm ----------
export function confirmProposal(req: Req, rawRef: string): Reply {
  const s = S();
  const rule = resolveRule(s, rawRef, "pending");
  const ref = rule ? refOf(rule) : rawRef;
  const p = s.proposals.get(ref);
  if (!rule || !p) {
    const done = s.confirmed.get(ref);
    if (rule && done) return ok({ rule: rulesView(s).find((r) => refOf(r) === ref), replay: done });
    return fail(404, "not_found", `No rule proposal ${rawRef} is waiting for confirmation.`);
  }
  if (req.role !== rule.authority_required) return fail(403, "forbidden", `Only the ${ROLE_NAME[rule.authority_required]} can confirm ${ref}: a rule's author must hold the authority it automates.`);
  if (!p.checks.no_hard_control) return fail(422, "validation", "This rule would offset a voucher without a signed acceptance, which a hard control forbids (Art. 7(3)). Nothing was saved.");
  const failed = Object.entries(p.checks).filter(([, v]) => !v).map(([k]) => k.replace(/_/g, " "));
  if (failed.length) return fail(422, "validation", `${ref} didn't pass: ${failed.join(", ")}. Nothing was saved.`);

  const q = ruleQuestion(s, rule);
  const before = snapshot(s);
  if (rule.supersedes) {
    const old = s.rules.find((r) => refOf(r) === rule.supersedes);
    if (old) {
      old.times_cited = citations(s, old);
      old.status = "retired";
    }
  }
  rule.status = "active";
  s.proposals.delete(ref);
  const replay = diffSnaps(before, snapshot(s), ref, s.knownAt, s.locked, flipExclusions(q));
  const at = nextAt(s);
  addCommit(s, "rule_event", req.session.principal, at, { ...rule, status: "active" }, `rule:${ref}`, `${ref} confirmed · active`);
  emit(s, { at, kind: "rule", actor: req.session.principal, summary: `${ROLE_NAME[req.role]}'s ruling saved as policy ${ref} · never asked again`, ref, chip: "RULED" }, q?.storm_id ?? EOWYN_ID);

  // Re-decide what changed and say so, storm by storm.
  for (const storm of s.storms) {
    for (const spec of storm.flights) if (replay.flips.some((f) => f.entity_id === spec.flight.id)) commitDecision(s, storm, spec, s.knownAt);
  }
  if (rule.id === "R-CL-1") settleVouchers(s, ref, before);
  if (rule.id === "R-LEG-1") {
    for (const storm of s.storms) {
      const flips = replay.flips.filter((f) => stormOfFlight(s, f.entity_id)?.id === storm.id);
      if (!flips.length) continue;
      const delta = flips.reduce((t, f) => t + (f.delta_cents ?? 0), 0);
      emit(s, { kind: "decision", actor: "agent.engine", summary: `${flips.length} knock-on returns settled · ${ref} cited ${flips.length}×`, ref, chip: "CITED", amount_cents: delta || null }, storm.id);
    }
    const jeId = postEstimateChange(s, replay, `Legal ruling ${ref}: NS113, NS115, NS117 settled · ${eur(Math.abs(replay.total_delta_cents))} change in estimate (IAS 8.36) · ${s.locked.length ? `${s.locked.join(", ")} locked, untouched` : "open period"} · drafted, pending approval`, "NS117@2025-01-24");
    if (jeId) {
      replay.adjustment_je_ids = [jeId];
      emit(s, { kind: "journal", actor: "agent.engine", summary: `${eur(Math.abs(replay.total_delta_cents))} change in estimate drafted, pending approval · Dr 2140 / Cr 4090${s.locked.length ? ` · ${s.locked.join(", ")} locked, untouched` : ""}`, ref: jeId, chip: "DRAFTED", amount_cents: replay.total_delta_cents }, EOWYN_ID);
    }
  }
  if (rule.id === "R-CTL-1") {
    if (rule.version === 1 && !s.questions.some((x) => x.pattern === "rule_widen")) {
      const nq = allCohortsQuestion(nextQuestionId(s), nextAt(s), EOWYN_ID, ref);
      s.questions.push(nq);
      emit(s, { kind: "question", actor: "agent.engine", summary: "Asked the Controller once: all storm cohorts?", ref: nq.id, chip: "ASKED" }, EOWYN_ID, { payload: nq });
    } else {
      emit(s, { kind: "rule", actor: "agent.engine", summary: `${ref}: every storm cohort keeps its expected tail from M12 until the six-year limitation`, ref, chip: "APPLIED" }, EOWYN_ID);
    }
  }
  s.confirmed.set(ref, replay);
  return ok({ rule: rulesView(s).find((r) => refOf(r) === ref), replay });
}

/** After R-CL-1: newly settled cases are cited per storm; a case it doesn't reach (non-EU departure) asks again, once. */
export function settleVouchers(s: MockState, ref: string, before: Snap | null) {
  const ctx = ctxOf(s);
  for (const storm of s.storms) {
    const cases = voucherCases(storm);
    if (!cases.length) continue;
    const open = cases.filter((c) => !voucherSettled(c, ctx));
    const settledHere = cases.filter((c) => voucherSettled(c, ctx) && !(before?.vouchers.get(c.coupon_id)?.settled ?? false));
    if (storm.kind === "eowyn" && settledHere.length) {
      emit(s, { kind: "entitlement", actor: "agent.engine", summary: `14C settled: no signed acceptance, no offset · ${ref} · €600 cash, the voucher stays as goodwill`, ref: "NS31@2025-01-24:14C", chip: "CITED", amount_cents: 60_000 }, storm.id);
    } else if (settledHere.length) {
      const cashOf = (cases: typeof settledHere) =>
        cases.reduce((t, c) => {
          const hit = specOf(s, c.flight_id);
          return t + (hit ? bandCents(hit.spec.flight.origin, hit.spec.flight.dest) : 0);
        }, 0);
      const eu = settledHere.filter((c) => c.departs_eu);
      if (eu.length) emit(s, { kind: "entitlement", actor: "agent.engine", summary: `${eu.length} unsigned in-lieu vouchers on EU departures settled · ruling cited ${ref}`, ref: storm.id, chip: "CITED", amount_cents: cashOf(eu) }, storm.id);
      for (const c of settledHere.filter((x) => !x.departs_eu)) {
        const hit = specOf(s, c.flight_id);
        const route = hit ? `${hit.spec.flight.origin}→${hit.spec.flight.dest}` : "non-EU";
        emit(s, { kind: "entitlement", actor: "agent.engine", summary: `${route} case settled · no signed acceptance, no offset · ruling cited ${ref}`, ref: c.coupon_id, chip: "CITED", amount_cents: cashOf([c]) }, storm.id);
      }
    }
    for (const c of open) {
      if (s.questions.some((q) => q.case_refs.includes(c.coupon_id))) continue;
      const hit = specOf(s, c.flight_id);
      const route = hit ? `${hit.spec.flight.origin}→${hit.spec.flight.dest}` : "non-EU";
      const nq = storm.id === HERMINIA_ID ? bosDubQuestion(nextQuestionId(s), nextAt(s), storm, ref) : nonEuVoucherQuestion(s, storm, c.coupon_id, route, ref);
      s.questions.push(nq);
      emit(s, { kind: "question", actor: "agent.engine", summary: `${route} case asked again (doesn't depart the EU)`, ref: nq.id, chip: "ASKED", amount_cents: nq.holds_cents ?? null }, storm.id, { payload: nq });
    }
  }
}

/** The cash compensation a settled case is now owed (its Art. 7 band, no offset). */
const bandCents = (origin: string, dest: string) => bandFor(origin, dest).band_eur * 100;

export function nonEuVoucherQuestion(s: MockState, storm: StormDef, couponId: string, route: string, ref: string): MockQuestion {
  const base = bosDubQuestion(nextQuestionId(s), nextAt(s), storm, ref);
  const seat = couponId.split(":").pop() ?? "";
  return {
    ...base,
    case_refs: [couponId],
    title: `${couponId.split("@")[0]} ${route} · ${seat}: the same unsigned voucher, but the flight doesn't leave the EU`,
    found: `The service desk gave passenger ${seat} a €300 voucher in lieu of compensation on ${route}. There is no signed acceptance. EU261 still applies: an EU carrier arriving in the EU (Art. 3(1)(b)).`,
    why_flagged: `${ref} covers every flight leaving the EU. This one doesn't leave the EU, so the ruling doesn't reach it: out of scope, asked once.`,
    holds: [couponId],
    evidence: [],
  };
}

// ---------- reject / widen / revert ----------
function guardRule(req: Req, rule: Rule | undefined, verb: string, rawRef: string): Reply | null {
  if (!rule) return fail(404, "not_found", `No rule ${rawRef}.`);
  if (rule.tier === "hard_control") return fail(403, "forbidden", `Hard controls are code: nobody can ${verb} ${refOf(rule)} here.`);
  if (rule.tier === "regulation") return fail(403, "forbidden", `Regulation cards change only when the law does: ${refOf(rule)} can't be ${verb === "widen" ? "widened" : `${verb}ed`}.`);
  if (req.role !== rule.authority_required) return fail(403, "forbidden", `Only the ${ROLE_NAME[rule.authority_required]} can ${verb} ${refOf(rule)}.`);
  return null;
}

export function rejectRule(req: Req, rawRef: string): Reply {
  const s = S();
  const rule = resolveRule(s, rawRef, "pending");
  const blocked = guardRule(req, rule, "reject", rawRef);
  if (blocked || !rule) return blocked ?? fail(404, "not_found", `No rule ${rawRef}.`);
  const explanation = str(bodyOf(req).explanation);
  if (!explanation) return fail(422, "validation", "Say why in a sentence: the rejection becomes the record.");
  const ref = refOf(rule);
  const q = ruleQuestion(s, rule);
  const at = nextAt(s);
  const ruling: Ruling = { id: nextRulingId(s), question_id: q?.id ?? null, author_role: req.role, author: req.session.name, kind: "rejection", decision: `Reject ${ref}`, explanation, at };
  s.rulings.push(ruling);
  if (s.proposals.has(ref)) {
    rule.status = "retired";
    s.proposals.delete(ref);
    if (q && q.pattern !== "rule_widen") q.status = "open";
    if (q?.pattern === "rule_widen") q.status = "answered";
    emit(s, { at, kind: "ruling", actor: req.session.principal, summary: `${ROLE_NAME[req.role]} rejected ${ref}: "${explanation}"`, ref: ruling.id, chip: "RULED" }, q?.storm_id ?? EOWYN_ID, { payload: ruling });
    return ok({ ruling, proposal: null });
  }
  if (rule.status !== "active") return fail(422, "validation", `${ref} is ${rule.status}; there's nothing to reject.`);
  emit(s, { at, kind: "ruling", actor: req.session.principal, summary: `${ROLE_NAME[req.role]} rejected ${ref}: "${explanation}"`, ref: ruling.id, chip: "RULED" }, q?.storm_id ?? EOWYN_ID, { payload: ruling });
  retire(s, rule, req);
  return ok({ ruling, proposal: null });
}

export function widenRule(req: Req, rawRef: string): Reply {
  const s = S();
  const rule = resolveRule(s, rawRef, "active");
  const blocked = guardRule(req, rule, "widen", rawRef);
  if (blocked || !rule) return blocked ?? fail(404, "not_found", `No rule ${rawRef}.`);
  if (rule.status !== "active") return fail(422, "validation", `Confirm ${refOf(rule)} before widening it.`);
  const pending = [...s.proposals.values()].find((p) => p.rule.supersedes === refOf(rule));
  if (pending) return ok(pending);
  const at = nextAt(s);
  const w = widenOnce(rule, at);
  if (!w) return fail(422, "validation", `Nothing left to widen: every scope key in ${refOf(rule)} is grounded in the ruling.`);
  const next = widenOnce(w.rule, at);
  const widened: Rule = { ...w.rule, version: nextVersion(s, rule.id) };
  const ref = refOf(widened);
  const would_flip = diffSnaps(snapshot(s), simulate(s, withActive(s, widened)), ref, s.knownAt, s.locked);
  const proposal: RuleProposal = { rule: widened, checks: { ...CHECKS_OK }, would_flip, widen_next: next ? { drop: next.dropped, scope_after: next.rule.scope } : null };
  s.rules.push(widened);
  s.proposals.set(ref, proposal);
  emit(s, { at, kind: "rule", actor: "agent.engine", summary: `Widen preview ${ref}: drops ${w.dropped} (copied from the case) · would change ${would_flip.flips.length} past decisions`, ref, chip: "INFO" }, EOWYN_ID, { payload: proposal });
  return ok(proposal);
}

export function revertRule(req: Req, rawRef: string): Reply {
  const s = S();
  const rule = resolveRule(s, rawRef, "active");
  const blocked = guardRule(req, rule, "revert", rawRef);
  if (blocked || !rule) return blocked ?? fail(404, "not_found", `No rule ${rawRef}.`);
  if (rule.status !== "active") return fail(422, "validation", `${refOf(rule)} isn't active; there's nothing to revert.`);
  return ok(retire(s, rule, req));
}

/** Retire an active rule, replay, book the € change in the first open period, and reopen what it had settled. */
function retire(s: MockState, rule: Rule, req: Req): ReplayDiff {
  const ref = refOf(rule);
  const before = snapshot(s);
  rule.times_cited = citations(s, rule);
  rule.status = "retired";
  if (rule.supersedes) {
    const prev = s.rules.find((r) => refOf(r) === rule.supersedes);
    if (prev) prev.status = "active";
  }
  const replay = diffSnaps(before, snapshot(s), ref, s.knownAt, s.locked);
  const at = nextAt(s);
  addCommit(s, "revert", req.session.principal, at, { ref, flips: replay.flips.length }, `rule:${ref}`, `${ref} reverted · replayed`);
  for (const storm of s.storms) for (const spec of storm.flights) if (replay.flips.some((f) => f.entity_id === spec.flight.id)) commitDecision(s, storm, spec, s.knownAt);
  const reopen = rule.id === "R-LEG-1" ? "Q-2" : rule.id === "R-CL-1" ? "Q-1" : rule.id === "R-CTL-1" ? "Q-3" : null;
  if (reopen && !rule.supersedes) {
    const q = s.questions.find((x) => x.id === reopen);
    if (q) {
      q.status = "open";
      q.remind_at = addMin(s.knownAt, 180);
    }
  }
  const jeId = postEstimateChange(s, replay, `Reverted ${ref} · replayed · ${eur(Math.abs(replay.total_delta_cents))} change in estimate (IAS 8.36)${s.locked.length ? ` · ${s.locked.join(", ")} locked, untouched` : ""} · drafted, pending approval`, null);
  if (jeId) replay.adjustment_je_ids = [jeId];
  const lockNote = s.locked.length ? ` · ${s.locked.join(", ")} locked, untouched` : "";
  emit(s, { kind: "replay", actor: req.session.principal, summary: `Reverted ${ref} · flips ${replay.flips.length} · Δ${eur(replay.total_delta_cents)}${lockNote}`, ref, chip: "INFO", amount_cents: replay.total_delta_cents || null }, EOWYN_ID, { payload: replay });
  return replay;
}

// ---------- books ----------
export function approveJournal(req: Req, id: string): Reply {
  const s = S();
  const entry = s.journal.find((e) => e.id === id);
  if (!entry) return fail(404, "not_found", `No journal entry ${id}.`);
  if (entry.status !== "draft") return fail(422, "validation", `${id} is already ${entry.status}.`);
  const principal = req.session.principal;
  const payout = entry.kind === "claim_approved" || entry.kind === "claim_paid";
  const action = payout ? "approve_payout" : "approve_journal";
  const deny = (code: string, message: string, reason: string) => {
    const at = nextAt(s);
    s.accessLog.push({ at, principal, action, resource: `journal:${id}`, allowed: false, reason });
    emit(s, { at, kind: "access_denied", actor: principal, summary: `${principal} ${action} → DENIED · ${code === "sod_violation" ? "SoD" : "authority"}`, ref: id, chip: "DENIED" }, EOWYN_ID, { payload: { principal, action, id, reason } });
    return fail(403, code, message);
  };
  if (entry.preparer === principal) return deny("sod_violation", "Preparer can't approve their own entry.", "SoD · preparer = approver");
  const allowed = payout ? ["claims_lead"] : ["controller", "cfo"];
  if (!allowed.includes(req.role)) return deny("forbidden", payout ? "Payouts need the Claims Lead's approval." : "Only the Controller (or the CFO) approves journal entries.", payout ? "payouts need the Claims Lead" : "journals need the Controller");
  entry.status = "approved";
  entry.approver = principal;
  const at = nextAt(s);
  s.accessLog.push({ at, principal, action, resource: `journal:${id}`, allowed: true, reason: `${ROLE_NAME[req.role]} ≠ preparer (${entry.preparer})` });
  const amount = entry.lines.reduce((t, l) => t + (l.dr_cents ?? 0), 0);
  emit(s, { at, kind: "journal", actor: principal, summary: `${ROLE_NAME[req.role]} approved ${id} · ${entry.memo.split(" · ")[0]} · parked, not posted`, ref: id, chip: "APPLIED", amount_cents: amount }, EOWYN_ID, { payload: entry });
  return ok(entry);
}

const PERIOD = /^\d{4}-(0[1-9]|1[0-2])$/;

export function monthEnd(req: Req, estimate: () => unknown, entitlementOf: (c: string) => number): Reply {
  const s = S();
  const period = str(bodyOf(req).period);
  if (!PERIOD.test(period)) return fail(422, "validation", "period must look like 2025-02.");
  if (req.role !== "controller") return fail(403, "forbidden", "Only the Controller runs the month end.");
  if (s.locked.includes(period)) return fail(422, "validation", `${period} is locked; nothing is written to a locked period.`);
  const ids = MONTH_END_IDS[period] ?? [];
  const entries = s.journal.filter((e) => ids.includes(e.id));
  s.monthEnd.add(period);
  const cie = entries.find((e) => e.kind === "change_in_estimate");
  if (cie) {
    const amount = cie.lines.reduce((t, l) => t + (l.cr_cents ?? 0), 0);
    emit(s, { kind: "journal", actor: req.session.principal, summary: `Month end ${period}: ${eur(amount)} change in estimate on the NS31 cohort (BF at M1, A/E 1.448) · drafted, pending approval`, ref: cie.id, chip: "DRAFTED", amount_cents: amount }, EOWYN_ID);
  } else {
    emit(s, { kind: "info", actor: req.session.principal, summary: `Month end ${period}: no new development · nothing to re-estimate`, ref: null, chip: "INFO" }, EOWYN_ID);
  }
  return ok({ entries, rollforward: rollforward(s.journal, period, entitlementOf), estimate: estimate() });
}

export function lockPeriod(req: Req): Reply {
  const s = S();
  const period = str(bodyOf(req).period);
  if (!PERIOD.test(period)) return fail(422, "validation", "period must look like 2025-02.");
  if (req.role !== "controller") return fail(403, "forbidden", "Only the Controller locks a period.");
  if (!s.locked.includes(period)) {
    s.locked.push(period);
    s.locked.sort();
    const at = nextAt(s);
    addCommit(s, "period_lock", req.session.principal, at, { period }, `period:${period}`, `${period} locked`);
    emit(s, { at, kind: "info", actor: req.session.principal, summary: `${ROLE_NAME[req.role]} locked ${period} · nothing is written to it again`, ref: period, chip: "LOCKED" }, EOWYN_ID, { commitKind: "period_lock" });
  }
  return ok({ locked: [...s.locked] });
}

export function setClock(req: Req): Reply {
  const s = S();
  const raw = str(bodyOf(req).known_at);
  const t = Date.parse(raw);
  if (!raw || Number.isNaN(t) || !/^\d{4}-\d{2}-\d{2}T/.test(raw)) return fail(422, "validation", "known_at must be a UTC time like 2025-01-25T12:00:00Z.");
  if (t < Date.parse(s.knownAt)) return fail(422, "validation", `The clock only moves forward: it's at ${s.knownAt}.`);
  const known_at = isoZ(t);
  if (known_at !== s.knownAt) {
    s.knownAt = known_at;
    s.tick = 0;
    emit(s, { kind: "info", actor: req.session.principal, summary: `Clock moved to ${known_at}`, ref: null, chip: "INFO" }, null, { commitKind: "clock" });
    for (const q of s.questions) {
      if (q.status !== "open" || !q.remind_at || Date.parse(q.remind_at) > t) continue;
      q.status = "reminded";
      const hours = Math.round((t - Date.parse(q.asked_at)) / 3_600_000);
      const others = publicQuestion(s, q, "judge").others_settled;
      emit(s, { kind: "reminder", actor: "agent.engine", summary: `Reminded the ${ROLE_NAME[q.routed_to]}: ${q.id} waiting ${hours}h · ${others.toLocaleString("en-US")} others settled`, ref: q.id, chip: "INFO" }, q.storm_id);
    }
  }
  return ok({ known_at: s.knownAt });
}

// ---------- challenge ----------
const LEGAL_PATTERN = /airbus|boeing|manufacturer|hidden (manufacturing )?defect|operator (information|notice)|\boit\b|service bulletin|design defect|manufacturing defect|batch/i;
const NEW_FACT = /\b\d{1,2}:\d{2}\s*z?\b|\bEI-[A-Z]{3}\b|tech ?log|\bmel\b|\baog\b|crew|part arrived|spare|ferry|\bmcc\b/i;

export function challenge(req: Req, flightId: string): Reply {
  const s = S();
  const hit = specOf(s, flightId);
  if (!hit) return fail(404, "not_found", `No flight ${flightId}.`);
  const text = str(bodyOf(req).text);
  if (!text) return fail(422, "validation", "Write the challenge first.");
  const { storm, spec } = hit;
  const f = spec.flight;
  const ctx = ctxOf(s);
  const d = decide(storm, spec, ctx);
  const classification: ChallengeResponse["classification"] = LEGAL_PATTERN.test(text) ? "new_legal_pattern" : NEW_FACT.test(text) ? "new_fact" : "assertion";
  const at = nextAt(s);
  const challengeEv: Evidence = { fact_id: `F:challenge:${f.id}:${at}`, source_id: `challenge:${f.id}`, field: "challenge.text", value: text, quote: text, role: "contradicts", trust_tier: 4, struck: false };
  const w = mainWindow(storm);
  const hub = hubOf(storm);
  let cited: Evidence[] = [];
  let reply: string;

  if (!d) {
    reply = `Decision stands. ${f.number} operated (off blocks ${f.actual_dep ? hhmmZ(f.actual_dep) : hhmmZ(f.sched_dep)}), so there's no cancellation to settle.`;
    cited = [scheduleEv(spec)];
  } else if (f.id === HERO_FLIGHT) {
    cited = [
      metarEv(storm, "2025-01-24T16:00:00Z", "metar.max_gust_kt_from_16z", 25),
      metarEv(storm, f.sched_dep, "flight.in_window_dep", "out"),
      { fact_id: "F:schedule:EIDW@2025-01-24:operated_15_30_17_30", source_id: `schedule:${storm.id}`, field: "schedule.operated_departures", value: 11, quote: "11 Northstar departures operated 15:30–17:30Z", role: "supports", trust_tier: 2, struck: false },
      ...d.evidence.filter((e) => e.field === "aog.logged_at" || e.field === "aog.mel_relief"),
    ];
    reply = `Decision stands. From 16:00Z the Dublin METAR shows gusts ≤25 kt (${nearestObs(storm.metar, "2025-01-24T16:00:00Z").raw.split(" ").slice(1, 3).join(" ")}; ${nearestObs(storm.metar, f.sched_dep).raw.split(" ").slice(1, 3).join(" ")} at NS31's STD), and 11 Northstar departures operated between 15:30 and 17:30Z. EI-NSB was AOG from 23 Jan 21:40Z with no MEL relief (tech log), before any storm window. A technical fault is not an extraordinary circumstance (EU261 Art. 5(3); CJEU C-549/07), so compensation is owed.`;
  } else if (d.cause === "weather") {
    const atArr = d.in_window_arr === "in" && d.in_window_dep !== "in";
    const t = atArr ? f.sched_arr : f.sched_dep;
    cited = d.evidence.filter((e) => e.trust_tier === 1);
    reply = `Decision stands. ${f.number}'s ${atArr ? "arrival" : "departure"} at ${hhmmZ(t)} was inside the ${hub} storm window (${windowLabel(w)}; ${nearestObs(storm.metar, t).raw.split(" ").slice(1, 3).join(" ")}). That's an extraordinary circumstance (EU261 Art. 5(3)): no compensation; refunds and care still due.`;
  } else if (isHeld(d)) {
    cited = d.evidence.filter((e) => e.trust_tier <= 2);
    reply = `Decision stands for now: ${f.number} is with Legal (${d.question_id ?? "Q-2"}), and the challenge is attached to it as a tier-4 fact. Challenge facts route; they never flip a decision.`;
  } else {
    cited = d.evidence.filter((e) => e.trust_tier === 1);
    reply = `Decision stands. ${d.reason}${d.rules_applied.length ? ` (${d.rules_applied.join(", ")})` : ""}. ${d.extraordinary === "extraordinary" ? "No compensation; refunds and care still due." : "Compensation is owed."}`;
  }

  let question: MockQuestion | null = null;
  if (classification === "new_legal_pattern" && d) {
    reply = `Decision stands until Legal rules. A manufacturer's notice of a hidden defect can take a technical fault outside normal operation (CJEU C-549/07 ¶26). That is a legal question, so it has gone to Legal: confidence 52% · no precedent. Challenge facts route; they never flip a decision.`;
    question = hiddenDefectQuestion(nextQuestionId(s), at, f.id, storm.id, text);
  } else if (classification === "new_fact" && d) {
    reply = `${reply} Your account is recorded as a tier-4 fact: it doesn't outrank the tech log or the METAR (tier 1), so Ops will check it against the MCC and OCC logs.`;
    question = opsQuestion(nextQuestionId(s), at, storm.id, f.id, `${f.number}: a challenge adds a fact to check`, `A challenge on ${f.number} says: "${text}"`, text, `challenge:${f.id}`);
  }
  if (question) s.questions.push(question);
  const ruling: Ruling = { id: nextRulingId(s), question_id: question?.id ?? null, author_role: "agent.engine", author: "agent.engine", kind: "challenge_response", decision: "Decision stands.", explanation: reply, at };
  s.rulings.push(ruling);
  emit(s, { at, kind: "decision", actor: "agent.engine", summary: `Challenge on ${f.number} answered · ${classification.replace(/_/g, " ")} · Decision stands.`, ref: f.id, chip: "INFO" }, storm.id, { payload: { text, classification }, inputs: ["prompt:drafter-v1"] });
  if (question) emit(s, { kind: "question", actor: "agent.engine", summary: classification === "new_legal_pattern" ? `Asked Legal about a hidden-defect notice on ${f.number} (C-549/07 ¶26)` : `Asked Ops to check a challenge fact on ${f.number}`, ref: question.id, chip: "ASKED" }, storm.id, { payload: question });
  const response: ChallengeResponse = {
    classification,
    decision_stands: true,
    reply: { id: `DRAFT-challenge:${f.id}:${s.ids.draft++}`, kind: "challenge_reply", text: reply, numbers_verified: true, llm_commit: null, template_fallback: false },
    cited: [...cited, challengeEv],
    question: question ? publicQuestion(s, question, req.role) : null,
  };
  return ok(response);
}

