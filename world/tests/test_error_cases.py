from collections import Counter

from contracts.models import World


def test_stress_corpus_has_five_real_inputs_for_each_error_in_each_split():
    from world.error_cases import build_error_cases

    cases = build_error_cases()
    assert len(cases) == 140
    assert len({c["id"] for c in cases}) == 140
    counts = Counter((c["split"], c["category"]) for c in cases)
    assert len(counts) == 28 and set(counts.values()) == {5}
    for case in cases:
        world = World.model_validate(case["world"])
        assert world.sources and world.flights and world.coupons
        assert world.meta["simulated"] is True
        assert "expected" not in world.meta
        assert all(f.date.year < 2025 for f in world.flights) if case["split"] == "train" else all(
            f.date.year == 2025 for f in world.flights)


def test_stress_labels_are_supported_by_input_events_not_engine_outputs():
    from world.error_cases import build_error_cases

    cases = {c["category"]: c for c in build_error_cases() if c["split"] == "test" and c["variant"] == 0}
    unsigned = cases["unsigned_voucher"]
    assert unsigned["world"]["crm"][0]["signed_acceptance_sha256"] is None
    assert unsigned["expected"]["voucher_offset_cents"] == 0
    duplicate = cases["duplicate_claim"]
    assert len({c["coupon_id"] for c in duplicate["world"]["claims"]}) == 1
    assert duplicate["expected"]["max_discharge_cents"] == 60000
    agency = cases["agency_without_authority"]
    assert agency["world"]["claims"][0]["authority"] == "none"
    assert agency["expected"]["claim_approved"] is False
    expired = cases["claim_after_limitation"]
    assert expired["world"]["claims"][0]["received_at"].startswith("2031-01-25")
    assert expired["expected"]["claim_approved"] is False
    regime = cases["wrong_regime"]
    assert regime["world"]["claims"][0]["currency_regime"] == "UK261"
    assert regime["expected"]["compensation_cents"] == 25000
    assert regime["world"]["flights"][0]["dest"] == "LHR"


def test_knock_on_return_cases_are_out_of_every_window_at_both_ends():
    """A knock-on return's only link to the storm is the cancelled outbound: the return sector is observed and outside
    every storm window at its departure and its arrival end (engine.timeline's own definition), while the outbound
    left inside a Dublin window."""
    from engine.timeline import position, storm_windows
    from world.error_cases import build_error_cases

    cases = [c for c in build_error_cases() if c["category"] == "knock_on_return"]
    assert len(cases) == 10
    for case in cases:
        world = World.model_validate(case["world"])
        flights = {f.id: f for f in world.flights}
        ret = flights[case["flight_id"]]
        root = flights[ret.inbound_flight_id]
        icao = {a.iata: a.icao for a in world.airports}

        def where(t, code, world=world, icao=icao):
            rows = [o for k, obs in world.metar.items() if k.split("@")[0] == icao[code] for o in obs]
            return position(t, rows, storm_windows(rows))

        assert (root.origin, root.dest, ret.origin, ret.dest) == ("DUB", "CDG", "CDG", "DUB")
        assert where(root.sched_dep, "DUB") == "in", case["id"]
        assert where(ret.sched_dep, "CDG") == "out", case["id"]
        assert where(ret.sched_arr, "DUB") == "out", case["id"]
        assert ret.sched_dep >= root.sched_arr and ret.date == ret.sched_dep.date()
        assert case["expected"]["cause"] == "knock_on"
