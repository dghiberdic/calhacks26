"""F0 · The golden Éowyn world, embedded verbatim inside the generated Northstar world.

`contracts/fixtures/golden/world.json` (David, D0b) is the hero day EIDW@2025-01-24 plus the Herminia mini-day
EIDW@2025-01-26, the Isha opening balance and the mined history. It is loaded **as is** and spliced into the
generated world; the generator simply does not simulate the golden days. Every coupon id, 14C, NS31 and all golden
numbers therefore stay identical, and `golden_slice(world)` returns a World whose canonical hash equals golden's.

Where the two worlds share a key, golden wins: airports (identical anyway), `meta.distances_km` (golden's rounded
plan distances), `metar` keys, `real_context`. Golden's own `meta` is kept whole under `meta["golden"]`.
"""
from __future__ import annotations

import hashlib
from dataclasses import dataclass
from datetime import date
from functools import lru_cache
from pathlib import Path
from typing import Any

import orjson

from contracts.models import World

ROOT = Path(__file__).resolve().parent.parent
GOLDEN_PATH = ROOT / "contracts" / "fixtures" / "golden" / "world.json"


def canonical_hash(model: Any) -> str:
    data = model.model_dump(mode="json") if hasattr(model, "model_dump") else model
    return hashlib.sha256(orjson.dumps(data, option=orjson.OPT_SORT_KEYS)).hexdigest()


def available() -> bool:
    return GOLDEN_PATH.exists()


@lru_cache(maxsize=1)
def load_golden() -> World:
    """The golden world, validated, verbatim."""
    return World.model_validate(orjson.loads(GOLDEN_PATH.read_bytes()))


def golden_days(g: World | None = None) -> frozenset[date]:
    """World days (Dublin local) that golden owns: every `meta.storms[*].local_date`."""
    g = g or load_golden()
    return frozenset(date.fromisoformat(s["local_date"]) for s in g.meta.get("storms", {}).values())


@dataclass(frozen=True)
class GoldenIds:
    flights: frozenset[str]
    coupons: frozenset[str]
    tech_log: frozenset[str]
    ops_log: frozenset[str]
    crm: frozenset[str]
    claims: frozenset[str]
    care: frozenset[str]
    sources: frozenset[str]
    history: frozenset[str]
    cohorts: frozenset[str]
    airports: tuple[str, ...]
    metar: tuple[str, ...]
    real_context: tuple[str, ...]


@lru_cache(maxsize=1)
def golden_ids() -> GoldenIds:
    g = load_golden()
    return GoldenIds(
        flights=frozenset(f.id for f in g.flights), coupons=frozenset(c.id for c in g.coupons),
        tech_log=frozenset(e.id for e in g.tech_log), ops_log=frozenset(e.id for e in g.ops_log),
        crm=frozenset(e.id for e in g.crm), claims=frozenset(c.id for c in g.claims),
        care=frozenset(c.id for c in g.care), sources=frozenset(s.id for s in g.sources),
        history=frozenset(h.ruling_id for h in g.history_cases),
        cohorts=frozenset(o.cohort for o in g.opening_balances),
        airports=tuple(a.icao for a in g.airports), metar=tuple(g.metar), real_context=tuple(g.real_context))


def _before(items: list, key, cut: date) -> tuple[list, list]:
    a = [x for x in items if key(x) < cut]
    b = [x for x in items if key(x) >= cut]
    return a, b


def embed(world: World, g: World | None = None) -> World:
    """Splice golden into a generated world that does not simulate golden's days. Raises on any id collision."""
    g = g or load_golden()
    ids = golden_ids()
    clash = ({f.id for f in world.flights} & ids.flights) | ({c.id for c in world.coupons} & ids.coupons) \
        | ({s.id for s in world.sources} & ids.sources) | ({e.id for e in world.ops_log} & ids.ops_log) \
        | ({e.id for e in world.tech_log} & ids.tech_log) | ({e.id for e in world.crm} & ids.crm) \
        | ({c.id for c in world.claims} & ids.claims) | ({c.id for c in world.care} & ids.care) \
        | (set(world.metar) & set(ids.metar))
    if clash:
        raise ValueError(f"generated world collides with golden ids: {sorted(clash)[:5]}")
    cut = min(golden_days(g))

    def splice(gen: list, gold: list, key) -> list:
        a, b = _before(gen, key, cut)
        return a + list(gold) + b

    flights = splice(world.flights, g.flights, lambda f: f.date)
    fdate = {f.id: f.date for f in flights}
    coupons = splice(world.coupons, g.coupons, lambda c: fdate[c.flight_id])
    elections = splice(world.elections, g.elections, lambda e: fdate[e.coupon_id.rsplit(":", 1)[0]])
    crm = splice(world.crm, g.crm, lambda e: e.at.date())
    claims = splice(world.claims, g.claims, lambda c: c.received_at.date())
    care = splice(world.care, g.care, lambda c: fdate[c.flight_id])
    tech = splice(world.tech_log, g.tech_log, lambda e: e.logged_at.date())
    ops = splice(world.ops_log, g.ops_log, lambda e: e.at.date())
    sources = splice(world.sources, g.sources, lambda s: s.received_at.date())
    gold_ap = {a.icao for a in g.airports}
    airports = list(g.airports) + [a for a in world.airports if a.icao not in gold_ap]
    metar = {**world.metar, **g.metar}
    meta = dict(world.meta)
    meta["golden"] = g.meta
    meta["golden_hash"] = canonical_hash(g)
    meta["distances_km"] = {**world.meta.get("distances_km", {}), **g.meta.get("distances_km", {})}
    history = list(g.history_cases) + [h for h in world.history_cases if h.ruling_id not in ids.history]
    opening = list(g.opening_balances) + [o for o in world.opening_balances if o.cohort not in ids.cohorts]
    return World(meta=meta, airports=airports, flights=flights, tech_log=tech, ops_log=ops, coupons=coupons,
                 elections=elections, crm=crm, claims=claims, care=care, metar=metar, sources=sources,
                 history_cases=history, opening_balances=opening,
                 real_context={**world.real_context, **g.real_context})


