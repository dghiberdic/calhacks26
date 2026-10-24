"""Held-out accounting evaluation. All labels originate in world.answer_key, never engine outputs.

Every cancelled flight lands in exactly one outcome class (eval/DECISIONS.md):

- ``auto_correct``: the engine settled it with no person, and the cause and extraordinary status match the key;
- ``auto_wrong``: settled with no person, but wrong. This is the dangerous class;
- ``escalated_correct``: held for the person the key names (``expected_route``). The correct workflow;
- ``held_other``: held although the key needs no person, or held for someone else. It costs straight-through,
  but it is not an error.

``ambiguous`` (feature-invisible by design) is reported as its own line on top of the classes.

The calibration label for every kind is "the engine settled this item alone and correctly" (an abstention, i.e.
``needs_legal`` or ``needs_ruling``, is 0). Routing uses the score as exactly that probability.
"""
from __future__ import annotations

from collections.abc import Callable, Mapping
from datetime import UTC, date, datetime, timedelta
from fractions import Fraction
from typing import Any

from contracts.models import Question, Role, Rule, Ruling, World
from engine import confidence as conf
from engine.engine import Engine, round_half_away
from engine.questions import voucher_features
from eval.golden_flow import SCRIPTED_RULINGS, historical_reduction

SPLITS = {"train": ("2023-07-01", "2024-12-31"), "test": ("2025-01-01", "2025-06-30")}
SETTLED = frozenset({"extraordinary", "not_extraordinary"})
INTERNAL_LATENT = frozenset({"internal_aog", "crew", "notice", "concurrent"})
EXTRAORDINARY_ROOTS = frozenset({"weather_dep", "weather_arr", "external_hit", "atc"})
RATE_PCT = {250: 20, 400: 27, 600: 35}
SEGMENT = {250: "short_le1500", 400: "medium_1500_3500", 600: "long_haul_gt3500"}
MONTHS = (1, 3, 6, 12, 18)
OUTCOME_CLASSES = ("auto_correct", "auto_wrong", "escalated_correct", "held_other")
RULED_AFTER = timedelta(hours=2)            # a scripted ruling lands two hours after the morning it is first asked


def known_at_for(day: date) -> datetime:
    return datetime.combine(day + timedelta(days=1), datetime.min.time(), UTC) + timedelta(hours=9)


def day_world(world: World, day: date) -> World:
    """Limit case indexes, retaining preceding sectors/logs and only history available by cut-off."""
    start = datetime.combine(day, datetime.min.time(), UTC) - timedelta(days=1)
    end = start + timedelta(days=4)
    known = known_at_for(day)
    fs = [f for f in world.flights if start <= f.sched_dep < end]
    ids = {f.id for f in fs}
    tails = {f.aircraft for f in fs}
    cs = [c for c in world.coupons if c.flight_id in ids]
    cids = {c.id for c in cs}
    return world.model_copy(update={
        "flights": fs, "coupons": cs,
        "elections": [e for e in world.elections if e.coupon_id in cids],
        "crm": [e for e in world.crm if e.coupon_id in cids],
        "claims": [c for c in world.claims if c.coupon_id in cids],
        "care": [c for c in world.care if c.flight_id in ids],
        "tech_log": [t for t in world.tech_log if t.aircraft in tails and t.logged_at < end],
        "ops_log": [o for o in world.ops_log if set(o.flight_ids) & ids and o.at < end],
        "metar": {k: [o for o in rows if start <= o.valid < end] for k, rows in world.metar.items()},
        "history_cases": [h for h in world.history_cases if h.at <= known],
    })


# ---------------------------------------------------------------- labels (pure; unit-tested)

