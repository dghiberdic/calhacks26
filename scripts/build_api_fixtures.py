#!/usr/bin/env python3
"""D0b: regenerate contracts/fixtures/api/*.json (+ fixtures/injections/) from the golden world plus fakes.

Base layer: the D0a plan narrative (scripts/build_stub_fixtures.py: journals, rollforwards, CFO, rules, commits,
access, controls, eval, trace prose). Golden layer, replacing it where the golden world knows better:
- the Storm Run's flights, windows, METAR, airports and counters come from `FakeEngine` on `world.json`
  (real IEM METAR at both ends, evidence quoting the real documents' spans);
- every Flight File's decision, sample entitlements (real coupon ids), counts and timeline (the world's logs);
- the questions keep the plan's wording, with evidence that points at golden facts;
- `storm_EIDW@2025-01-26.json` is Herminia after R-CL-1 (31 settled, BOS→DUB asks again);
- `fixtures/injections/<id>.json` holds the 8 rehearsed scenarios (CONTRACTS §5).

The cause model here is a *display* calibration that reproduces the plan's numbers (NS31 91%, knock-ons 47%);
voucher and release use the shipped default. It is fixture-only and labelled `cal-plan-fixture`.

Usage: uv run python scripts/build_api_fixtures.py [--check]
"""
from __future__ import annotations

import importlib.util
import json
import shutil
import sys
import tempfile
from collections import Counter
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from contracts import calibration as cal  # noqa: E402
from contracts.fakes import FakeDrafter, FakeEngine, golden_world, station_obs, storm_windows  # noqa: E402
from contracts.models import (  # noqa: E402
    Entitlement, Evidence, FlightFile, Role, Ruling, StormRun, StormSummary, TraceEvent, World,
)
from contracts.normalize import world_to_facts  # noqa: E402

UTC = timezone.utc
API = ROOT / "contracts" / "fixtures" / "api"
INJ = ROOT / "contracts" / "fixtures" / "injections"
EOWYN, HERMINIA = "EIDW@2025-01-24", "EIDW@2025-01-26"
DAY, HDAY = date(2025, 1, 24), date(2025, 1, 26)
KNOWN_AT = datetime(2025, 1, 25, 6, 0, tzinfo=UTC)
H_KNOWN_AT = datetime(2025, 1, 27, 6, 0, tzinfo=UTC)

_default = cal.load(cal.DEFAULT_PATH)
PLAN_CAL = {
    "version": "cal-plan-fixture",
    "note": "fixture-only display calibration reproducing the plan's numbers (NS31 91%, knock-ons 47%)",
    "models": {
        "cause": {"features": ["in_window_dep", "in_window_arr", "window_margin_h", "aog_before_window",
                               "aog_inside_window", "root_cause_internal", "sources_disagree", "precedent_count",
                               "knock_on"],
                  "coef": [2.9, 2.9, 0.4, 1.0, -3.5, 1.21, -0.5, 0.1, 0.3], "intercept": -0.8, "n": 0},
        "voucher": _default["models"]["voucher"], "release": _default["models"]["release"],
    },
}


