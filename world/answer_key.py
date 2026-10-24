"""F3c · The answer key: ground truth per split, written by the generator from its latent causes (never the engine).

    uv run python -m world.answer_key            # writes data/answer_key/{train,test}.json + curves_train.json

Per flight: true cause, extraordinary status, latent cause, the OCC code typed, planted tags, expected route.
Per coupon (compact): each cancelled flight lists a default truth row and the coupons that differ from it.
Per claim: valid?, what to pay, which coupons it covers, why.
"""
from __future__ import annotations

import sys
from collections import Counter
from datetime import date
from pathlib import Path
from typing import Any

import orjson

from world import pax as P
from world.golden import canonical_hash

ROOT = Path(__file__).resolve().parent.parent
OUT_DIR = ROOT / "data" / "answer_key"
VERSION = "answer-key-v1"
LABEL = "ground truth from the generator's latent causes and Northstar's rulings; never from the engine"
SPLIT_RANGE = {"train": ("2023-07-01", "2024-12-31"), "test": ("2025-01-01", "2025-06-30")}
COUPON_FIELDS = ("status", "compensation_cents", "voucher_offset_cents", "reduction", "handling", "planted", "also")
COUPON_NOTE = ("coupons[flight].default applies to every seat not in exceptions. Refund due (Art. 8) = the coupon's "
               "election is 'refund'; care due (Art. 9) unless status is staff_ticket. pay = compensation - offset.")
FLIGHT_TYPES = ("miscoded_technical", "concurrent", "knock_on_return", "notice_ge_14d", "manifest_ops_pax_mismatch",
                "ambiguous")


def _row(t: dict[str, Any]) -> dict[str, Any]:
    return {k: t[k] for k in COUPON_FIELDS if t.get(k) not in (None, [], False)}


def _flight_split(gen: Any) -> dict[str, str]:
    out: dict[str, str] = {}
    for m in gen.world.meta["days"]:
        for fid in m["flights"]:
            out[fid] = m["split"]
    for m in gen.world.meta.get("legacy", []):
        for fid in m["flights"]:
            out[fid] = m["split"]
    return out


def build(gen: Any) -> dict[str, dict[str, Any]]:
    w, truth = gen.world, gen.truth
    fsplit = _flight_split(gen)
    flights = {f.id: f for f in w.flights}
    coupons_by_flight: dict[str, list] = {}
    for c in w.coupons:
        coupons_by_flight.setdefault(c.flight_id, []).append(c)
    world_hash = canonical_hash(w)
    keys: dict[str, dict[str, Any]] = {}
    for split in ("train", "test"):
        fids = [fid for fid, sp in fsplit.items() if sp == split]
        key: dict[str, Any] = {"version": VERSION, "split": split, "range": list(SPLIT_RANGE[split]),
                               "seed": w.meta.get("seed"), "generator": w.meta.get("generator"),
                               "world_hash": world_hash, "label": LABEL, "coupon_note": COUPON_NOTE,
                               "storms": {}, "flights": {}, "coupons": {},
                               "claims": {}, "planted": {}, "planted_cases": {}}
        cases: dict[str, set[str]] = {}
        for fid in sorted(fids):
            ft = truth.flights[fid]
            f = flights[fid]
            row = ft.to_json()
            row.pop("flight_id", None)
            row["ops_code"] = f.ops_cause_code
            row["recode_expected"] = bool(f.status == "cancelled" and f.ops_cause_code in ("71", "72")
                                          and ft.cause not in ("weather",))
            key["flights"][fid] = row
            for tag in ft.planted:
                cases.setdefault(tag, set()).add(fid)
            cs = coupons_by_flight.get(fid, [])
            if not cs:
                continue
            rows = {c.id.rsplit(":", 1)[1]: _row(truth.coupons[c.id]) for c in cs}
            default = Counter(orjson.dumps(r, option=orjson.OPT_SORT_KEYS) for r in rows.values()).most_common(1)[0][0]
            key["coupons"][fid] = {"band_eur": truth.coupons[cs[0].id]["band_eur"],
                                   "segment": truth.coupons[cs[0].id]["segment"], "n": len(cs),
                                   "default": orjson.loads(default),
                                   "exceptions": {seat: r for seat, r in sorted(rows.items())
                                                  if orjson.dumps(r, option=orjson.OPT_SORT_KEYS) != default}}
            for c in cs:
                for tag in truth.coupons[c.id].get("planted", []):
                    cases.setdefault(tag, set()).add(c.id)
        fset = set(fids)
        for cl in w.claims:
            if cl.coupon_id.rsplit(":", 1)[0] not in fset:
                continue
            t = truth.claims[cl.id]
            row = {"coupon_id": cl.coupon_id, "valid": t["valid"], "pay_cents": t["pay_cents"], "reason": t["reason"],
                   "dev_month": t["dev_month"]}
            if t["covers"] != [cl.coupon_id]:
                row["covers"] = t["covers"]
            if t["planted"]:
                row["planted"] = t["planted"]
            key["claims"][cl.id] = row
            for tag in t["planted"]:
                cases.setdefault(tag, set()).add(cl.coupon_id)
        for m in w.meta["days"]:
            if m["split"] != split:
                continue
            key["storms"][m["storm_id"]] = _storm_stats(m, flights, coupons_by_flight, truth, w)
        key["planted_cases"] = {k: sorted(v) for k, v in sorted(cases.items())}
        key["planted"] = {k: len(v) for k, v in sorted(cases.items())}
        keys[split] = key
    return keys


