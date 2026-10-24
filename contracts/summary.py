"""The Flight File entitlements summary: every key of `contracts.models.EntitlementsSummary`, from Entitlements alone.

One builder shared by the engine (`engine.eu261.summarize`), the fakes and the fixture script, so the UI reads the
same keys and wording everywhere (plan §9). Pure: counts, sums and labels of numbers the engine already computed;
it never decides who is owed.
"""
from __future__ import annotations

from collections import Counter
from collections.abc import Mapping, Sequence
from fractions import Fraction
from typing import Any

from .models import Entitlement

DEFAULT_RATES: dict[int, Fraction] = {600: Fraction(35, 100), 400: Fraction(27, 100), 250: Fraction(20, 100)}
SEGMENT = {600: "long_haul_gt3500", 400: "medium_1500_3500", 250: "short_le1500"}
ACCRUING = ("owed", "needs_ruling", "held")
STATUS_LABEL = {
    "owed": "owed, payout drafted pending Claims Lead approval",
    "needs_ruling": "waits on a ruling",
    "held": "held for Legal",
    "no_compensation": "no compensation; refunds and care still due",
    "exempt_notice": "exempt: told 14+ days ahead (Art. 5(1)(c))",
    "out_of_scope": "outside EU261 (Art. 3)",
    "staff_ticket": "staff ticket (Art. 3(3))",
}
STATUS_ORDER = ("owed", "needs_ruling", "held", "no_compensation", "exempt_notice", "out_of_scope", "staff_ticket")


def eur(cents: int) -> str:
    return f"€{cents / 100:,.0f}" if cents % 100 == 0 else f"€{cents / 100:,.2f}"


def _round(x: Fraction) -> int:
    n = abs(x)
    q = int(n) + (1 if n - int(n) >= Fraction(1, 2) else 0)
    return q if x >= 0 else -q


def band_label(distance_km: float, band_eur: int, margin_km: float) -> str:
    """Same wording as engine.eu261.Band.note: '4,804 km · 1,304 km over the €600 threshold'."""
    if band_eur == 250:
        return f"{distance_km:,.0f} km · {margin_km:,.0f} km under the €400 band"
    if band_eur == 600:
        return f"{distance_km:,.0f} km · {margin_km:,.0f} km over the €600 threshold"
    if abs((distance_km - 1500) - margin_km) < 0.6:
        return f"{distance_km:,.0f} km · {margin_km:,.0f} km over the €400 threshold"
    return f"{distance_km:,.0f} km · {margin_km:,.0f} km under the €600 band"