def cause_matches(predicted: str, truth: Mapping[str, Any]) -> bool:
    """The engine's cause equals the key's. A knock-on of an internal root and that root's own cause name the same
    obligation (C-74/19: the previous rotation's cause carries), so either label matches the other."""
    t = truth.get("cause")
    if predicted == t:
        return True
    pair = {predicted, t}
    if "knock_on" not in pair or not pair <= {"knock_on", "technical", "crew"}:
        return False
    if t == "knock_on":
        return truth.get("root_latent") in INTERNAL_LATENT
    return truth.get("latent") in INTERNAL_LATENT


def settled_right(predicted_cause: str, predicted_extraordinary: str, truth: Mapping[str, Any]) -> bool:
    """Calibration label: the engine settled it (no ``needs_legal``) and the answer matches the key."""
    return (predicted_extraordinary in SETTLED and predicted_extraordinary == truth.get("extraordinary")
            and cause_matches(predicted_cause, truth))


def outcome_class(outcome: str, routed_to: str | None, right: bool, expected_route: str | None) -> str:
    if outcome == "auto":
        return "auto_correct" if right else "auto_wrong"
    if expected_route and routed_to == expected_route:
        return "escalated_correct"
    return "held_other"


def miss_class(row: Mapping[str, Any]) -> str:
    """Why a non-``auto_correct`` flight is not auto-correct (reporting only)."""
    oc = row["outcome_class"]
    if oc == "auto_correct":
        return "auto_correct"
    if row.get("ambiguous"):
        return "ambiguous_by_design"
    if oc == "escalated_correct":
        return "escalated_correct"
    if oc == "auto_wrong":
        return "auto_wrong"
    pattern = row.get("pattern") or ""
    if row.get("outcome") == "human":
        return "held_batch_review"
    if row.get("truth_cause") == "weather" and row.get("predicted_cause") in ("unknown", "knock_on"):
        return "held_window_edge"                   # deliberate: weather code just outside the strict window
    if pattern == "external_event" or (row.get("truth_cause") == "technical"
                                       and row.get("truth_extraordinary") == "extraordinary"):
        return "held_external_event_no_precedent"   # deliberate: only Legal settles a new legal pattern
    if row.get("latent") == "notice":
        return "held_notice_ge_14d"
    if pattern == "concurrent_causes" or row.get("predicted_cause") == "concurrent":
        return "held_concurrent_not_in_key"
    return "held_other"


# ---------------------------------------------------------------- scripted rulings (held-out replay only)

class Scope:
    """Ground-truth scope of each scripted ruling: the cases the ruler's words cover, from the key and the World
    (never from the engine)."""

    def __init__(self, world: World, truth_flights: Mapping[str, Mapping[str, Any]]):
        self.truth = truth_flights
        self.flights = {f.id: f for f in world.flights}
        self.eu = {a.iata: a.eu for a in world.airports}
        self.in_lieu = {e.coupon_id: e for e in world.crm if e.kind == "voucher_in_lieu_of_compensation"}

    def covers(self, pattern: str, ref: str) -> bool:
        if pattern == "voucher_in_lieu_unsigned":
            v = self.in_lieu.get(ref)
            f = self.flights.get(ref.rsplit(":", 1)[0])
            return v is not None and not v.signed_acceptance_sha256 and bool(f and self.eu.get(f.origin))
        if pattern == "knock_on_return":
            t = self.truth.get(ref, {})
            return (t.get("cause") == "knock_on" and t.get("root_latent") in EXTRAORDINARY_ROOTS
                    and t.get("spare_within_3h") is False and t.get("reroute_earliest_offered") is True)
        if pattern == "cohort_release":
            return ref == "EIDW@2024-01-21"
        return False


