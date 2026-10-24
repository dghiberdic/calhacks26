// The 1% StormCheck asks about, one question per pattern, in the plan's wording (§1.4, §9).
// Q1 (Claims Lead), Q2 (Legal, one question for 3 flights), Q3 (Controller); questions raised later
// (the BOS→DUB voucher case, a challenge's legal pattern, an unparseable injection) use the builders.
import type { Evidence, Question } from "@/api/types";
import * as T from "./texts";
import { ev, metarEv, type StormDef } from "./world";
import { addMin } from "./util";

/** Question plus the additive `others_settled` field (contracts/requests/justin.md #4). */
export type MockQuestion = Question & { others_settled?: number; storm_id: string };

export const Q1_RECOMMENDED = "No signed acceptance, no offset: pay €600 cash; the voucher stays as goodwill.";
export const Q2_RECOMMENDED =
  "A return sector of a storm-cancelled rotation is extraordinary only if no aircraft and crew could operate it within 3 h of STD, and passengers were offered the earliest reroute on any carrier (C-74/19).";
export const Q3_RECOMMENDED = "Derecognise the remaining €3,600 now: no new claims in 3 months.";
export const Q3_REJECT = "Reject: never release the tail. At M12 keep (ultimate − M12 rate) × entitlement until the six-year limitation.";

