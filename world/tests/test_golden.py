"""F0: golden Éowyn embed. The generated world's golden slice equals golden byte-for-byte (canonical hash)."""
from __future__ import annotations

from datetime import date

import orjson
import pytest

from world import golden
from world.days import world_days
from world.generator import generate_world

pytestmark = pytest.mark.skipif(not golden.available(), reason="golden world.json not landed yet")


@pytest.fixture(scope="module")
def embedded():
    days = [w for w in world_days() if w.day in (date(2024, 12, 7), date(2025, 2, 23), date(2025, 1, 30))]
    return generate_world(0, days, embed_golden=True)


def test_golden_loads_verbatim():
    g = golden.load_golden()
    raw = orjson.loads(golden.GOLDEN_PATH.read_bytes())
    assert len(g.flights) == len(raw["flights"]) and len(g.coupons) == len(raw["coupons"])
    assert golden.golden_days() == {date(2025, 1, 24), date(2025, 1, 26)}


def test_embedded_slice_equals_golden_canonical_hash(embedded):
    g = golden.load_golden()
    sl = golden.golden_slice(embedded.world)
    assert golden.canonical_hash(sl) == golden.canonical_hash(g)
    assert embedded.world.meta["golden_hash"] == golden.canonical_hash(g)


def test_full_world_embed_keeps_golden_identical(full_world):
    full = full_world
    assert golden.canonical_hash(golden.golden_slice(full.world)) == golden.canonical_hash(golden.load_golden())
    # the generator did not simulate golden's days
    gen_days = {m["date"] for m in full.world.meta["days"] if not m.get("golden")}
    assert not gen_days & {"2025-01-24", "2025-01-26"}
    ids = [f.id for f in full.world.flights]
    assert len(ids) == len(set(ids))


def test_embedded_world_keeps_the_golden_hero_case(embedded):
    w = embedded.world
    ns31 = next(f for f in w.flights if f.id == "NS31@2025-01-24")
    assert ns31.ops_cause_code == "71" and ns31.aircraft == "EI-NSB" and ns31.pax == 172
    assert any(c.id == "NS31@2025-01-24:14C" for c in w.coupons)
    assert sum(f.pax for f in w.flights if f.id in golden.load_golden().meta["storms"]["EIDW@2025-01-24"]["flight_ids"]
               and f.status == "cancelled") == 5292
    assert w.meta["distances_km"]["DUB-BCN"] == 1486          # golden's pinned plan distance wins


def test_golden_truth_comes_from_golden_groups_not_the_engine(embedded):
    t = embedded.truth.flights
    assert t["NS31@2025-01-24"].cause == "technical" and t["NS31@2025-01-24"].extraordinary == "not_extraordinary"
    assert "miscoded_technical" in t["NS31@2025-01-24"].planted
    for fid in ("NS113@2025-01-24", "NS115@2025-01-24", "NS117@2025-01-24"):
        assert t[fid].cause == "knock_on" and t[fid].expected_route == "legal"
    assert t["NS101@2025-01-24"].cause == "weather"
    assert t["NS106@2025-01-26"].cause == "technical" and "miscoded_technical" in t["NS106@2025-01-26"].planted
    assert sum(1 for x in t.values() if x.golden and x.status == "cancelled") == 27 + 4


def test_embed_refuses_id_collisions():
    g = golden.load_golden()
    with pytest.raises(ValueError):
        golden.embed(g, g)