def scripted_rule(question: Question, world: World, at: datetime) -> Rule | None:
    """The plan §1.4 ruling on the first question of a pattern, drafted by the engine's own deterministic drafter
    (``engine.lifecycle.template_rule``), confirmed and active from ``at``."""
    from engine.lifecycle import template_rule
    from engine.rules import TIER_OF_ROLE

    spec = SCRIPTED_RULINGS.get(question.pattern)
    if spec is None:
        return None
    role, rule_id, text, kind = spec
    ref = question.case_refs[0] if question.case_refs else ""
    case: dict[str, Any] = {}
    if question.pattern == "voucher_in_lieu_unsigned":
        f = next((x for x in world.flights if x.id == ref.rsplit(":", 1)[0]), None)
        eu = {a.iata: a.eu for a in world.airports}
        case["flight.departs_eu"] = bool(f and eu.get(f.origin))
    elif question.pattern == "knock_on_return":
        case["rotation.prev_cause"] = "weather"
    elif question.pattern == "cohort_release":
        case["cohort"] = ref
    ruling = Ruling(id=f"RUL-EVAL-{rule_id}", question_id=question.id, author_role=role, author=f"{role.value}:eval",
                    kind=kind, decision=question.recommended_option if kind == "answer" else "reject",
                    explanation=text, at=at)
    rule = template_rule(ruling, question, case)
    if rule is None:
        return None
    return rule.model_copy(update={"id": rule_id, "status": "active", "recorded_at": at,
                                   "tier": TIER_OF_ROLE.get(role, rule.tier), "authority_required": role})


# ---------------------------------------------------------------- the run

def _claims_by_month(key: Mapping[str, Any], coupon_ids: set[str]) -> dict[str, int]:
    out = {str(k): 0 for k in MONTHS}
    for c in key["claims"].values():
        if c["coupon_id"] in coupon_ids and c["valid"]:
            for k in MONTHS:
                if c.get("dev_month", 99) <= k:
                    out[str(k)] += c["pay_cents"]
    return out


def claim_validity_rows(world: World, keys: Mapping[str, Any]) -> list[dict[str, Any]]:
    """One row per keyed claim: CONTRACTS x-encoding computed from the World, label = the key's ``valid``."""
    flights = {f.id: f for f in world.flights}
    claims = {c.id: c for c in world.claims}
    per_coupon: dict[str, int] = {}
    for c in world.claims:
        per_coupon[c.coupon_id] = per_coupon.get(c.coupon_id, 0) + 1
    refunds = {e.coupon_id for e in world.crm if e.kind in ("refund_initiated", "bsp_refund", "chargeback")}
    rows = []
    for split in ("train", "test"):
        for cid, t in sorted(keys[split]["claims"].items()):
            c = claims.get(cid)
            f = flights.get(t["coupon_id"].rsplit(":", 1)[0])
            if c is None or f is None:
                continue
            months = (c.received_at.year - f.sched_dep.year) * 12 + (c.received_at.month - f.sched_dep.month)
            try:
                limit = f.date.replace(year=f.date.year + 6)
            except ValueError:
                limit = f.date.replace(year=f.date.year + 6, day=28)
            feats = {"channel_agency": 1.0 if c.channel == "agency" else 0.0,
                     "authority_none": 1.0 if c.channel == "agency" and c.authority in (None, "none") else 0.0,
                     "duplicate": 1.0 if per_coupon.get(c.coupon_id, 0) > 1 or c.coupon_id in refunds else 0.0,
                     "after_limitation": 1.0 if c.received_at.date() > limit else 0.0,
                     "regime_uk261": 1.0 if c.currency_regime == "UK261" else 0.0,
                     "age_months": float(max(0, months)), "precedent_count": 0.0}
            rows.append({"split": split, "kind": "claim_validity", "claim_id": cid, "flight_id": f.id,
                         "features": feats, "correct": bool(t["valid"])})
    return rows


