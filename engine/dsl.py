"""Rule DSL (CONTRACTS §4): validation and evaluation over the allowlisted features only.

Shape: ``{"all": [...]}`` / ``{"any": [...]}`` / ``{"not": clause}``; a clause is ``{"f": feature, "op": op, "v": v}``.
An unknown feature or op makes the rule invalid. Scope is a flat ``{key: value}`` map over the same features plus
a few context keys (``storm``, ``cohort``...); values tagged ``case:<v>`` were copied from the case (not grounded in
the ruling) and still constrain.

Pure: no wall clock, no randomness.
"""
from __future__ import annotations

from collections.abc import Iterable, Mapping
from datetime import date, datetime
from typing import Any

from contracts.models import Rule

FEATURES = frozenset({
    # flight
    "flight.in_window_dep", "flight.in_window_arr", "flight.window_margin_min", "flight.distance_km",
    "flight.band_eur", "flight.departs_eu", "flight.arrives_eu", "flight.operating_carrier_eu",
    "flight.route_region", "flight.ops_cause_code", "flight.is_return_sector",
    # aog
    "aog.before_window", "aog.inside_window", "aog.ata_chapter", "aog.root_cause_internal", "aog.mel_relief",
    # rotation
    "rotation.prev_cancelled", "rotation.prev_cause", "spare.available_within_h",
    # passenger
    "pax.notice_days", "pax.arrival_delay_min", "pax.election", "pax.reroute_earliest_offered", "pax.fare_type",
    # voucher
    "voucher.in_lieu", "voucher.signed", "voucher.amount_cents",
    # claim
    "claim.channel", "claim.authority", "claim.duplicate", "claim.age_months", "claim.after_limitation",
    "claim.regime",
    # cohort
    "cohort.age_months", "cohort.months_since_last_claim", "cohort.limitation_expired",
    # evidence
    "sources.disagree", "precedent.count",
})

# Scope may also pin the case's context (widen removes these one rung at a time). ``pattern`` is the question a cause
# ruling answers; the engine sets it (never the drafter) and widen never removes it.
CONTEXT_KEYS = frozenset({"storm", "cohort", "flight", "station", "segment", "coupon", "pattern"})

OPS = frozenset({"eq", "ne", "lt", "le", "gt", "ge", "in", "nin", "exists"})

TIER_RANK = {  # higher wins (plan §2 rule 4)
    "hard_control": 6, "regulation": 5, "legal_ruling": 4, "controller_ruling": 3, "claims_lead_ruling": 2,
    "mined": 1,
}

CASE_PREFIX = "case:"


class DslError(ValueError):
    pass


# ---------- validation ----------

def validate(cond: Any, path: str = "$") -> list[str]:
    """All problems with a condition (empty list = valid)."""
    errs: list[str] = []
    if not isinstance(cond, Mapping):
        return [f"{path}: clause must be an object"]
    keys = set(cond)
    if keys == {"all"} or keys == {"any"}:
        k = next(iter(keys))
        items = cond[k]
        if not isinstance(items, list):
            return [f"{path}.{k}: must be a list"]
        for i, c in enumerate(items):
            errs += validate(c, f"{path}.{k}[{i}]")
        return errs
    if keys == {"not"}:
        return validate(cond["not"], f"{path}.not")
    if {"f", "op"} <= keys <= {"f", "op", "v"}:
        f, op = cond["f"], cond["op"]
        if f not in FEATURES:
            errs.append(f"{path}: unknown feature {f!r}")
        if op not in OPS:
            errs.append(f"{path}: unknown op {op!r}")
        if op in {"in", "nin"} and not isinstance(cond.get("v"), list):
            errs.append(f"{path}: op {op!r} needs a list value")
        if op != "exists" and "v" not in cond:
            errs.append(f"{path}: op {op!r} needs a value")
        return errs
    return [f"{path}: unrecognised clause keys {sorted(keys)}"]


def validate_scope(scope: Any) -> list[str]:
    if not isinstance(scope, Mapping):
        return ["scope must be an object"]
    return [f"scope: unknown key {k!r}" for k in scope if k not in FEATURES and k not in CONTEXT_KEYS]


def literals(cond: Any) -> list[Any]:
    """Every literal value in a condition (for grounding checks), in order."""
    out: list[Any] = []
    if isinstance(cond, Mapping):
        if "all" in cond or "any" in cond:
            for c in cond.get("all", cond.get("any", [])):
                out += literals(c)
        elif "not" in cond:
            out += literals(cond["not"])
        elif "v" in cond:
            v = cond["v"]
            out += list(v) if isinstance(v, list) else [v]
    return out


