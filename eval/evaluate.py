"""Held-out accounting evaluation. All labels originate in world.answer_key, never engine outputs."""
from __future__ import annotations

from datetime import UTC, date, datetime, timedelta
from fractions import Fraction

from contracts.models import World
from engine.engine import Engine, round_half_away
from eval.golden_flow import historical_reduction


def day_world(world: World, day: date) -> World:
    """Limit case indexes, retaining preceding sectors/logs and only history available by cut-off."""
    start = datetime.combine(day, datetime.min.time(), UTC) - timedelta(days=1)
    end = start + timedelta(days=4)
    known = datetime.combine(day + timedelta(days=1), datetime.min.time(), UTC) + timedelta(hours=9)
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


def collect(world: World, keys: dict, calibration: dict) -> list[dict]:
    rows = []
    for split in ("train", "test"):
        key = keys[split]
        days = sorted({f["day"] for f in key["flights"].values() if f["status"] == "cancelled"})
        for day_text in days:
            day = date.fromisoformat(day_text)
            sample = day_world(world, day)
            known_at = datetime.combine(day + timedelta(days=1), datetime.min.time(), UTC) + timedelta(hours=9)
            engine = Engine(sample, calibration=calibration)
            rules = [historical_reduction(datetime(2023, 7, 1, tzinfo=UTC))]
            run = engine.run_storm(sample, "EIDW", day, rules, known_at)
            for fr in run.flights:
                d, f = fr.decision, fr.flight
                truth = key["flights"].get(f.id)
                if d is None or truth is None or truth["day"] != day_text:
                    continue
                coupons = {c.id: key["coupons"][c.id] for c in sample.coupons
                           if c.flight_id == f.id and c.id in key["coupons"]}
                ents = engine.entitlements(d, sample, rules)
                held_coupons = {c for q in run.questions for c in q.case_refs if c in coupons}
                correct = (d.cause.value == truth.get("cause") and
                           d.extraordinary.value == truth.get("extraordinary"))
                miscoded = (truth.get("latent") == "internal_aog" and f.ops_cause_code in {"71", "72"})
                caught = miscoded and d.recoded and correct
                pay = sum(c.get("pay_cents", 0) for c in coupons.values())
                buckets = {}
                for c in coupons.values():
                    band = c["band_eur"]
                    buckets[band] = buckets.get(band, 0) + c.get("pay_cents", 0)
                ultimate = sum(round_half_away(cents * Fraction({250: 20, 400: 27, 600: 35}[band], 100))
                               for band, cents in buckets.items())
                claimed = sum(c["pay_cents"] for c in key["claims"].values()
                              if c["coupon_id"] in coupons and c["valid"])
                rows.append({"split": split, "day": day_text, "flight_id": f.id, "kind": "cause",
                    "features": d.confidence.features, "correct": correct, "passengers": len(coupons),
                    "auto_passengers": sum(e.coupon_id not in held_coupons and e.status not in {"held", "needs_ruling"}
                                           for e in ents) if d.outcome == "auto" else 0,
                    "miscoded": miscoded, "caught": caught, "truth_pay_cents": pay,
                    "false_hold": d.outcome == "escalated" and truth.get("expected_route") is None,
                    "preview_cents": sum(round_half_away(Fraction(sum(e.compensation_cents for e in ents
                        if e.band_eur == band and e.status in {"owed", "held", "needs_ruling"}) * rate, 100))
                        for band, rate in ((250, 20), (400, 27), (600, 35))),
                    "ultimate_cents": ultimate, "claimed_cents": claimed,
                    "predicted_cause": d.cause.value, "truth_cause": truth.get("cause"),
                    "predicted_extraordinary": d.extraordinary.value,
                    "truth_extraordinary": truth.get("extraordinary")})
    return rows


def summarize(rows: list[dict]) -> dict:
    test = [r for r in rows if r["split"] == "test"]
    n = sum(r["passengers"] for r in test)
    return {"n_passengers": n,
        "straight_through_pct": round(100 * sum(r["auto_passengers"] for r in test) / n, 6) if n else 0.0,
        "miscodes_caught": sum(r["caught"] for r in test),
        "miscodes_total": sum(r["miscoded"] for r in test),
        "miscodes_eur_cents": sum(r["truth_pay_cents"] for r in test if r["caught"]),
        "false_holds": sum(r["false_hold"] for r in test),
        "liability_vs_actual": {"preview_eur": sum(r["preview_cents"] for r in test) / 100,
            "ultimate_expected_eur": sum(r["ultimate_cents"] for r in test) / 100,
            "valid_claims_through_2026_06_30_eur": sum(r["claimed_cents"] for r in test) / 100,
            "flight_cause_and_extraordinary_accuracy": sum(r["correct"] for r in test) / len(test) if test else 0.0}}