export function baselineQuestions(eowyn: StormDef): MockQuestion[] {
  const q1Evidence: Evidence[] = [
    ev("crm:NS31@2025-01-24:14C", "voucher.in_lieu", true, "VOUCHER EUR 300.00 ISSUED IN LIEU OF COMPENSATION", "context", false, "coupon:NS31@2025-01-24:14C"),
    ev("crm:NS31@2025-01-24:14C", "voucher.signed", false, "SIGNATURE: NONE CAPTURED", "supports", false, "coupon:NS31@2025-01-24:14C"),
    ev("crm:NS31@2025-01-24:14C", "voucher.accepted", true, "STATUS ACCEPTED", "contradicts", false, "coupon:NS31@2025-01-24:14C"),
    ev("claim:CLM-2025-0131", "claim.voucher_disputed", true, T.CLAIM_14C_SPAN, "supports", false, "coupon:NS31@2025-01-24:14C"),
    ev("claim:CLM-2025-0131", "claim.passenger_name", T.PAX_14C_NAME, T.PAX_14C_NAME, "context", false, "coupon:NS31@2025-01-24:14C"),
  ];
  const q2Evidence: Evidence[] = [
    ev(`spares:${eowyn.id}`, "spare.available_within_h", 4.33, T.SPARES_KNOCK_ON.NS117, "supports", false, "flight:NS117@2025-01-24"),
    metarEv(eowyn, "2025-01-24T16:20:00Z", "flight.in_window_arr", "out"),
    metarEv(eowyn, "2025-01-24T15:55:00Z", "flight.in_window_arr", "out"),
    ev(`pss:${eowyn.id}`, "pax.reroute_earliest_offered", true, T.PSS_KNOCK_ON.NS117, "supports", false, "flight:NS117@2025-01-24"),
    ev(`occ_log:${eowyn.id}`, "rotation.prev_cancelled", true, "NS116/117", "supports", false, "flight:NS117@2025-01-24"),
    ev(`occ_log:${eowyn.id}`, "flight.ops_cause_code", "71", T.OCC_EOWYN_71, "context", false, "flight:NS117@2025-01-24"),
  ];
  return [
    {
      id: "Q-1",
      storm_id: eowyn.id,
      case_refs: ["NS31@2025-01-24:14C"],
      pattern: "voucher_in_lieu_unsigned",
      routed_to: "claims_lead",
      asked_at: "2025-01-25T06:00:00Z",
      title: "NS31 · 14C: does a service-desk voucher in lieu offset her €600?",
      found: `On 24 Jan the T2 service desk gave passenger 14C (${T.PAX_14C_NAME}) a €300 voucher "in lieu of compensation". CRM records it as accepted; her claim says she never agreed, and there is no signed acceptance (Art. 7(3)).`,
      why_flagged: "Sources disagree: CRM (tier 3) says accepted, her claim (tier 4) says she never agreed, and there is no signature hash. An offset needs signed acceptance, and no rule covers unsigned in-lieu vouchers yet.",
      recommends: "Pay the €600 in cash and keep the €300 service-desk voucher as goodwill: without a signed acceptance there is no offset.",
      recommended_option: Q1_RECOMMENDED,
      options: [Q1_RECOMMENDED, "Offset the €300 voucher and pay €300 cash.", "Ask the passenger to confirm in writing first; hold the €600."],
      evidence: q1Evidence,
      confidence: { score: 0.39, kind: "voucher", label: "voucher-offset confidence", features: { in_lieu: 1, signed: 0, sources_disagree: 1, precedent_count: 0 }, caps: ["capped:sources-disagree"], calibration_version: "cal-v1" },
      reason_tag: "sources-disagree",
      holds: ["NS31@2025-01-24:14C"],
      holds_cents: 60_000,
      status: "reminded",
      remind_at: "2025-01-25T09:00:00Z",
    },
    {
      id: "Q-2",
      storm_id: eowyn.id,
      case_refs: ["NS113@2025-01-24", "NS115@2025-01-24", "NS117@2025-01-24"],
      pattern: "knock_on_return",
      routed_to: "legal",
      asked_at: "2025-01-25T06:00:30Z",
      title: "3 knock-on returns: is a storm-cancelled rotation extraordinary for the return sector?",
      found:
        "NS113 LIS–DUB, NS115 FCO–DUB and NS117 MUC–DUB had no aircraft: their outbounds (NS112, NS114, NS116) were cancelled by the storm. Each return was calm at both ends (NS117: Munich calm at 14:05Z, Dublin 11 kt at 16:20Z). No spare tail could reach them within 3 h (earliest ferry to MUC: STD+4h20), and passengers were offered the earliest reroute (LH via FRA).",
      why_flagged:
        "No precedent: whether the previous rotation's storm makes the return extraordinary turns on a direct causal link and reasonable measures (CJEU C-74/19). That is a legal question, so it goes to Legal once, for all 3 flights.",
      recommends: "Rule that the return sector of a storm-cancelled rotation is extraordinary only if no aircraft and crew could operate it within 3 h of STD and passengers were offered the earliest reroute on any carrier.",
      recommended_option: Q2_RECOMMENDED,
      options: [Q2_RECOMMENDED, "Not extraordinary: compensate all 3 flights (530 passengers).", "Extraordinary for every return of a storm-cancelled rotation, with no conditions."],
      evidence: q2Evidence,
      confidence: {
        score: 0.47,
        kind: "cause",
        label: "cause-finding confidence",
        features: { in_window_dep: 0, in_window_arr: 0, window_margin_h: 1.33, aog_before_window: 0, aog_inside_window: 0, root_cause_internal: 0, sources_disagree: 1, precedent_count: 0, knock_on: 1 },
        caps: ["capped:no-precedent"],
        calibration_version: "cal-v1",
      },
      reason_tag: "no-precedent",
      holds: ["NS113@2025-01-24", "NS115@2025-01-24", "NS117@2025-01-24"],
      holds_cents: 4_749_600,
      status: "open",
      remind_at: "2025-01-25T09:00:30Z",
    },
    {
      id: "Q-3",
      storm_id: eowyn.id,
      case_refs: ["EIDW@2024-01-21"],
      pattern: "cohort_release",
      routed_to: "controller",
      asked_at: "2025-01-25T06:00:35Z",
      title: "Storm Isha cohort (EIDW@2024-01-21, long haul): derecognise the remaining €3,600 at M12?",
      found: "The Storm Isha long-haul cohort (21 Jan 2024) has a €60,000 full Art. 7 entitlement and 29% claimed by M12, leaving €3,600 of EU261 compensation liability. No new claims in the last 3 months.",
      why_flagged: "Derecognising liability is a change in estimate, so it needs the Controller. The claims have gone quiet, but the six-year limitation (Ireland, C-139/11) hasn't run.",
      recommends: "Derecognise the remaining €3,600: no new claims in 3 months.",
      recommended_option: Q3_RECOMMENDED,
      options: [Q3_RECOMMENDED, Q3_REJECT, "Keep the €3,600 and re-test next quarter."],
      evidence: [
        { fact_id: "F:cohort:EIDW@2024-01-21:cohort.months_since_last_claim", source_id: "books:register:EIDW@2024-01-21", field: "cohort.months_since_last_claim", value: 3, quote: "last valid claim 2024-10-17 · 3 months without a new claim", role: "supports", trust_tier: 2, struck: false },
        { fact_id: "F:cohort:EIDW@2024-01-21:cohort.claimed_pct", source_id: "books:register:EIDW@2024-01-21", field: "cohort.claimed_pct", value: 0.29, quote: "claimed 29% of €60,000 by M12", role: "context", trust_tier: 2, struck: false },
        { fact_id: "F:cohort:EIDW@2024-01-21:cohort.limitation_expired", source_id: "regulation:IE-statute-of-limitations", field: "cohort.limitation_expired", value: false, quote: "limitation (Ireland): 6 years, to 2030-01-21", role: "contradicts", trust_tier: 1, struck: false },
      ],
      confidence: { score: 0.72, kind: "release", label: "release confidence", features: { cohort_age_months: 12, months_since_last_claim: 3, limitation_expired: 0 }, caps: [], calibration_version: "cal-v1" },
      reason_tag: "release-proposal",
      holds: ["EIDW@2024-01-21"],
      holds_cents: 360_000,
      status: "open",
      remind_at: "2025-01-25T09:00:35Z",
    },
  ];
}

