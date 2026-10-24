from datetime import UTC, datetime

import orjson

from contracts.models import Claim
from world.generator import generate_world


def test_answer_key_covers_golden_coupons_without_changing_the_world():
    from world.answer_key import build_answer_key
    from world.golden import canonical_hash, load_golden

    generated = generate_world(seed=0, wdays=[], embed_golden=True)
    before = canonical_hash(generated.world)
    key = build_answer_key(generated, "test")
    ns31 = {cid: row for cid, row in key["coupons"].items()
            if row["flight_id"] == "NS31@2025-01-24"}
    assert len(ns31) == 172
    assert sum(row["compensation_cents"] for row in ns31.values()) == 9_900_000
    assert ns31["NS31@2025-01-24:14C"]["voucher_offset_cents"] == 0
    assert set(key["coupons"]) == {c.id for c in load_golden().coupons}
    assert canonical_hash(generated.world) == before


def test_claim_key_rejects_missing_authority_duplicates_and_expiry():
    from world.answer_key import build_answer_key

    generated = generate_world(seed=0, wdays=[], embed_golden=True)
    def claim(cid, at, **kw):
        return Claim(id=cid, coupon_id="NS31@2025-01-24:14C", received_at=at,
                     channel=kw.get("channel", "direct"), authority=kw.get("authority"),
                     amount_claimed_cents=999_999, text="Simulated claim for the same coupon.")
    generated.world = generated.world.model_copy(update={"claims": [
        claim("no-authority", datetime(2025, 1, 25, tzinfo=UTC), channel="agency", authority="none"),
        claim("valid", datetime(2025, 1, 26, tzinfo=UTC)),
        claim("duplicate", datetime(2025, 1, 27, tzinfo=UTC)),
        claim("expired", datetime(2031, 1, 25, tzinfo=UTC)),
    ]})
    rows = build_answer_key(generated, "test")["claims"]
    assert rows["no-authority"]["reason"] == "authority_none"
    assert rows["valid"]["pay_cents"] == 60_000
    assert rows["duplicate"]["reason"] == "duplicate"
    assert rows["expired"]["reason"] == "after_limitation"
    assert all(rows[c]["pay_cents"] == 0 for c in ("no-authority", "duplicate", "expired"))


def test_answer_keys_are_split_and_reproducible_on_disk(tmp_path):
    from world.answer_key import write_answer_keys
    from world.days import world_days

    days = [d for d in world_days() if d.day.isoformat() == "2024-01-21"]
    generated = generate_world(seed=0, wdays=days, embed_golden=True)
    files = write_answer_keys(generated, tmp_path)
    first = {split: path.read_bytes() for split, path in files.items()}
    keys = {split: orjson.loads(data) for split, data in first.items()}
    assert keys["train"]["coverage"]["coupons"] > 0
    assert keys["test"]["coverage"]["coupons"] > 0
    assert not set(keys["train"]["flights"]) & set(keys["test"]["flights"])
    assert set(keys["train"]["coupons"]) | set(keys["test"]["coupons"]) == {c.id for c in generated.world.coupons}
    write_answer_keys(generated, tmp_path)
    assert all(path.read_bytes() == first[split] for split, path in files.items())
