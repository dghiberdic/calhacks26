from world.generator import generate_world


def test_evaluation_expands_shared_truth_without_changing_the_world_or_compact_export():
    from eval.truth import expanded_keys
    from world.answer_key import build
    from world.golden import canonical_hash

    generated = generate_world(seed=0, wdays=[], embed_golden=True)
    before = canonical_hash(generated.world)
    packed = build(generated)
    expanded = expanded_keys(generated)
    ns31 = {cid: row for cid, row in expanded["test"]["coupons"].items()
            if row["flight_id"] == "NS31@2025-01-24"}
    assert len(ns31) == 172
    assert sum(row.get("compensation_cents", 0) for row in ns31.values()) == 9900000
    assert ns31["NS31@2025-01-24:14C"].get("voucher_offset_cents", 0) == 0
    assert "NS31@2025-01-24" in packed["test"]["coupons"]
    assert "NS31@2025-01-24:14C" not in packed["test"]["coupons"]
    assert canonical_hash(generated.world) == before