/** After R-CL-1: the BOS→DUB case doesn't depart the EU, so the rule doesn't cover it and it asks again. */
export function bosDubQuestion(id: string, at: string, herminia: StormDef, ruleRef: string): MockQuestion {
  return {
    id,
    storm_id: herminia.id,
    case_refs: ["NS30@2025-01-25:12A"],
    pattern: "voucher_in_lieu_unsigned",
    routed_to: "claims_lead",
    asked_at: at,
    title: "NS30 BOS→DUB · 12A: the same unsigned voucher, but the flight doesn't leave the EU",
    found: "The BOS service desk gave passenger 12A a €300 voucher in lieu of compensation on NS30 BOS→DUB (cancelled, technical). There is no signed acceptance. EU261 still applies: an EU carrier arriving in the EU (Art. 3(1)(b)).",
    why_flagged: `${ruleRef} covers every flight leaving the EU. This flight leaves Boston, so the ruling doesn't reach it: out of scope, asked once.`,
    recommends: "Apply the same answer: no signed acceptance, no offset; pay €600 cash and keep the voucher as goodwill.",
    recommended_option: "No signed acceptance, no offset here too: pay €600 cash; the voucher stays as goodwill.",
    options: ["No signed acceptance, no offset here too: pay €600 cash; the voucher stays as goodwill.", "Offset the €300 voucher for non-EU departures.", "Ask Legal whether the BOS desk's voucher terms differ."],
    evidence: [
      ev("crm:NS30@2025-01-25:desk", "voucher.signed", false, "SIGNATURE: NONE CAPTURED", "supports", false, "coupon:NS30@2025-01-25:12A"),
      ev("crm:NS30@2025-01-25:desk", "voucher.in_lieu", true, "VOUCHER EUR 300.00 ISSUED IN LIEU OF COMPENSATION", "context", false, "coupon:NS30@2025-01-25:12A"),
      ev("occ_log:NS30@2025-01-25", "flight.departs_eu", false, "NS30 BOS-DUB CNL RSN 41", "context", false, "flight:NS30@2025-01-25"),
    ],
    confidence: { score: 0.44, kind: "voucher", label: "voucher-offset confidence", features: { in_lieu: 1, signed: 0, sources_disagree: 1, precedent_count: 1 }, caps: ["capped:out-of-scope"], calibration_version: "cal-v1" },
    reason_tag: "out-of-scope",
    holds: ["NS30@2025-01-25:12A"],
    holds_cents: 60_000,
    status: "open",
    remind_at: addMin(at, 180),
  };
}

