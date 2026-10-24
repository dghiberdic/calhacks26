"""Independent ground-truth exports. This module deliberately never imports engine/."""
from __future__ import annotations

from collections import Counter
from pathlib import Path
from typing import Any

import orjson
from dateutil.relativedelta import relativedelta

from world.generator import GENERATOR_VERSION, Generated
from world.pax import coupon_truth

VERSION = "northstar-answer-key@1"


def build_answer_key(generated: Generated, split: str) -> dict[str, Any]:
    if split not in {"train", "test"}:
        raise ValueError("split must be train or test")
    world, truth = generated.world, generated.truth
    flights = {f.id: f for f in world.flights}
    selected = {fid: t for fid, t in truth.flights.items() if t.split == split}
    elections = {e.coupon_id: e for e in world.elections}
    vouchers = {e.coupon_id: e for e in sorted(world.crm, key=lambda e: (e.at, e.id))
                if e.kind == "voucher_in_lieu_of_compensation"}
    coupons: dict[str, dict[str, Any]] = {}
    for coupon in world.coupons:
        if coupon.flight_id not in selected:
            continue
        row = truth.coupons.get(coupon.id)
        if row is None:
            row = coupon_truth(flights[coupon.flight_id], selected[coupon.flight_id].__dict__, coupon,
                               elections.get(coupon.id), vouchers.get(coupon.id), world.meta.get("distances_km"))
        coupons[coupon.id] = dict(row)

    claims: dict[str, dict[str, Any]] = {}
    accepted: set[str] = set()
    for claim in sorted(world.claims, key=lambda c: (c.received_at, c.id)):
        if claim.coupon_id not in coupons:
            continue
        coupon = coupons[claim.coupon_id]
        flight = flights[coupon["flight_id"]]
        valid, reason = True, "valid"
        if coupon["status"] != "owed":
            valid, reason = False, coupon["status"]
        elif claim.received_at.date() > flight.date + relativedelta(years=6):
            valid, reason = False, "after_limitation"
        elif claim.channel == "agency" and claim.authority not in {"poa", "assignment"}:
            valid, reason = False, "authority_none"
        elif claim.coupon_id in accepted:
            valid, reason = False, "duplicate"
        elif coupon.get("pay_cents", 0) == 0:
            valid, reason = False, "settled_in_kind"
        if valid:
            accepted.add(claim.coupon_id)
        row = dict(truth.claims.get(claim.id, {}))
        row.update(coupon_id=claim.coupon_id, valid=valid, reason=reason,
                   pay_cents=coupon.get("pay_cents", 0) if valid else 0)
        claims[claim.id] = row

    planted: Counter[str] = Counter()
    for row in selected.values():
        planted.update(row.planted)
    for row in coupons.values():
        planted.update(row.get("planted", []))
    for row in claims.values():
        planted.update(row.get("planted", []))
    return {
        "version": VERSION,
        "generator": GENERATOR_VERSION,
        "seed": world.meta.get("seed", 0),
        "split": split,
        "period": "2023-07-01..2024-12-31" if split == "train" else "2025-01-01..2025-06-30",
        "ground_truth_source": "latent causes and explicit fixture policy; never engine decisions",
        "flights": {fid: row.to_json() for fid, row in sorted(selected.items())},
        "coupons": dict(sorted(coupons.items())),
        "claims": dict(sorted(claims.items())),
        "planted": dict(sorted(planted.items())),
        "coverage": {"flights": len(selected), "coupons": len(coupons), "claims": len(claims)},
    }


def write_answer_keys(generated: Generated, directory: str | Path) -> dict[str, Path]:
    directory = Path(directory)
    directory.mkdir(parents=True, exist_ok=True)
    paths = {}
    for split in ("train", "test"):
        path = directory / f"{split}.json"
        path.write_bytes(orjson.dumps(build_answer_key(generated, split), option=orjson.OPT_SORT_KEYS) + b"\n")
        paths[split] = path
    return paths
