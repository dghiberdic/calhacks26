"""D0b: the golden world (contracts/fixtures/golden/world.json) is valid, up to date, and matches the plan.

Reference computations here are deliberately tiny and test-local (never engine code): the storm-window definition
of plan §1.2 and the Art. 7 arithmetic of plan §1.3.
"""
from __future__ import annotations

import csv
import hashlib
import importlib.util
import json
import re
from collections import Counter
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from contracts.models import ClaimCurve, MetarObs, World

ROOT = Path(__file__).resolve().parents[2]
GOLDEN = ROOT / "contracts" / "fixtures" / "golden"
UTC = timezone.utc
EOWYN, HERMINIA, ISHA = "EIDW@2025-01-24", "EIDW@2025-01-26", "EIDW@2024-01-21"
NS31 = "NS31@2025-01-24"
ID_RE = re.compile(r"^[A-Za-z0-9@.:_-]+$")
KNOWN_AT = datetime(2025, 1, 25, 6, 0, tzinfo=UTC)


def t(s: str) -> datetime:
    return datetime.fromisoformat(s.replace("Z", "+00:00"))


@pytest.fixture(scope="module")
def raw() -> str:
    return (GOLDEN / "world.json").read_text(encoding="utf-8")


@pytest.fixture(scope="module")
def world(raw: str) -> World:
    return World.model_validate_json(raw)


@pytest.fixture(scope="module")
def flights(world: World):
    return {f.id: f for f in world.flights}


def eowyn_cancelled(world: World, flights):
    return [flights[i] for i in world.meta["storms"][EOWYN]["flight_ids"] if flights[i].status == "cancelled"]


# ---------------------------------------------------------------- reference storm window (plan §1.2, binding)
def is_storm(o: MetarObs) -> bool:
    wx = o.wxcodes or ""
    return ((o.gust or 0) >= 35 or (o.sknt or 0) >= 30 or (o.vsby_sm is not None and o.vsby_sm < 0.5)
            or any(c in wx for c in ("SN", "FZ", "TS", "GR")))


def ref_windows(obs: list[MetarObs]) -> list[tuple[datetime, datetime]]:
    hits = sorted((o.valid for o in obs if is_storm(o)))
    out: list[list[datetime]] = []
    for v in hits:
        if out and v - out[-1][1] < timedelta(hours=2):
            out[-1][1] = v
        else:
            out.append([v, v])
    return [(a, b) for a, b in out]


def calm_near(obs: list[MetarObs], when: datetime) -> bool:
    near = [o for o in obs if abs(o.valid - when) <= timedelta(minutes=60)]
    return bool(near) and not any(is_storm(o) for o in near)


def station_obs(world: World, icao: str) -> list[MetarObs]:
    return sorted((o for k, v in world.metar.items() if k.startswith(icao + "@") for o in v), key=lambda o: o.valid)