def load_stub():
    spec = importlib.util.spec_from_file_location("build_stub_fixtures", ROOT / "scripts" / "build_stub_fixtures.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def _iso(t: datetime) -> str:
    return t.astimezone(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")


def tl(t: datetime, kind: str, label: str, text: str, source_id: str | None, tier: int | None,
       **extra: Any) -> dict[str, Any]:
    return {"at": _iso(t), "kind": kind, "label": label, "text": text, "source_id": source_id, "trust_tier": tier,
            **extra}


# ---------------------------------------------------------------- golden timeline for a flight file
def timeline(w: World, fid: str) -> list[dict[str, Any]]:
    f = next(x for x in w.flights if x.id == fid)
    src = {s.id: s for s in w.sources}
    out: list[dict[str, Any]] = []
    for e in w.tech_log:
        if e.aircraft == f.aircraft and e.logged_at <= f.sched_dep and e.logged_at >= f.sched_dep - timedelta(days=2):
            out.append(tl(e.logged_at, "tech_log", f"Tech log {e.aircraft}" + (" · AOG" if e.aog else ""), e.text,
                          f"SRC-{e.id}", 1))
    for e in w.ops_log:
        if fid in e.flight_ids or (e.kind == "occ" and f.outbound_pair_id in e.flight_ids):
            label = {"occ": "OCC log", "mcc": "MCC log", "spares": "Spares log"}[e.kind]
            extra = {"scored": False} if e.kind == "spares" and f.number == "NS31" else {}
            out.append(tl(e.at, e.kind, label + (" (context only: not scored for a technical cause)" if extra else ""),
                          e.text, f"SRC-{e.id}", src[f"SRC-{e.id}"].trust_tier, **extra))
    hub = "EIDW"
    obs = station_obs(w, hub)
    wins = [x for x in storm_windows(obs) if x.start.date() <= f.sched_dep.date() + timedelta(days=1)]
    main = max(wins, key=lambda x: x.end - x.start) if wins else None
    metar_src = next((k for k in w.metar if k.startswith(hub + "@") and any(o.valid == f.sched_dep or
                                                                             o.valid.date() == f.sched_dep.date()
                                                                             for o in w.metar[k])), None)
    if main is not None:
        so = next(o for o in obs if o.valid == main.start)
        eo = next(o for o in obs if o.valid == main.end)
        out.append(tl(main.start, "window_start", "Storm window opens", so.raw, f"SRC-METAR-{metar_src}", 1))
        out.append(tl(main.end, "window_end", "Storm window closes", eo.raw, f"SRC-METAR-{metar_src}", 1))
    icao = {a.iata: a.icao for a in w.airports}
    for end, t, ap in (("STD", f.sched_dep, f.origin), ("STA", f.sched_arr, f.dest)):
        so = station_obs(w, icao.get(ap, ap))
        near = [o for o in so if abs(o.valid - t) <= timedelta(minutes=60)]
        if near:
            o = min(near, key=lambda o: (abs(o.valid - t), o.valid))
            key = next(k for k in w.metar if k.startswith(o.station + "@") and o in w.metar[k])
            wind = f"{o.sknt} kt" + (f", gust {o.gust} kt" if o.gust else ", no gust")
            out.append(tl(o.valid, "metar", f"Weather at {end} ({ap}): {wind}", o.raw, f"SRC-METAR-{key}", 1))
    crm = [e for e in w.crm if e.coupon_id.startswith(fid + ":")]
    bot = sorted((e for e in crm if e.kind == "refund_initiated"), key=lambda e: e.at)
    if bot:
        out.append(tl(bot[0].at, "crm", f"CRM bot: {len(bot)} refunds initiated {bot[0].at:%H:%M}–{bot[-1].at:%H:%M}Z "
                                        "· 'weather, no compensation' emails", bot[0].text, f"SRC-{bot[0].id}", 3))
    for e in crm:
        if e.kind in ("voucher_in_lieu_of_compensation", "bsp_refund", "chargeback"):
            label = {"voucher_in_lieu_of_compensation": f"Service desk: voucher in lieu of compensation to "
                                                        f"{e.coupon_id.rsplit(':', 1)[1]} · unsigned",
                     "bsp_refund": f"BSP refund on {e.coupon_id.rsplit(':', 1)[1]} · duplicate of the bot's refund",
                     "chargeback": f"Chargeback on {e.coupon_id.rsplit(':', 1)[1]} after the bot's refund"}[e.kind]
            out.append(tl(e.at, "crm", label, e.text, f"SRC-{e.id}", src[f"SRC-{e.id}"].trust_tier))
    if f.number == "NS31":
        ops = [x for x in w.flights if x.id in (w.meta["groups"]["operated"])]
        out.append(tl(min(x.sched_dep for x in ops), "operated", f"{len(ops)} Northstar departures operated "
                                                                   "15:30–17:30Z",
                      ", ".join(f"{x.number} {x.dest}" for x in sorted(ops, key=lambda x: x.sched_dep)),
                      f"SRC-SCHEDULE-{EOWYN}", 2))
    for end, t, ap in (("STD", f.sched_dep, f.origin), ("STA", f.sched_arr, f.dest)):
        out.append(tl(t, "schedule", f"{f.number} {end} {t:%H:%M}Z {ap}", "Cancelled", f"SRC-SCHEDULE-{EOWYN}" if
                      f.date <= DAY else f"SRC-SCHEDULE-{HERMINIA}", 2))
    return sorted(out, key=lambda x: (x["at"], x["kind"]))


def summary(stub_summary: dict[str, Any], ents: list[Entitlement], w: World, fid: str) -> dict[str, Any]:
    el = {e.coupon_id: e.kind for e in w.elections}
    s = dict(stub_summary)
    s.update({
        "coupons": len(ents),
        "status_counts": dict(sorted(Counter(e.status for e in ents).items())),
        "elections": dict(sorted(Counter(el[e.coupon_id] for e in ents).items())),
        "refunds_already_initiated": sum(e.refund_already_initiated for e in ents),
        "refund_due_cents": sum(e.refund_due_cents for e in ents),
        "claims_received": sum(1 for c in w.claims if c.coupon_id.startswith(fid + ":") and c.received_at <= KNOWN_AT),
        "care_due": all(e.care_due for e in ents),
    })
    if any(e.compensation_cents for e in ents if e.status in ("owed", "needs_ruling")):
        s["compensation_cents"] = sum(e.compensation_cents for e in ents if e.status in ("owed", "needs_ruling"))
    return s


def samples(ents: list[Entitlement], w: World, fid: str, stub_samples: list[Entitlement]) -> list[Entitlement]:
    by = {e.coupon_id: e for e in ents}
    picked = [by[s.coupon_id] for s in stub_samples if s.coupon_id in by]
    if len(picked) < 2:
        el = {e.coupon_id: e.kind for e in w.elections}
        for kind in ("refund", "reaccommodated_own", "reroute_partner"):
            e = next((x for x in ents if el[x.coupon_id] == kind and x not in picked), None)
            if e is not None:
                picked.append(e)
    return picked[:5]


# ---------------------------------------------------------------- questions: plan wording, golden evidence
def questions(stub, run: StormRun, w: World) -> list:
    facts = world_to_facts(w, flight_ids=["NS31@2025-01-24"], include_metar=False) + [
        f for f in world_to_facts(w, include_metar=False) if f.subject.startswith("cohort:")]
    src = {s.id: s for s in w.sources}

    def ev(subject_prefix: str, field: str, role: str) -> Evidence | None:
        f = next((x for x in facts if x.subject.startswith(subject_prefix) and x.field == field), None)
        if f is None:
            return None
        return Evidence(fact_id=f.id, source_id=f.source_id, field=f.field, value=f.value, quote=f.span, role=role,
                        trust_tier=src[f.source_id].trust_tier)
    claim14 = next(c for c in w.claims if c.coupon_id.endswith(":14C"))
    run_q = {q.id: q for q in run.questions}
    out = []
    for q in stub.QUESTIONS:
        rq = run_q.get(q.id)
        if q.id == "Q-1":
            evidence = [ev("coupon:NS31@2025-01-24:14C", "voucher.in_lieu", "context"),
                        ev("coupon:NS31@2025-01-24:14C", "voucher.accepted", "contradicts"),
                        ev("coupon:NS31@2025-01-24:14C", "voucher.signed", "supports"),
                        ev(f"claim:{claim14.id}", "claim.voucher_disputed", "supports"),
                        ev("coupon:NS31@2025-01-24:14C", "voucher.amount_cents", "context")]
        elif q.id == "Q-2":
            evidence = [e for r in run.flights if r.decision and r.decision.cause.value == "knock_on"
                        for e in r.decision.evidence if e.field in ("spare.available_within_h", "metar.gust_kt",
                                                                     "pax.reroute_earliest_offered")]
        else:
            evidence = [ev("cohort:", "cohort.balance_cents", "supports"), ev("cohort:", "cohort.claimed_pct", "context"),
                        ev("cohort:", "cohort.last_claim_at", "supports")]
        upd: dict[str, Any] = {"evidence": [e for e in evidence if e is not None]}
        if rq is not None:
            upd.update(case_refs=rq.case_refs, holds=rq.holds, holds_cents=rq.holds_cents, confidence=rq.confidence)
        out.append(q.model_copy(update=upd))
    return out


def herminia(eng: FakeEngine, w: World, stub, q1) -> StormRun:
    r = Ruling(id="RUL-Q-1", question_id="Q-1", author_role=Role.CLAIMS_LEAD, author="claims_lead:maria",
               kind="answer", decision=q1.recommended_option, explanation=q1.recommends,
               at=KNOWN_AT + timedelta(hours=4))
    rcl = FakeDrafter().propose_rule(r, q1, []).model_copy(update={"status": "active"})
    run = display(eng.run_storm(w, "EIDW", HDAY, [*stub.RULES, rcl], H_KNOWN_AT))
    settled = len(w.meta["herminia"]["in_lieu_unsigned_eu_departures"])
    asks = next(q for q in run.questions if q.pattern == "voucher_in_lieu_unsigned")
    feed = list(run.feed) + [
        TraceEvent(seq=len(run.feed) + 1, at=H_KNOWN_AT + timedelta(seconds=40), kind="rule", actor="agent.engine",
                   summary=f"R-CL-1@1 cited {settled}× · {settled} voucher cases settled, ruling cited", ref="R-CL-1@1",
                   chip="CITED"),
        TraceEvent(seq=len(run.feed) + 2, at=H_KNOWN_AT + timedelta(seconds=42), kind="question",
                   actor="agent.engine", summary=f"Asked Claims Lead again: {asks.case_refs[0]} departs BOS (not the "
                                                 "EU) · outside R-CL-1's scope", ref=asks.id, chip="ASKED"),
    ]
    counters = dict(run.counters, settled_by_rule=settled, rules_cited=run.counters["rules_cited"])
    return run.model_copy(update={"feed": feed, "counters": counters, "learned": stub.LEARNED,
                                  "real_context": w.real_context.get(HERMINIA, {})})


def display(run: StormRun) -> StormRun:
    """Fixture display: confidence scores rounded to whole percents (the plan's 91% / 47% / 39% / 72%)."""
    def rc(c):
        return c.model_copy(update={"score": None if c.score is None else round(c.score, 2)})
    rows = [r.model_copy(update={"decision": r.decision.model_copy(update={"confidence": rc(r.decision.confidence)})})
            if r.decision else r for r in run.flights]
    qs = [q.model_copy(update={"confidence": rc(q.confidence)}) for q in run.questions]
    return run.model_copy(update={"flights": rows, "questions": qs})


def build(out_dir: Path, inj_dir: Path) -> None:
    stub = load_stub()
    stub.OUT = out_dir
    stub.main()
    w = golden_world()
    eng = FakeEngine(w, calibration=PLAN_CAL)
    run = display(eng.run_storm(w, "EIDW", DAY, stub.RULES, KNOWN_AT))
    qs = questions(stub, run, w)
    counters = {**stub.COUNTERS, **run.counters}
    storm = run.model_copy(update={"feed": stub.TRACE, "learned": stub.LEARNED, "questions": qs,
                                   "counters": counters})
    stub.dump(f"storm_{EOWYN}.json", storm)
    stub.dump("questions.json", qs)
    stub.dump("storms.json", [StormSummary(id=EOWYN, station="EIDW", date=DAY, cancelled=counters["cancelled"],
                                           questions=len(qs), liability_drafted_cents=storm.liability_drafted_cents)])
    for old in out_dir.glob("flight_*.json"):
        old.unlink()
    for row in run.flights:
        d = row.decision
        if d is None:
            continue
        ents = eng.entitlements(d, w, stub.RULES)
        base = stub.FLIGHT_FILES[d.flight_id]
        handoff = None
        if d.flight_id == "NS31@2025-01-24":
            bot = sum(1 for e in w.crm if e.kind == "refund_initiated" and e.coupon_id.startswith(d.flight_id + ":"))
            handoff = {**(base.handoff or {}), "refunds_already_initiated": bot, "rights_notices_drafted": bot,
                       "bsp_duplicates_flagged": sum(1 for e in w.crm if e.kind == "bsp_refund"),
                       "chargebacks_flagged": sum(1 for e in w.crm if e.kind == "chargeback")}
        ff = FlightFile(flight=row.flight, decision=d,
                        entitlements_summary=summary(base.entitlements_summary, ents, w, d.flight_id),
                        sample_entitlements=samples(ents, w, d.flight_id, base.sample_entitlements),
                        journal_preview=base.journal_preview, timeline=timeline(w, d.flight_id), handoff=handoff,
                        explanation=base.explanation)
        stub.dump(f"flight_{d.flight_id}.json", ff)
    stub.dump(f"storm_{HERMINIA}.json", herminia(eng, w, stub, next(q for q in qs if q.id == "Q-1")))
    inj_dir.mkdir(parents=True, exist_ok=True)
    for old in inj_dir.glob("*.json"):
        old.unlink()
    for inj in stub.INJECTIONS:
        (inj_dir / f"{inj.id}.json").write_text(json.dumps(inj.model_dump(mode="json"), indent=2,
                                                           ensure_ascii=False) + "\n")


def main(argv: list[str]) -> int:
    if "--check" in argv:
        with tempfile.TemporaryDirectory() as tmp:
            a, i = Path(tmp) / "api", Path(tmp) / "injections"
            a.mkdir()
            build(a, i)
            stale = []
            for d_new, d_old in ((a, API), (i, INJ)):
                new = {p.name: p.read_bytes() for p in d_new.glob("*.json")}
                old = {p.name: p.read_bytes() for p in d_old.glob("*.json")} if d_old.exists() else {}
                stale += [f"{d_old.name}/{n}" for n in sorted(set(new) | set(old)) if new.get(n) != old.get(n)]
            for s in stale:
                print(f"stale: contracts/fixtures/{s}")
            return 1 if stale else 0
    build(API, INJ)
    print(f"wrote {len(list(API.glob('*.json')))} api fixtures + {len(list(INJ.glob('*.json')))} injections")
    return 0


if __name__ == "__main__":
    _ = shutil  # keep import for callers that copy fixture dirs
    raise SystemExit(main(sys.argv[1:]))