def collect(world: World, keys: dict, calibration: dict, *, splits=("train", "test"), ledger: dict | None = None,
            progress: Callable[[str], None] | None = None) -> list[dict]:
    """Run the real engine on every keyed day. Train days see no rulings. Held-out days run in date order, and the
    plan §1.4 rulings apply from the morning their pattern is first asked (repeat questions, scope)."""
    rows: list[dict] = []
    ledger = ledger if ledger is not None else {}
    questions_log: list[dict] = ledger.setdefault("questions", [])
    rulings_log: list[dict] = ledger.setdefault("rulings", [])
    repeats: list[dict] = ledger.setdefault("repeats", [])
    out_of_scope: list[dict] = ledger.setdefault("out_of_scope", [])
    in_scope: dict[str, int] = ledger.setdefault("in_scope_settled", {})
    base = [historical_reduction(datetime(2023, 7, 1, tzinfo=UTC))]
    for split in splits:
        key = keys[split]
        lower, upper = SPLITS[split]
        scope = Scope(world, key["flights"])
        ruled: dict[str, Rule] = {}
        # Legacy fixtures test late claims; their 2017/18 operations are outside this cause-evaluation split.
        days = sorted({f["day"] for f in key["flights"].values() if lower <= f["day"] <= upper})
        for day_text in days:
            day = date.fromisoformat(day_text)
            sample = day_world(world, day)
            known_at = known_at_for(day)
            engine = Engine(sample, calibration=calibration)
            rules = base + [r for r in ruled.values() if r.recorded_at <= known_at]
            refs = {f"{r.id}@{r.version}": p for p, r in ruled.items()}
            run = engine.run_storm(sample, "EIDW", day, rules, known_at)
            held_coupons = {c for q in run.questions for c in q.case_refs}
            elections = {e.coupon_id: e for e in sample.elections}
            signed_vouchers = {e.coupon_id for e in sample.crm if e.kind == "voucher_issued"
                               and e.signed_acceptance_sha256}
            for fr in run.flights:
                d, f = fr.decision, fr.flight
                truth = key["flights"].get(f.id)
                if d is None or truth is None or truth["day"] != day_text:
                    continue
                coupons = {c.id: key["coupons"][c.id] for c in sample.coupons
                           if c.flight_id == f.id and c.id in key["coupons"]}
                ents = engine.entitlements(d, sample, rules)
                exact = d.cause.value == truth.get("cause") and d.extraordinary.value == truth.get("extraordinary")
                right = settled_right(d.cause.value, d.extraordinary.value, truth)
                routed = d.routed_to.value if d.routed_to else None
                oc = outcome_class(d.outcome, routed, right, truth.get("expected_route"))
                miscoded = truth.get("latent") == "internal_aog" and f.ops_cause_code in {"71", "72"}
                pay = sum(c.get("pay_cents", 0) for c in coupons.values())
                buckets: dict[int, int] = {}
                for c in coupons.values():
                    buckets[c["band_eur"]] = buckets.get(c["band_eur"], 0) + c.get("pay_cents", 0)
                ultimate = sum(round_half_away(cents * Fraction(RATE_PCT[band], 100))
                               for band, cents in buckets.items())
                accrual: dict[str, int] = {}
                for e in ents:
                    if e.status in {"owed", "held", "needs_ruling"}:
                        seg = SEGMENT[e.band_eur]
                        accrual[seg] = accrual.get(seg, 0) + e.compensation_cents - e.voucher_offset_cents
                by_month = _claims_by_month(key, set(coupons))
                pattern = next((q.pattern for q in run.questions if f.id in q.case_refs), None)
                # Refund due (Art. 8) per the key = the coupon's election is "refund". The engine also drafts a
                # refund when a voucher election has no signed acceptance and was not self-service on the web
                # (deliberate legal conservatism, Art. 8(1)(a) via 7(3)): its own category, never an error.
                unsigned_voucher_refund = [e for e in ents if e.coupon_id in coupons and e.refund_due_cents > 0
                                           and (el := elections.get(e.coupon_id)) is not None and el.kind == "voucher"
                                           and el.recorded_by != "web" and e.coupon_id not in signed_vouchers]
                refund_other = sum(1 for e in ents if e.coupon_id in coupons
                                   and (e.refund_due_cents > 0) != (getattr(elections.get(e.coupon_id), "kind", None)
                                                                     == "refund")) - len(unsigned_voucher_refund)
                row = {"split": split, "day": day_text, "flight_id": f.id, "kind": "cause",
                       "golden": bool(truth.get("golden", False)), "ambiguous": bool(truth.get("ambiguous", False)),
                       "latent": truth.get("latent"), "planted": list(truth.get("planted") or []),
                       "features": d.confidence.features, "score": d.confidence.score,
                       "correct": right, "exact": exact,
                       "outcome": d.outcome, "routed_to": routed, "expected_route": truth.get("expected_route"),
                       "outcome_class": oc, "pattern": pattern,
                       "rules_applied": list(d.rules_applied), "passengers": len(coupons),
                       "auto_passengers": sum(e.coupon_id not in held_coupons
                                              and e.status not in {"held", "needs_ruling"}
                                              for e in ents) if d.outcome == "auto" else 0,
                       "miscoded": miscoded, "caught": miscoded and d.extraordinary.value != "extraordinary",
                       "caught_auto": miscoded and oc == "auto_correct", "truth_pay_cents": pay,
                       "false_hold": oc == "held_other",
                       "preview_cents": sum(round_half_away(Fraction(sum(e.compensation_cents for e in ents
                           if e.band_eur == band and e.status in {"owed", "held", "needs_ruling"}) * rate, 100))
                           for band, rate in ((250, 20), (400, 27), (600, 35))),
                       "ultimate_cents": ultimate,
                       "claimed_cents": sum(c["pay_cents"] for c in key["claims"].values()
                                            if c["coupon_id"] in coupons and c["valid"]),
                       "claims_by_month": by_month, "accrual_by_segment": accrual,
                       "refund_unsigned_voucher_coupons": len(unsigned_voucher_refund),
                       "refund_unsigned_voucher_cents": sum(e.refund_due_cents for e in unsigned_voucher_refund),
                       "refund_disagree_other": refund_other,
                       "predicted_cause": d.cause.value, "truth_cause": truth.get("cause"),
                       "predicted_extraordinary": d.extraordinary.value,
                       "truth_extraordinary": truth.get("extraordinary")}
                row["miss_class"] = miss_class(row)
                rows.append(row)
                for ref in d.rules_applied:
                    if ref in refs:
                        if scope.covers(refs[ref], f.id):
                            in_scope[ref] = in_scope.get(ref, 0) + 1
                        else:
                            out_of_scope.append({"case": f.id, "rule": ref, "day": day_text})
                for e in ents:
                    for ref in e.rules_applied:
                        if ref in refs and refs[ref] == "voucher_in_lieu_unsigned":
                            if scope.covers(refs[ref], e.coupon_id):
                                in_scope[ref] = in_scope.get(ref, 0) + 1
                            else:
                                out_of_scope.append({"case": e.coupon_id, "rule": ref, "day": day_text})
                    if e.coupon_id not in coupons or e.status not in {"owed", "needs_ruling"}:
                        continue
                    if not any(v.coupon_id == e.coupon_id and v.kind == "voucher_in_lieu_of_compensation"
                               for v in sample.crm):
                        continue
                    feats, _ = voucher_features(sample, e.coupon_id, known_at)
                    t = coupons[e.coupon_id]
                    rows.append({"split": split, "day": day_text, "flight_id": f.id, "coupon_id": e.coupon_id,
                                 "kind": "voucher", "features": feats,
                                 "score": conf.score("voucher", feats, calibration).score,
                                 "correct": (e.status == "owed" and t.get("status") == "owed"
                                             and e.voucher_offset_cents == t.get("voucher_offset_cents", 0)),
                                 "status": e.status, "rules_applied": list(e.rules_applied)})
            for q in run.questions:
                questions_log.append({"split": split, "day": day_text, "id": q.id, "pattern": q.pattern,
                                      "routed_to": q.routed_to.value, "n_cases": len(q.case_refs),
                                      "score": q.confidence.score, "kind": q.confidence.kind})
                if split != "test":
                    continue
                if q.pattern in ruled:
                    inside = [r for r in q.case_refs if scope.covers(q.pattern, r)]
                    if inside:
                        repeats.append({"question": q.id, "day": day_text, "pattern": q.pattern,
                                        "in_scope": len(inside)})
                    continue
                rule = scripted_rule(q, sample, known_at + RULED_AFTER)
                if rule is not None:
                    ruled[q.pattern] = rule
                    rulings_log.append({"pattern": q.pattern, "rule": f"{rule.id}@{rule.version}", "day": day_text,
                                        "first_question": q.id, "at": rule.recorded_at.isoformat()})
            if progress:
                progress(f"{split} {day_text}: {run.counters.get('cancelled', 0)} cancelled, "
                         f"{len(run.questions)} questions")
    ledger["controls"] = {"repeat_questions": len(repeats), "out_of_scope_auto": len(out_of_scope),
                          "in_scope_settled": sum(in_scope.values()), "rulings": len(rulings_log)}
    return rows


