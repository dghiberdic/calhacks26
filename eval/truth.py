"""Expand the team's compact independent answer key for scoring; preserve its exported format verbatim."""
from world.answer_key import build


def expanded_keys(generated) -> dict:
    keys = build(generated)
    for key in keys.values():
        packed = key["coupons"]
        expanded = {}
        for coupon in generated.world.coupons:
            record = packed.get(coupon.flight_id)
            if record is None:
                continue
            seat = coupon.id.rsplit(":", 1)[1]
            row = dict(record["exceptions"].get(seat, record["default"]))
            row.update(flight_id=coupon.flight_id, band_eur=record["band_eur"], segment=record["segment"])
            row["pay_cents"] = max(0, row.get("compensation_cents", 0) - row.get("voucher_offset_cents", 0))
            expanded[coupon.id] = row
        key["coupons"] = expanded
    return keys