/** A challenge citing a manufacturer's hidden-defect notice: a new legal pattern (C-549/07 ¶26), routed to Legal. */
export function hiddenDefectQuestion(id: string, at: string, flightId: string, stormId: string, text: string): MockQuestion {
  return {
    id,
    storm_id: stormId,
    case_refs: [flightId],
    pattern: "new_legal_pattern",
    routed_to: "legal",
    asked_at: at,
    title: `${flightId.split("@")[0]}: does a manufacturer's hidden-defect notice make the EDP failure extraordinary?`,
    found: "A challenge cites an Airbus operator notice of a hidden manufacturing defect in this engine-driven pump batch. If the defect was hidden and the manufacturer flagged it, the technical fault could fall outside normal operation.",
    why_flagged: "New legal pattern: CJEU C-549/07 ¶26 leaves room for hidden manufacturing defects. Challenge facts are trust tier 4: they route, they never flip a decision. The decision stands until Legal rules.",
    recommends: "Ask maintenance for the notice and the pump's serial number; until then the technical decision stands.",
    recommended_option: "Decision stands until the notice and serial number are verified by maintenance.",
    options: ["Decision stands until the notice and serial number are verified by maintenance.", "Treat a verified manufacturer hidden-defect notice as extraordinary (C-549/07 ¶26).", "Not extraordinary even with a notice: the defect was found and logged before the storm."],
    evidence: [{ fact_id: `F:challenge:${flightId}:challenge.text`, source_id: `challenge:${flightId}`, field: "challenge.text", value: text, quote: text, role: "contradicts", trust_tier: 4, struck: false }],
    confidence: { score: 0.52, kind: "cause", label: "cause-finding confidence", features: { aog_before_window: 1, root_cause_internal: 1, sources_disagree: 1, precedent_count: 0 }, caps: ["capped:no-precedent"], calibration_version: "cal-v1" },
    reason_tag: "new-legal-pattern",
    holds: [],
    holds_cents: 0,
    status: "open",
    remind_at: addMin(at, 180),
  };
}

/** Something StormCheck couldn't place (an unparseable injection or a tier-4 "new fact"): Ops checks it, at low confidence. */
export function opsQuestion(id: string, at: string, stormId: string, caseRef: string, title: string, found: string, quote: string, sourceId: string): MockQuestion {
  return {
    id,
    storm_id: stormId,
    case_refs: [caseRef],
    pattern: "unresolved_subject",
    routed_to: "ops",
    asked_at: at,
    title,
    found,
    why_flagged: "StormCheck couldn't tie this to a flight, a tail or a coupon with tier-1 evidence. Data gaps go to Ops below 0.6 confidence; nothing was changed.",
    recommends: "Check it against the OCC and MCC logs; if it is new tier-1 evidence, add it as a log entry.",
    recommended_option: "Checked: no new tier-1 evidence; keep the decision.",
    options: ["Checked: no new tier-1 evidence; keep the decision.", "It's new evidence: logged in the MCC/OCC log for re-decision.", "Not ours: discard."],
    evidence: [{ fact_id: `F:${sourceId}:raw`, source_id: sourceId, field: "source.text", value: quote, quote, role: "context", trust_tier: 4, struck: false }],
    confidence: { score: 0.31, kind: "cause", label: "cause-finding confidence", features: { sources_disagree: 0, precedent_count: 0 }, caps: ["capped:unparsed"], calibration_version: "cal-v1" },
    reason_tag: "out-of-scope",
    holds: [],
    holds_cents: 0,
    status: "open",
    remind_at: addMin(at, 180),
  };
}

/** After R-CTL-1: the rejection generalising, asked once. */
export function allCohortsQuestion(id: string, at: string, stormId: string, ruleRef: string): MockQuestion {
  return {
    id,
    storm_id: stormId,
    case_refs: [ruleRef],
    pattern: "rule_widen",
    routed_to: "controller",
    asked_at: at,
    title: "All storm cohorts?",
    found: `${ruleRef} keeps the expected tail for the Storm Isha cohort until the six-year limitation. Your words ("Never release the tail") don't name Isha.`,
    why_flagged: "The cohort is copied from the case, not from your ruling, so StormCheck asks once before widening it.",
    recommends: "Widen it: keep the expected tail for every storm cohort from M12 until the six-year limitation.",
    recommended_option: "Yes: every storm cohort, from M12 until the six-year limitation.",
    options: ["Yes: every storm cohort, from M12 until the six-year limitation.", "No: only the Storm Isha cohort."],
    evidence: [],
    confidence: { score: null, kind: "release", label: "release confidence", features: {}, caps: [], calibration_version: "cal-v1" },
    reason_tag: "out-of-scope",
    holds: [],
    holds_cents: 0,
    status: "open",
    remind_at: addMin(at, 180),
  };
}