# ---------------------------------------------------------------- metrics

def _cause(rows: list[dict]) -> list[dict]:
    return [r for r in rows if r.get("kind", "cause") == "cause"]


def classes(rows: list[dict]) -> dict[str, int]:
    out = {c: 0 for c in OUTCOME_CLASSES}
    for r in rows:
        if "outcome_class" in r:
            out[r["outcome_class"]] += 1
    return out


def liability_vs_actual(rows: list[dict], curves: Mapping[str, Mapping[int, float]] | None) -> dict[str, float]:
    """Engine day-1 accrual × the train-learned curve at Mk, against valid claims received by Mk (generated cohorts;
    golden's curated claims extract is excluded)."""
    if not curves:
        return {}
    gen = [r for r in rows if not r.get("golden") and "accrual_by_segment" in r]
    out: dict[str, float] = {}
    for k in (1, 3, 6):
        expected = sum(cents * curves.get(seg, {}).get(k, 0.0) for r in gen
                       for seg, cents in r["accrual_by_segment"].items())
        actual = sum(r["claims_by_month"][str(k)] for r in gen)
        out[f"m{k}_expected_eur"] = round(expected / 100, 2)
        out[f"m{k}_actual_eur"] = round(actual / 100, 2)
        out[f"m{k}_actual_over_expected"] = round(actual / expected, 4) if expected else 0.0
    return out