# ---------------------------------------------------------------- validity + freshness
def test_world_validates_and_is_up_to_date(raw: str, world: World):
    spec = importlib.util.spec_from_file_location("build_golden", ROOT / "scripts" / "build_golden.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    assert mod.render_world().decode("utf-8") == raw, "world.json is stale: run `uv run python scripts/build_golden.py`"
    assert mod.render_curves() == (GOLDEN / "curves.json").read_bytes(), "curves.json is stale"
    assert world.meta["golden_version"] == "golden-v1"


def test_every_datetime_is_utc_z(raw: str):
    stamps = re.findall(r'"(\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}[^"]*)"', raw)
    assert stamps and all(s.endswith("Z") for s in stamps), {s for s in stamps if not s.endswith("Z")}


def test_ids_use_the_id_charset_and_are_unique(world: World):
    groups = {
        "flights": [f.id for f in world.flights], "coupons": [c.id for c in world.coupons],
        "sources": [s.id for s in world.sources], "crm": [e.id for e in world.crm], "claims": [c.id for c in world.claims],
        "care": [c.id for c in world.care], "ops_log": [e.id for e in world.ops_log],
        "tech_log": [e.id for e in world.tech_log], "history": [h.ruling_id for h in world.history_cases],
        "metar_keys": list(world.metar),
    }
    for name, ids in groups.items():
        bad = [i for i in ids if not ID_RE.match(i)]
        assert not bad, (name, bad[:5])
        assert len(ids) == len(set(ids)), name


# ---------------------------------------------------------------- Éowyn day (plan §1.2)
def test_eowyn_27_cancelled_11_operated_5292_pax(world: World, flights):
    st = world.meta["storms"][EOWYN]
    ids = st["flight_ids"]
    canc = eowyn_cancelled(world, flights)
    assert len(canc) == 27 and len([i for i in ids if flights[i].status == "operated"]) == 11
    assert sum(f.pax for f in canc) == 5292 == st["passengers_cancelled"]
    groups = world.meta["groups"]
    assert {g: len(groups[g]) for g in ("outbound_weather", "return_weather", "overnight_inbound", "knock_on",
                                        "technical", "operated")} == {
        "outbound_weather": 13, "return_weather": 6, "overnight_inbound": 4, "knock_on": 3, "technical": 1,
        "operated": 11}
    ops = [flights[i] for i in groups["operated"]]
    assert all(t("2025-01-24T15:30:00Z") <= f.sched_dep <= t("2025-01-24T17:30:00Z") for f in ops)


def test_5292_coupons_with_one_election_each(world: World, flights):
    canc = {f.id: f for f in eowyn_cancelled(world, flights)}
    eowyn_coupons = [c for c in world.coupons if c.flight_id in canc]
    assert len(eowyn_coupons) == 5292
    per_flight = Counter(c.flight_id for c in world.coupons)
    assert all(per_flight[f.id] == f.pax for f in flights.values() if f.status == "cancelled")
    assert all(c.id.startswith(c.flight_id + ":") for c in world.coupons)
    elections = Counter(e.coupon_id for e in world.elections)
    assert set(elections) == {c.id for c in world.coupons} and set(elections.values()) == {1}
    assert all(c.fare_cents > 0 and c.taxes_cents > 0 for c in world.coupons)


def test_ns31_hero_flight(world: World, flights):
    f = flights[NS31]
    assert (f.origin, f.dest, f.aircraft, f.pax, f.ops_cause_code) == ("DUB", "BOS", "EI-NSB", 172, "71")
    assert f.sched_dep == t("2025-01-24T16:30:00Z")
    coupons = [c for c in world.coupons if c.flight_id == NS31]
    assert {(c.fare_cents, c.taxes_cents) for c in coupons} == {(45000, 6000)}
    el = {e.coupon_id: e for e in world.elections if e.coupon_id.startswith(NS31 + ":")}
    assert Counter(e.kind for e in el.values()) == {"refund": 32, "voucher": 14, "reaccommodated_own": 112,
                                                   "reroute_partner": 14}
    assert {e.arrival_delay_min for e in el.values() if e.kind == "reroute_partner"} == {220}
    reaccom = [e for e in el.values() if e.kind == "reaccommodated_own"]
    assert all(e.arrival_delay_min > 240 for e in reaccom)
    assert {e.new_arrival.date().isoformat() for e in reaccom} <= {"2025-01-25", "2025-01-26", "2025-01-27",
                                                                     "2025-01-28"}


def ref_entitlement_cents(world: World, flight_id: str) -> int:
    """Art. 7(1)(c) €600 for >3,500 km, halved under Art. 7(2)(c) when a reroute arrives within 4 h."""
    km = world.meta["distances_km"]["DUB-BOS"]
    assert km > 3500
    total = 0
    for e in world.elections:
        if e.coupon_id.startswith(flight_id + ":"):
            within = e.kind in ("reroute_partner", "reaccommodated_own") and (e.arrival_delay_min or 10**6) <= 240
            total += 30000 if within else 60000
    return total


def test_ns31_entitlement_is_9_900_000(world: World):
    assert ref_entitlement_cents(world, NS31) == 9_900_000 == 158 * 60000 + 14 * 30000


def test_ns31_atl_and_taxes(world: World):
    coupons = {c.id: c for c in world.coupons if c.flight_id == NS31}
    el = {e.coupon_id: e.kind for e in world.elections if e.coupon_id in coupons}
    by = lambda k: [coupons[c] for c, kk in el.items() if kk == k]  # noqa: E731
    assert sum(c.fare_cents for c in coupons.values()) == 7_740_000 and sum(c.taxes_cents for c in coupons.values()) == 1_032_000
    assert sum(c.fare_cents + c.taxes_cents for c in by("refund")) == 1_632_000
    assert sum(c.fare_cents + c.taxes_cents for c in by("voucher")) == 714_000
    assert sum(c.fare_cents for c in by("reroute_partner")) == 630_000
    assert sum(c.taxes_cents for c in by("reroute_partner")) == 84_000


def test_main_window_and_ns31_out_by_60_min(world: World, flights):
    wins = ref_windows(world.metar[EOWYN])
    main = max(wins, key=lambda w: w[1] - w[0])
    assert abs(main[0] - t("2025-01-24T02:30:00Z")) <= timedelta(minutes=30)
    assert abs(main[1] - t("2025-01-24T15:00:00Z")) <= timedelta(minutes=30)
    assert any(w[0] == t("2025-01-23T23:30:00Z") for w in wins), "minor 23:30Z window is separate"
    assert flights[NS31].sched_dep - main[1] >= timedelta(minutes=60)
    assert calm_near(station_obs(world, "KBOS"), flights[NS31].sched_arr), "NS31 is calm at BOS on arrival"


def test_weather_flights_sit_in_the_dub_window(world: World, flights):
    main = max(ref_windows(world.metar[EOWYN]), key=lambda w: w[1] - w[0])
    inside = lambda x: main[0] <= x <= main[1]  # noqa: E731
    g = world.meta["groups"]
    assert all(inside(flights[i].sched_dep) for i in g["outbound_weather"])
    assert all(inside(flights[i].sched_arr) for i in g["return_weather"] + g["overnight_inbound"])


def test_knock_on_returns_are_calm_at_both_ends(world: World, flights):
    main = max(ref_windows(world.metar[EOWYN]), key=lambda w: w[1] - w[0])
    icao = {a.iata: a.icao for a in world.airports}
    for fid in world.meta["groups"]["knock_on"]:
        f = flights[fid]
        assert f.outbound_pair_id and flights[f.outbound_pair_id].status == "cancelled"
        assert flights[f.outbound_pair_id].aircraft == f.aircraft
        assert calm_near(station_obs(world, icao[f.origin]), f.sched_dep), fid
        nearest = min(world.metar[EOWYN], key=lambda o: abs(o.valid - f.sched_arr))
        assert f.sched_arr > main[1] and not is_storm(nearest), fid     # after the window, calm at STA


# ---------------------------------------------------------------- logs (verbatim)
def test_logs_verbatim(world: World):
    tl = {e.aircraft: e for e in world.tech_log if e.aog and e.station == "DUB" and e.aircraft == "EI-NSB"}
    nsb = tl["EI-NSB"]
    assert nsb.text == ("23JAN 21:40Z EI-NSB DUB N/S. HYD FLUID ENG 2 LWR COWL. GND RUN: ECAM HYD Y ENG 2 PUMP LO PR. "
                        "EXT LEAK EDP CASE DRAIN PORT, EXCEEDS AMM LIMIT. EDP RPLCMT REQD. NO MEL RELIEF. A/C AOG.")
    assert (nsb.ata, nsb.mel_relief, nsb.logged_at) == ("2913", False, t("2025-01-23T21:40:00Z"))
    texts = {e.text for e in world.ops_log}
    assert ("05:12Z OCC DM: STORM ÉOWYN CNL LIST → NETLINE, RSN 71. NS100/101 NS102/103 NS104/105 NS106/107 "
            "NS108/109 NS110/111 NS112/113 NS114/115 NS116/117 NS118 NS21 NS41 NS51 NS31. INBD NS20 NS30 NS40 NS50 "
            "RSN 72. ASM SENT. IROPS SMS 05:20Z.") in texts
    assert "22:15Z: NO EDP IN DUB STORES; POOL UNIT EX-TLS VIA CDG 25JAN ETA 14:00Z, RTS EST 20:00Z." in texts
    assert ("No long-range tail at DUB. XLR EI-NSN at BOS (NS30 CNL 72); A330s at JFK/ORD/YYZ (NS20/40/50 CNL); "
            "A320/A321neo lack range.") in texts
    assert "No tail at MUC. Earliest ferry ex-DUB 15:30Z → MUC dep 18:25Z = STD+4h20." in texts
    assert {e.kind for e in world.ops_log} == {"occ", "mcc", "spares"}


# ---------------------------------------------------------------- CRM (plan §1.3)
def test_crm_bot_refunds_duplicate_chargeback_and_14c(world: World):
    bot = [e for e in world.crm if e.kind == "refund_initiated"]
    assert len(bot) == 32 and {e.actor for e in bot} == {"agent.crm_bot"}
    assert all(e.coupon_id.startswith(NS31 + ":") for e in bot)
    assert min(e.at for e in bot) == t("2025-01-24T06:02:00Z") and max(e.at for e in bot) == t("2025-01-24T09:40:00Z")
    assert sum(e.amount_cents for e in bot) == 1_632_000
    assert len([e for e in world.crm if e.kind == "rights_email_sent"]) == 32
    refunded = {e.coupon_id for e in bot}
    bsp = [e for e in world.crm if e.kind == "bsp_refund"]
    assert len(bsp) == 1 and bsp[0].coupon_id in refunded, "one BSP + bot duplicate"
    cb = [e for e in world.crm if e.kind == "chargeback"]
    assert len(cb) == 1 and cb[0].coupon_id in refunded and cb[0].coupon_id != bsp[0].coupon_id
    channels = Counter(c.channel for c in world.coupons if c.id in refunded)
    assert channels == {"direct": 31, "ota": 1}
    v = [e for e in world.crm if e.kind == "voucher_in_lieu_of_compensation" and e.coupon_id == NS31 + ":14C"]
    assert len(v) == 1 and v[0].amount_cents == 30000 and v[0].signed_acceptance_sha256 is None
    assert "IN LIEU OF COMPENSATION" in v[0].text and v[0].at == t("2025-01-24T14:20:00Z")


# ---------------------------------------------------------------- claims
def face_value(world: World, coupon_id: str) -> int:
    e = next(e for e in world.elections if e.coupon_id == coupon_id)
    return 30000 if e.kind in ("reroute_partner", "reaccommodated_own") and (e.arrival_delay_min or 10**6) <= 240 \
        else 60000


def test_claims_overnight_jan_and_feb(world: World):
    ns31 = [c for c in world.claims if c.coupon_id.startswith(NS31 + ":")]
    assert len(ns31) == len(world.claims) == 22
    overnight = [c for c in ns31 if t("2025-01-24T16:30:00Z") <= c.received_at <= KNOWN_AT]
    assert len(overnight) == 6
    assert sum(face_value(world, c.coupon_id) for c in overnight) == 360_000          # Jan: 6 × €600
    feb = [c for c in ns31 if c.received_at.strftime("%Y-%m") == "2025-02"]
    assert len(feb) == 16
    assert sorted(face_value(world, c.coupon_id) for c in feb) == [30000] + [60000] * 15
    assert sum(face_value(world, c.coupon_id) for c in feb) == 930_000
    c14 = next(c for c in overnight if c.coupon_id.endswith(":14C"))
    assert "I never agreed to take a voucher instead of my compensation" in c14.text
    assert any(c.coupon_id.endswith(":9B") and c.channel == "direct" for c in overnight)
    assert len({c.coupon_id for c in ns31}) == 22, "no duplicate claims in the golden world"
    agency = [c for c in ns31 if c.channel == "agency"]
    assert agency and all(c.authority == "poa" and c.agency for c in agency)


# ---------------------------------------------------------------- care
def test_care_accrued_and_invoiced(world: World, flights):
    acc = sum(c.amount_cents for c in world.care if not c.invoiced)
    inv = sum(c.amount_cents for c in world.care if c.invoiced)
    assert (acc, inv, acc - inv) == (22_700_000, 22_130_000, 570_000)
    assert {c.flight_id for c in world.care} == {f.id for f in eowyn_cancelled(world, flights)}


# ---------------------------------------------------------------- documents and sources
def test_eight_messy_documents_including_the_prompt_injection(world: World):
    src = {s.id: s for s in world.sources}
    messy = world.meta["messy_documents"]
    assert len(messy) == 8 and all(m in src for m in messy)
    inj = src[world.meta["prompt_injection_source"]]
    assert "ignore previous instructions" in inj.text and inj.trust_tier == 4


def test_sources_hash_tier_acl_and_record_links(world: World):
    for s in world.sources:
        assert s.text is not None and s.sha256 == hashlib.sha256(s.text.encode("utf-8")).hexdigest(), s.id
        assert 1 <= s.trust_tier <= 4
        assert set(s.acl_tags) <= {"pii", "ops", "finance", "legal", "maintenance"}, s.id
    ids = {s.id for s in world.sources}
    records = ([e.id for e in world.tech_log] + [e.id for e in world.ops_log] + [e.id for e in world.crm]
               + [c.id for c in world.claims])
    missing = [r for r in records if f"SRC-{r}" not in ids]
    assert not missing, missing[:5]
    src = {s.id: s for s in world.sources}
    for e in world.tech_log:
        assert e.text in src[f"SRC-{e.id}"].text and src[f"SRC-{e.id}"].trust_tier == 1
    for e in world.crm:
        assert e.text in src[f"SRC-{e.id}"].text
    for c in world.claims:
        assert c.text in src[f"SRC-{c.id}"].text and "pii" in src[f"SRC-{c.id}"].acl_tags
    for k in world.metar:
        assert f"SRC-METAR-{k}" in ids
    for f in world.flights:
        if f.status == "cancelled":
            assert f"SRC-PSS-{f.id}" in ids and f"SRC-MANIFEST-{f.id}" in ids


# ---------------------------------------------------------------- METAR (real)
def test_eidw_metar_is_the_real_csv(world: World):
    for key, file in ((EOWYN, "eidw_2025-01-23_25.csv"), (HERMINIA, "eidw_2025-01-26.csv")):
        rows = list(csv.DictReader((GOLDEN / file).open(encoding="utf-8")))
        obs = world.metar[key]
        assert [o.raw for o in obs] == [r["metar"] for r in rows]
        assert all(o.station == "EIDW" for o in obs)
    meta = world.meta["metar"]
    assert all(m["real"] for m in meta.values()) and world.meta["metar_synthetic"] == []
    for k in ("LPPT@2025-01-24", "LIRF@2025-01-24", "EDDM@2025-01-24", "KBOS@2025-01-24"):
        assert world.metar[k] and all(o.station == k.split("@")[0] for o in world.metar[k])
        assert not any(is_storm(o) for o in world.metar[k]), f"{k} is calm all day"


# ---------------------------------------------------------------- Herminia mini-day (plan §1.4 Q1 payoff)
def test_herminia_31_eu_departures_and_one_bos_dub(world: World, flights):
    ap = {a.iata: a for a in world.airports}
    inlieu = [e for e in world.crm if e.kind == "voucher_in_lieu_of_compensation" and e.coupon_id != NS31 + ":14C"]
    assert len(inlieu) == 32 and all(e.signed_acceptance_sha256 is None for e in inlieu)
    by_flight = Counter(e.coupon_id.rsplit(":", 1)[0] for e in inlieu)
    eu = sum(n for fid, n in by_flight.items() if ap[flights[fid].origin].eu)
    non_eu = [fid for fid in by_flight if not ap[flights[fid].origin].eu]
    assert eu == 31 and len(non_eu) == 1
    assert (flights[non_eu[0]].origin, flights[non_eu[0]].dest) == ("BOS", "DUB")
    h = world.meta["herminia"]
    assert len(h["in_lieu_unsigned_eu_departures"]) == 31 and len(h["in_lieu_unsigned_non_eu"]) == 1
    win = ref_windows(world.metar[HERMINIA])
    assert win and (win[0][0], win[-1][1]) == (t("2025-01-26T11:30:00Z"), t("2025-01-26T13:00:00Z"))
    for fid in by_flight:
        f = flights[fid]
        assert f.status == "cancelled"
        assert not any(a <= f.sched_dep <= b or a <= f.sched_arr <= b for a, b in win), fid
        aog = [e for e in world.tech_log if e.aircraft == f.aircraft and e.aog and e.logged_at < f.sched_dep]
        assert aog and aog[0].mel_relief is False, fid


# ---------------------------------------------------------------- Isha, history, context, curves
def test_isha_opening_balance(world: World):
    (ob,) = world.opening_balances
    assert (ob.cohort, ob.account, ob.entitlement_cents, ob.balance_cents) == (ISHA, "2140", 6_000_000, 360_000)
    assert ob.claimed_cents == 6_000_000 * 29 // 100 and ob.curve_segment == "long_haul_gt3500"
    assert ob.balance_cents == (35 - 29) * 6_000_000 // 100


def test_history_cases_41_of_42(world: World):
    rr = [h for h in world.history_cases if h.kind == "reroute_reduction"]
    assert len(world.history_cases) >= 42 and len(rr) == 42
    assert Counter(h.decision for h in rr) == {"apply_7_2_reduction": 41, "no_reduction": 1}
    assert all(h.at < t("2025-01-01T00:00:00Z") for h in world.history_cases), "learn split only"
    assert not any(h.kind in ("knock_on", "voucher_in_lieu") for h in world.history_cases), "Q1/Q2 have no precedent"


def test_real_context(world: World):
    rc = world.real_context[EOWYN]
    assert (rc["eurocontrol_departures"], rc["reported_cancellations_dep"], rc["red_warning"]) == (179, 119,
                                                                                                    "06:00-11:00")


def test_distances_match_plan_table(world: World):
    plan = {"BOS": 4804, "JFK": 5103, "ORD": 5896, "YYZ": 5261, "CDG": 786, "FRA": 1086, "BCN": 1486, "MAD": 1452,
            "LIS": 1643, "FCO": 1886, "ATH": 2876, "MUC": 1381, "AMS": 750, "LHR": 449}
    d = world.meta["distances_km"]
    assert {k: d[f"DUB-{k}"] for k in plan} == plan
    assert 1500 - d["DUB-BCN"] == 14


def test_curves_json():
    doc = json.loads((GOLDEN / "curves.json").read_text())
    curves = {c["segment"]: ClaimCurve.model_validate(c) for c in doc["curves"]}
    lh = curves["long_haul_gt3500"]
    assert lh.version == "LH-v1" and lh.points == [(1, 0.09), (3, 0.17), (6, 0.24), (12, 0.29), (18, 0.32)]
    assert (lh.ultimate, curves["medium_1500_3500"].ultimate, curves["short_le1500"].ultimate) == (0.35, 0.27, 0.20)
    assert lh.observed_through_month == 18 and len(lh.n_by_point) == len(lh.points)