def golden_slice(world: World) -> World:
    """The golden part of an embedded world, in golden's own order (canonical hash == golden's)."""
    ids = golden_ids()
    ap = {a.icao: a for a in world.airports}
    return World(
        meta=world.meta["golden"],
        airports=[ap[i] for i in ids.airports],
        flights=[f for f in world.flights if f.id in ids.flights],
        tech_log=[e for e in world.tech_log if e.id in ids.tech_log],
        ops_log=[e for e in world.ops_log if e.id in ids.ops_log],
        coupons=[c for c in world.coupons if c.id in ids.coupons],
        elections=[e for e in world.elections if e.coupon_id in ids.coupons],
        crm=[e for e in world.crm if e.id in ids.crm],
        claims=[c for c in world.claims if c.id in ids.claims],
        care=[c for c in world.care if c.id in ids.care],
        metar={k: world.metar[k] for k in ids.metar},
        sources=[s for s in world.sources if s.id in ids.sources],
        history_cases=[h for h in world.history_cases if h.ruling_id in ids.history],
        opening_balances=[o for o in world.opening_balances if o.cohort in ids.cohorts],
        real_context={k: world.real_context[k] for k in ids.real_context},
    )


# ---------------------------------------------------------------- ground truth for golden flights (plan §1.2)

GOLDEN_GROUP_TRUTH = {
    # group in golden meta.groups -> (latent, cause, extraordinary, expected_route)
    "outbound_weather": ("weather_dep", "weather", "extraordinary", None),
    "return_weather": ("weather_arr", "weather", "extraordinary", None),
    "overnight_inbound": ("weather_arr", "weather", "extraordinary", None),
    # knock-on returns: Legal's R-LEG-1 (no spare within 3 h, earliest reroute offered) makes them extraordinary
    "knock_on": ("rotation", "knock_on", "extraordinary", "legal"),
    "technical": ("internal_aog", "technical", "not_extraordinary", None),
    "h_technical": ("internal_aog", "technical", "not_extraordinary", None),
    "h_weather": ("weather_dep", "weather", "extraordinary", None),
    "operated": ("none", None, None, None),
    "h_operated": ("none", None, None, None),
}


def golden_flight_truth(g: World | None = None) -> dict[str, dict[str, Any]]:
    """Per-flight truth for golden flights, from golden's own `meta.groups` (the plan's truth table), never from
    the engine. Planted tags mark the golden error cases (NS31 and NS106@26JAN miscoded 71, knock-on returns)."""
    g = g or load_golden()
    out: dict[str, dict[str, Any]] = {}
    flights = {f.id: f for f in g.flights}
    for group, members in g.meta.get("groups", {}).items():
        latent, cause, extra, route = GOLDEN_GROUP_TRUTH[group]
        for fid in members:
            f = flights[fid]
            planted: list[str] = []
            if latent == "internal_aog" and f.ops_cause_code in ("71", "72"):
                planted.append("miscoded_technical")
            if latent == "rotation":
                planted.append("knock_on_return")
            out[fid] = {"latent": latent, "cause": cause, "extraordinary": extra, "expected_route": route,
                        "status": f.status, "planted": planted, "golden": True,
                        "root_flight_id": f.outbound_pair_id if latent == "rotation" else None,
                        "root_latent": "weather_dep" if latent == "rotation" else None,
                        "spare_within_3h": False if latent == "rotation" else None,
                        "reroute_earliest_offered": True if latent == "rotation" else None}
    return out