def summarize(rows: list[dict], curves: Mapping[str, Mapping[int, float]] | None = None) -> dict:
    test = [r for r in _cause(rows) if r["split"] == "test"]
    natural = [r for r in test if not r.get("golden", False)]
    n = sum(r["passengers"] for r in test)
    lva = {"preview_eur": sum(r["preview_cents"] for r in test) / 100,
           "ultimate_expected_eur": sum(r["ultimate_cents"] for r in test) / 100,
           "valid_claims_through_2026_06_30_eur": sum(r["claimed_cents"] for r in test) / 100,
           "flight_cause_and_extraordinary_accuracy": (sum(r.get("exact", r["correct"]) for r in test) / len(test)
                                                       if test else 0.0),
           "non_golden_cancellations": len(natural), "curated_golden_cancellations": len(test) - len(natural),
           "non_golden_cause_accuracy": (sum(r.get("exact", r["correct"]) for r in natural) / len(natural)
                                         if natural else 0.0)}
    if test and "outcome_class" in test[0]:
        for name, subset in (("", test), ("generated_", natural)):
            c = classes(subset)
            auto = c["auto_correct"] + c["auto_wrong"]
            for k, v in c.items():
                lva[f"{name}{k}"] = float(v)
            lva[f"{name}auto_precision"] = round(c["auto_correct"] / auto, 6) if auto else 0.0
            lva[f"{name}right_or_correctly_escalated"] = round(
                (c["auto_correct"] + c["escalated_correct"]) / len(subset), 6) if subset else 0.0
            lva[f"{name}auto_flights_pct"] = round(100 * auto / len(subset), 6) if subset else 0.0
        lva["ambiguous_by_design"] = float(sum(r.get("ambiguous", False) for r in test))
        lva["ambiguous_auto_wrong"] = float(sum(r.get("ambiguous", False) and r["outcome_class"] == "auto_wrong"
                                                for r in test))
        lva["miscodes_caught_auto"] = float(sum(r.get("caught_auto", False) for r in test))
        lva["refund_drafted_unsigned_non_web_voucher_coupons"] = float(
            sum(r.get("refund_unsigned_voucher_coupons", 0) for r in test))
        lva["refund_drafted_unsigned_non_web_voucher_eur"] = sum(
            r.get("refund_unsigned_voucher_cents", 0) for r in test) / 100
        lva["refund_disagree_other_coupons"] = float(sum(r.get("refund_disagree_other", 0) for r in test))
    lva.update(liability_vs_actual(test, curves))
    return {"n_passengers": n,
        "straight_through_pct": round(100 * sum(r["auto_passengers"] for r in test) / n, 6) if n else 0.0,
        "miscodes_caught": sum(r["caught"] for r in test),
        "miscodes_total": sum(r["miscoded"] for r in test),
        "miscodes_eur_cents": sum(r["truth_pay_cents"] for r in test if r["caught"]),
        "false_holds": sum(r["false_hold"] for r in test),
        "liability_vs_actual": lva}