def _storm_stats(m: dict, flights: dict, coupons_by_flight: dict, truth: Any, w: Any) -> dict[str, Any]:
    fids = m["flights"]
    cancelled = [f for f in fids if flights[f].status == "cancelled"]
    cs = [c for f in cancelled for c in coupons_by_flight.get(f, [])]
    owed = [c for c in cs if truth.coupons[c.id]["status"] == "owed"]
    cids = {c.id for c in cs}
    event = date.fromisoformat(m["date"])
    paid: dict[int, int] = {1: 0, 3: 0, 6: 0, 12: 0, 18: 0}
    for cl in w.claims:
        if cl.coupon_id in cids and truth.claims[cl.id]["valid"]:
            for k in paid:
                if truth.claims[cl.id]["dev_month"] <= k:
                    paid[k] += truth.claims[cl.id]["pay_cents"]
    return {"date": m["date"], "kind": m["kind"], "golden": bool(m.get("golden")), "flights": len(fids),
            "cancelled": len(cancelled), "passengers_cancelled": sum(flights[f].pax for f in cancelled),
            "entitlement_cents": sum(truth.coupons[c.id]["compensation_cents"] for c in owed),
            "owed_pay_cents": sum(truth.coupons[c.id]["pay_cents"] for c in owed),
            "owed_coupons": len(owed), "m1_month_end": P.dev_month_end(event, 1).date().isoformat(),
            "claims_paid_cents_by_month": {f"M{k}": v for k, v in paid.items()},
            "extraordinary_flights": sum(1 for f in cancelled if truth.flights[f].extraordinary == "extraordinary")}


def generated_curves(gen: Any, split: str = "train") -> dict[str, Any]:
    """€-basis cumulative valid-claim curves learned from the generated history (replaces golden's curves.json)."""
    w, truth = gen.world, gen.truth
    fsplit = {fid: m["split"] for m in w.meta["days"] for fid in m["flights"]}   # legacy (time-barred) excluded
    claimed_at: dict[str, int] = {}
    for t in truth.claims.values():
        if t["valid"]:
            for cid in t["covers"]:
                claimed_at[cid] = min(claimed_at.get(cid, 99), t["dev_month"])
    curves = []
    for seg, pts in P.curve_points().items():
        owed = [c for c in w.coupons if fsplit.get(c.flight_id) == split and truth.coupons[c.id]["status"] == "owed"
                and truth.coupons[c.id]["segment"] == seg]
        out_pts, ns = [], []
        for m, _ in pts:
            cohort = [c for c in owed
                      if P.dev_month_end(date.fromisoformat(truth.flights[c.flight_id].day), m) <= P.CLAIMS_HORIZON]
            ent = sum(truth.coupons[c.id]["compensation_cents"] for c in cohort)
            got = sum(truth.coupons[c.id]["compensation_cents"] for c in cohort if claimed_at.get(c.id, 99) <= m)
            out_pts.append([m, round(got / ent, 4) if ent else None])
            ns.append(len(cohort))
        ultimate = {"long_haul_gt3500": 0.35, "medium_1500_3500": 0.27, "short_le1500": 0.20}[seg]
        last = out_pts[-1][1] or ultimate
        curves.append({"segment": seg, "basis": "eur", "points": out_pts, "n_by_point": ns,
                       "observed_through_month": 18, "ultimate": ultimate, "tail_factor": round(ultimate / last, 4),
                       "tail_note": "months 18–72 beyond history: documented judgment (Steer 2020 benchmark 18% "
                                    "for cancellations)", "target_points": [list(p) for p in pts]})
    return {"version": "gen-curves-v1", "basis": "eur", "split": split,
            "source": f"generated Northstar claims history ({w.meta.get('generator')}, seed {w.meta.get('seed')}), "
                      f"{SPLIT_RANGE[split][0]} → {SPLIT_RANGE[split][1]}, coupons counted where the curve point is "
                      "observed before the 2026-07-01 extract", "curves": curves}


def write(gen: Any, out_dir: Path = OUT_DIR) -> list[Path]:
    out_dir.mkdir(parents=True, exist_ok=True)
    paths = []
    for split, key in build(gen).items():
        p = out_dir / f"{split}.json"
        p.write_bytes(orjson.dumps(key, option=orjson.OPT_SORT_KEYS) + b"\n")
        paths.append(p)
    p = out_dir / "curves_train.json"
    p.write_bytes(orjson.dumps(generated_curves(gen), option=orjson.OPT_INDENT_2) + b"\n")
    paths.append(p)
    return paths


def main(argv: list[str]) -> int:
    from world.generator import generate_world

    seed = int(argv[0]) if argv else 0
    gen = generate_world(seed)
    for p in write(gen):
        print(f"wrote {p.relative_to(ROOT)} ({p.stat().st_size / 1e3:.0f} kB)")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