def clauses(cond: Any) -> list[dict[str, Any]]:
    """Every leaf clause in a condition."""
    out: list[dict[str, Any]] = []
    if isinstance(cond, Mapping):
        if "all" in cond or "any" in cond:
            for c in cond.get("all", cond.get("any", [])):
                out += clauses(c)
        elif "not" in cond:
            out += clauses(cond["not"])
        elif "f" in cond:
            out.append(dict(cond))
    return out


# ---------- evaluation ----------

def strip_case(v: Any) -> Any:
    if isinstance(v, str) and v.startswith(CASE_PREFIX):
        raw = v[len(CASE_PREFIX):]
        return {"true": True, "false": False}.get(raw, raw)
    return v


def _cmp(op: str, a: Any, b: Any) -> bool:
    if a is None:
        if op == "eq":
            return b is None
        if op == "ne":
            return b is not None
        if op in {"in", "nin"}:
            hit = isinstance(b, list) and None in b
            return hit if op == "in" else not hit
        return False
    try:
        if op == "eq":
            return a == b
        if op == "ne":
            return a != b
        if op == "lt":
            return a < b
        if op == "le":
            return a <= b
        if op == "gt":
            return a > b
        if op == "ge":
            return a >= b
        if op == "in":
            return a in b
        if op == "nin":
            return a not in b
    except TypeError:
        return False
    raise DslError(f"unknown op {op!r}")


def evaluate(cond: Mapping[str, Any], feats: Mapping[str, Any]) -> bool:
    """Evaluate a validated condition. A missing feature reads as ``None``."""
    if "all" in cond:
        return all(evaluate(c, feats) for c in cond["all"])
    if "any" in cond:
        return any(evaluate(c, feats) for c in cond["any"])
    if "not" in cond:
        return not evaluate(cond["not"], feats)
    f, op = cond["f"], cond["op"]
    if f not in FEATURES:
        raise DslError(f"unknown feature {f!r}")
    val = feats.get(f)
    if op == "exists":
        want = cond.get("v", True)
        return (val is not None) == bool(want)
    return _cmp(op, val, cond.get("v"))


def scope_matches(scope: Mapping[str, Any], feats: Mapping[str, Any]) -> bool:
    for k, v in scope.items():
        want = strip_case(v)
        got = feats.get(k)
        if isinstance(want, list):
            if got not in [strip_case(x) for x in want]:
                return False
        elif got != want:
            return False
    return True


def specificity(rule: Rule) -> int:
    return len(rule.scope) + len(clauses(rule.condition))


def _as_date(t: datetime | date | None) -> date | None:
    if t is None:
        return None
    return t.date() if isinstance(t, datetime) else t


def in_force(rule: Rule, known_at: datetime | None, flight_date: date | None) -> bool:
    """Bitemporal filter (plan §2 rule 7): active, recorded by ``known_at``, valid for the flight's date."""
    if rule.static_card or rule.status != "active":
        return False
    if known_at is not None and rule.recorded_at > known_at:
        return False
    vf = _as_date(rule.valid_from)
    if vf is not None and flight_date is not None and vf > flight_date:
        return False
    return True


def applies(rule: Rule, feats: Mapping[str, Any], known_at: datetime | None = None,
            flight_date: date | None = None) -> bool:
    if not in_force(rule, known_at, flight_date):
        return False
    if validate(rule.condition) or validate_scope(rule.scope):
        return False  # an invalid rule never fires
    return scope_matches(rule.scope, feats) and evaluate(rule.condition, feats)


def precedence_key(rule: Rule) -> tuple[int, int, datetime, str, int]:
    """Sort key, ascending = weaker: tier, then specificity, then recorded_at, then id/version (stable tie-break)."""
    return (TIER_RANK.get(rule.tier, 0), specificity(rule), rule.recorded_at, rule.id, rule.version)


def matching(rules: Iterable[Rule], feats: Mapping[str, Any], *, actions: Iterable[Any] | None = None,
             known_at: datetime | None = None, flight_date: date | None = None) -> list[Rule]:
    """Applicable rules, strongest first. ``actions`` filters by ``RuleAction``."""
    acts = None if actions is None else set(actions)
    hits = [r for r in rules if (acts is None or r.action in acts) and applies(r, feats, known_at, flight_date)]
    return sorted(hits, key=precedence_key, reverse=True)


def ref(rule: Rule) -> str:
    return f"{rule.id}@{rule.version}"