def entitlements_summary(ents: Sequence[Entitlement], *, elections: Mapping[str, str] | None = None,
                         rates: Mapping[int, Fraction] | None = None) -> dict[str, Any]:
    """All documented summary keys for one flight's entitlements. `elections` maps coupon id → election kind."""
    rates = dict(rates or DEFAULT_RATES)
    counts = Counter(e.status for e in ents)
    out: dict[str, Any] = {
        "coupons": len(ents),
        "compensation_cents": sum(e.compensation_cents for e in ents),
        "status_counts": dict(sorted(counts.items())),
        "reduced": sum(1 for e in ents if e.reduction != "none"),
        "refunds_already_initiated": sum(1 for e in ents if e.refund_already_initiated),
        "refund_due_cents": sum(e.refund_due_cents for e in ents),
        "voucher_offset_cents": sum(e.voucher_offset_cents for e in ents),
        "care_due": any(e.care_due for e in ents),
        "owed": counts.get("owed", 0), "needs_ruling": counts.get("needs_ruling", 0), "held": counts.get("held", 0),
    }
    if not ents:
        return out
    first = ents[0]
    out.update(distance_km=first.distance_km, band_eur=first.band_eur, band_margin_km=first.band_margin_km)
    out["band_label"] = out["band_note"] = band_label(first.distance_km, first.band_eur, first.band_margin_km)

    accruing = [e for e in ents if e.status in ACCRUING and e.compensation_cents > 0]
    full = sum(e.compensation_cents for e in accruing)
    by_band: dict[int, int] = {}
    for e in accruing:
        by_band[e.band_eur] = by_band.get(e.band_eur, 0) + e.compensation_cents
    drafted = sum(_round(Fraction(v) * rates[b]) for b, v in by_band.items())
    bands = sorted({e.band_eur for e in ents})
    rate = rates.get(bands[0]) if len(bands) == 1 else None
    out.update(full_entitlement_cents=full, drafted_liability_cents=drafted, liability_drafted_cents=drafted)
    out["full_entitlement_label"] = f"{eur(full)} full Art. 7 entitlement if every passenger claims"
    if rate is not None:
        out["claim_rate"] = out["expected_ultimate_claim_rate"] = round(float(rate), 4)
        out["claim_rate_label"] = (f"{float(rate):.0%} expected ultimate claim rate (history to M18 + tail "
                                   "judgment)")

    out["statuses"] = [{"status": s, "count": counts[s], "label": STATUS_LABEL.get(s, s)}
                       for s in STATUS_ORDER if counts.get(s)]
    groups: dict[tuple[int, str, int], int] = {}
    for e in accruing:
        k = (e.band_eur, e.reduction, e.compensation_cents)
        groups[k] = groups.get(k, 0) + 1
    out["compensation_breakdown"] = [
        {"band_eur": b, "reduction": r, "count": n, "each_cents": each, "total_cents": n * each}
        for (b, r, each), n in sorted(groups.items(), key=lambda kv: (-kv[0][2], kv[0][1]))]
    if groups:
        reduced = any(r != "none" for (_, r, _) in groups)
        out["formula"] = " + ".join(f"{n} × {eur(each)}" for (_, _, each), n in
                                    sorted(groups.items(), key=lambda kv: -kv[0][2])) + (
            " (Art. 7(2)(c))" if reduced else "")
    red = [e for e in ents if e.reduction != "none"]
    if red:
        rules = sorted({r for e in red for r in e.rules_applied if "REDUCE" in r.upper()} or
                       {r for e in red for r in e.rules_applied})
        out["reduction_7_2"] = {"count": len(red), "saved_cents": sum(e.band_eur * 100 - e.compensation_cents
                                                                      for e in red), "rules": rules}

    held = [e for e in ents if e.status == "held"]
    if held:
        hv = sum(e.compensation_cents for e in held)
        acc = sum(_round(Fraction(sum(e.compensation_cents for e in held if e.band_eur == b)) * rates[b])
                  for b in {e.band_eur for e in held})
        out["accrued_cents"] = acc
        out["compensation_if_owed_cents"] = hv
        if rate is not None:
            out["accrual_basis"] = f"IFRS 15.56 constraint · {SEGMENT[bands[0]]} {float(rate):.0%}"

    n_owed, n_rul, n_held = counts.get("owed", 0), counts.get("needs_ruling", 0), len(held)
    if n_owed or n_rul:
        line = f"{n_owed} payouts drafted, pending Claims Lead approval"
        if n_rul:
            line += f" · {n_rul} {'waits' if n_rul == 1 else 'wait'} on a ruling"
        out["status_line"] = line
    elif n_held:
        out["status_line"] = f"Held for Legal · {eur(out['accrued_cents'])} accrued at the segment rate"
    elif counts.get("no_compensation"):
        out["status_line"] = "No compensation; refunds and care still due"
    else:
        out["status_line"] = "; ".join(f"{counts[s]} {STATUS_LABEL.get(s, s)}" for s in STATUS_ORDER if counts.get(s))
    if elections is not None:
        out["elections"] = dict(sorted(Counter(elections[e.coupon_id] for e in ents if e.coupon_id in elections)
                                       .items()))
    return out