def miss_table(rows: list[dict], split: str = "test") -> dict[str, dict[str, Any]]:
    """Counts and up to three example flights per ``miss_class`` (NUMBERS.md and requests to the engine owner)."""
    out: dict[str, dict[str, Any]] = {}
    for r in _cause(rows):
        if r["split"] != split:
            continue
        m = out.setdefault(r["miss_class"], {"n": 0, "generated": 0, "examples": []})
        m["n"] += 1
        m["generated"] += not r.get("golden", False)
        if len(m["examples"]) < 3:
            m["examples"].append(r["flight_id"])
    return dict(sorted(out.items()))


def load_curves(path) -> dict[str, dict[int, float]]:
    """``data/answer_key/curves_train.json`` → {segment: {month: rate}} (train split only)."""
    import orjson

    doc = orjson.loads(path.read_bytes())
    out: dict[str, dict[int, float]] = {}
    for c in doc.get("curves", []):
        pts = {int(m): float(v) for m, v in c.get("points", []) if v is not None}
        out[c["segment"]] = pts
    return out


SMALL_WORLD_DAYS = ("2023-12-21", "2025-02-26")     # one train storm, one held-out storm (not golden)


def small_world_digest(days=SMALL_WORLD_DAYS, seed: int = 0) -> str:
    """sha256 of every scored row on a two-day world: the reproducibility probe run in separate interpreters."""
    from hashlib import sha256

    import orjson

    from engine.confidence import default_calibration
    from eval.truth import expanded_keys
    from world.days import world_days
    from world.generator import generate_world

    wanted = {date.fromisoformat(d) for d in days}
    gen = generate_world(seed, [w for w in world_days() if w.day in wanted])
    ledger: dict = {}
    rows = collect(gen.world, expanded_keys(gen), default_calibration(), ledger=ledger)
    return sha256(orjson.dumps({"rows": rows, "ledger": ledger}, option=orjson.OPT_SORT_KEYS)).hexdigest()


__all__ = ["Role", "collect", "summarize", "day_world", "cause_matches", "settled_right", "outcome_class",
           "claim_validity_rows", "miss_table", "liability_vs_actual", "load_curves", "classes", "small_world_digest"]

if __name__ == "__main__":
    import sys

    if sys.argv[1:] == ["--small-world-digest"]:
        print(small_world_digest())
