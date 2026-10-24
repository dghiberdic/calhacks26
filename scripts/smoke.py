#!/usr/bin/env python3
"""D11 checkpoint smoke tests (IMPLEMENTATION_PLAN §7) against a running server (or any httpx-like client).

    uv run python scripts/smoke.py cp1 --base http://127.0.0.1:8000
    scripts/smoke_cp1.sh        # starts a server on a temp DB in the background, runs this, stops it

CP1: golden decisions (NS31 technical 71 → 41; 13 + 6 + 4 weather; 3 knock-ons needs_legal) and Books' numbers
     (NS31 3,465,000; storm 8,214,600) from the real server.
CP2: desk (new airport/date, 422s), inject → SSE event within 20 s, Q1 → R-CL-1 → Herminia settles 31 and the
     BOS→DUB case asks, blame reaches a METAR row, Reader/Drafter wired.
CP3: offline mode, 8 rehearsed injections + 20 fuzz inputs never 500, eval report, recorded build, make verify.

Each check prints OK/FAIL with a one-line detail; exit 1 if any check fails.
"""
from __future__ import annotations

import argparse
import json
import random
import subprocess
import sys
import time
from collections import Counter
from collections.abc import Callable
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from contracts.models import (  # noqa: E402
    Blame, ErrorEnvelope, EvalReport, FlightFile, InjectResponse, Injection, StormRun, TraceEvent,
)

EOWYN, HERMINIA = "EIDW@2025-01-24", "EIDW@2025-01-26"
NS31 = "NS31@2025-01-24"
GOLDEN = ROOT / "contracts" / "fixtures" / "golden"


class Check:
    def __init__(self) -> None:
        self.results: list[tuple[str, bool, str]] = []

    def __call__(self, name: str, ok: bool, detail: str = "") -> bool:
        self.results.append((name, bool(ok), detail))
        print(f"{'OK  ' if ok else 'FAIL'} {name}" + (f" · {detail}" if detail else ""), flush=True)
        return bool(ok)

    def guard(self, name: str, fn: Callable[[], tuple[bool, str]]) -> bool:
        try:
            ok, detail = fn()
        except Exception as e:  # noqa: BLE001  (a smoke test reports, it doesn't crash)
            ok, detail = False, f"{type(e).__name__}: {e}"[:300]
        return self(name, ok, detail)

    @property
    def ok(self) -> bool:
        return all(r[1] for r in self.results)


def golden_meta() -> dict[str, Any]:
    return json.loads((GOLDEN / "world.json").read_text(encoding="utf-8"))["meta"]


def expected_rulings() -> dict[str, Any]:
    return json.loads((GOLDEN / "expected" / "questions.json").read_text(encoding="utf-8"))["rulings"]


def coupon_settled_by(client, coupon_id: str, rule_id: str | None) -> bool:
    """Blame the coupon: its entitlement is owed (no longer needs a ruling) and the chain cites ``rule_id``."""
    if not rule_id:
        return False
    r = client.get("/api/blame", params={"target": coupon_id})
    if r.status_code != 200:
        return False
    b = Blame.model_validate(r.json())
    if not b.steps or not b.steps[0].label.startswith(f"Entitlement {coupon_id}") or " · owed" not in \
            b.steps[0].label:
        return False
    return any(s.commit.payload_ref.split("@")[0] == rule_id for s in b.steps)


def storm(client, sid: str = EOWYN) -> StormRun:
    r = client.get(f"/api/storms/{sid}")
    r.raise_for_status()
    return StormRun.model_validate(r.json())


# ---------------------------------------------------------------- CP1
def cp1(client, c: Check) -> None:
    c.guard("health", lambda: (client.get("/api/health").status_code == 200, client.get("/api/health").text[:160]))
    c.guard("storms lists Éowyn", lambda: (any(s["id"] == EOWYN for s in client.get("/api/storms").json()), ""))
    run = storm(client)
    meta = golden_meta()
    dec = {r.flight.id: r.decision for r in run.flights if r.decision}
    d31 = dec.get(NS31)
    c("NS31 technical, recoded 71 → 41", d31 is not None and d31.cause.value == "technical" and d31.recoded
      and d31.recode_label == "71 → 41", f"{d31.cause.value if d31 else None} {d31.recode_label if d31 else ''}")
    groups = meta["groups"]
    for g, n in (("outbound_weather", 13), ("return_weather", 6), ("overnight_inbound", 4)):
        got = sum(1 for f in groups[g] if dec.get(f) and dec[f].cause.value == "weather"
                  and dec[f].extraordinary.value == "extraordinary")
        c(f"{n} {g.replace('_', ' ')} flights are weather", got == n, f"{got}/{n}")
    ko = [dec.get(f) for f in groups["knock_on"]]
    c("3 knock-on returns needs_legal → Legal", all(d and d.cause.value == "knock_on" and d.extraordinary.value ==
                                                    "needs_legal" and d.routed_to and d.routed_to.value == "legal"
                                                    for d in ko), str([d.routed_to.value if d and d.routed_to else None
                                                                       for d in ko]))
    c("5,292 passengers · 27 cancelled · 11 operated",
      (run.counters.get("passengers"), run.counters.get("cancelled"), run.counters.get("operated")) == (5292, 27, 11),
      str({k: run.counters.get(k) for k in ("passengers", "cancelled", "operated")}))
    c("storm day-1 liability 8,214,600", run.liability_drafted_cents == 8_214_600, str(run.liability_drafted_cents))

    def ns31_je() -> tuple[bool, str]:
        ff = FlightFile.model_validate(client.get(f"/api/flights/{NS31}").json())
        cr = [sum(x.cr_cents for x in je.lines if x.account == "2140") for je in ff.journal_preview
              if je.kind == "compensation_estimate"]
        return 3_465_000 in cr, f"Cr 2140 {cr}"
    c.guard("NS31 Books draft Dr 4090 / Cr 2140 3,465,000", ns31_je)
    c.guard("3 questions · 3 people", lambda: (len(run.questions) == 3 and len({q.routed_to for q in run.questions})
                                               == 3, str([(q.id, q.routed_to.value) for q in run.questions])))
    impl = client.get("/api/health").json().get("impl", {})
    c("served by the real pipeline (not the stub)", impl.get("pipeline", "golden") != "stub" and
      impl.get("engine") != "stub", json.dumps(impl)[:200])


# ---------------------------------------------------------------- CP2
def session(client, role: str, name: str) -> dict[str, str]:
    r = client.post("/api/session", json={"role": role, "name": name})
    r.raise_for_status()
    return {"Authorization": f"Bearer {r.json()['token']}"}


def first_sse_event(client, last_id: int, timeout_s: float) -> TraceEvent | None:
    """Read /api/stream from Last-Event-ID until the first `trace` event (or timeout)."""
    deadline = time.monotonic() + timeout_s
    with client.stream("GET", "/api/stream", headers={"Last-Event-ID": str(last_id)}, timeout=timeout_s) as r:
        data: list[str] = []
        for line in r.iter_lines():
            if time.monotonic() > deadline:
                return None
            if line.startswith("data:"):
                data.append(line[5:].strip())
            elif line == "" and data:
                return TraceEvent.model_validate_json("\n".join(data))
    return None


def cp2(client, c: Check) -> None:
    def desk_new() -> tuple[bool, str]:
        t0 = time.monotonic()
        r = client.post("/api/desk", json={"icao": "EGLL", "date": "2024-01-21"}, timeout=30)
        dt = time.monotonic() - t0
        if r.status_code != 200:
            return False, f"{r.status_code} in {dt:.1f}s"
        run = StormRun.model_validate(r.json())
        # a real desk run (not the stub's empty one): Northstar DUB<->LHR flights on Storm Isha's real window
        ok = bool(run.flights) and bool(run.windows) and dt < 5
        return ok, f"{len(run.flights)} flights · {len(run.windows)} windows · {dt:.1f}s · {run.message or ''}"
    c.guard("desk EGLL 2024-01-21 runs a real day within 5 s", desk_new)

    def desk_422() -> tuple[bool, str]:
        fut = (date.today() + timedelta(days=30)).isoformat()
        a = client.post("/api/desk", json={"icao": "EIDW", "date": fut})
        b = client.post("/api/desk", json={"icao": "ZZZZ", "date": "2025-01-24"})
        ok = all(x.status_code == 422 and ErrorEnvelope.model_validate(x.json()) for x in (a, b))
        return ok, f"future {a.status_code} {a.json().get('error', {}).get('code')} · unknown {b.status_code} " \
                   f"{b.json().get('error', {}).get('code')}"
    c.guard("desk: future date / unknown ICAO → 422 with a plain message", desk_422)

    def inject_sse() -> tuple[bool, str]:
        last = max([e["seq"] for e in client.get("/api/trace").json()] or [0])
        inj = next(Injection.model_validate(x) for x in client.get("/api/injections").json()
                   if x["id"] == "01_aog_inside_window")
        commits_before = {x["hash"] for x in client.get("/api/commits", params={"limit": 1000}).json()}
        t0 = time.monotonic()
        r = client.post("/api/inject", json=inj.request.model_dump(mode="json"), timeout=30)
        resp = InjectResponse.model_validate(r.json())
        ev = first_sse_event(client, last, 20)
        dt = time.monotonic() - t0
        kinds = Counter(e.kind for e in resp.events)
        new = [x for x in client.get("/api/commits", params={"limit": 1000}).json() if x["hash"] not in commits_before]
        new_kinds = Counter(x["kind"] for x in new)
        return (r.status_code == 200 and resp.facts and ev is not None and ev.seq > last and dt < 20
                and "decision" in kinds and "decision" in new_kinds), \
            f"{len(resp.facts)} facts · events {dict(kinds)} · new commits {dict(new_kinds)} · " \
            f"SSE seq {ev.seq if ev else None} · {dt:.1f}s"
    c.guard("inject a tech-log line → fact → decision → commit, streamed within 20 s", inject_sse)

    def q1_herminia() -> tuple[bool, str]:
        want = expected_rulings()["Q1"]                    # expected/questions.json: R-CL-1@1 settles 31 coupons
        want_rule, want_version = want["rule"].split("@")
        cl = session(client, "claims_lead", "Maria")
        q1 = next(q for q in client.get("/api/questions", headers=cl).json() if q["id"] == "Q-1")
        r = client.post("/api/questions/Q-1/answer", headers=cl,
                        json={"decision": q1["recommended_option"], "explanation": q1["recommends"]})
        if r.status_code != 200:
            return False, f"answer {r.status_code} {r.text[:120]}"
        rule = (r.json().get("proposal") or {}).get("rule", {}).get("id")
        if rule != want_rule:
            return False, f"the ruling proposed {rule!r}, expected {want_rule}"
        rc = client.post(f"/api/proposals/{rule}/confirm", headers=cl)
        if rc.status_code != 200:
            return False, f"confirm {rule} → {rc.status_code}"
        client.post("/api/clock", json={"known_at": "2025-01-27T06:00:00Z"})
        h = storm(client, HERMINIA)
        meta = golden_meta()["herminia"]
        asks = [q for q in h.questions if q.pattern == want["herminia_asks_again"]["pattern"]]
        for fid in sorted({cid.split(":")[0] for cid in want["herminia_settled"]}):
            ff = FlightFile.model_validate(client.get(f"/api/flights/{fid}").json())
            if ff.entitlements_summary.get("needs_ruling") or \
                    ff.entitlements_summary.get("status_counts", {}).get("needs_ruling"):
                return False, f"{fid} still has needs_ruling coupons"
        # every one of the 31 coupons, not a sample: owed, and its blame chain cites the rule
        settled = [cid for cid in want["herminia_settled"] if coupon_settled_by(client, cid, rule)]
        missing = sorted(set(want["herminia_settled"]) - set(settled))
        cited = next((x.get("times_cited") for x in client.get("/api/rules").json()
                      if x.get("id") == rule and x.get("version") == int(want_version)), None)
        ok = (len(want["herminia_settled"]) == 31 and not missing
              and cited == want["times_cited_after_herminia"]
              and bool(asks) and asks[0].case_refs == meta["in_lieu_unsigned_non_eu"]
              == want["herminia_asks_again"]["case_refs"])
        return ok, (f"rule {rule} · settled {len(settled)}/31" + (f" (missing {missing[:3]}…)" if missing else "")
                    + f" · {want['rule']} times_cited {cited} (want {want['times_cited_after_herminia']}) · "
                    f"Herminia asks {asks[0].case_refs if asks else None}")
    c.guard("Q1 → R-CL-1 → Herminia settles 31, the BOS→DUB case asks again", q1_herminia)

    def blame() -> tuple[bool, str]:
        ff = FlightFile.model_validate(client.get(f"/api/flights/{NS31}").json())
        je = next(j for j in ff.journal_preview if j.kind == "compensation_estimate")
        line = next(i for i, x in enumerate(je.lines, 1) if x.account == "2140")
        r = client.get("/api/blame", params={"target": f"{je.id}:{line}"})
        b = Blame.model_validate(r.json())
        metar = [s for s in b.steps if (s.quote or "").startswith(("EIDW ", "METAR EIDW")) or
                 "METAR" in s.commit.payload_ref]
        return bool(metar), f"{len(b.steps)} steps · METAR step: {metar[0].quote[:40] if metar else None}"
    c.guard("blame reaches the METAR row", blame)

    impl = client.get("/api/health").json().get("impl", {})
    c("real Reader and Drafter wired", impl.get("reader") == "real" and impl.get("drafter") == "real",
      json.dumps({k: impl.get(k) for k in ("reader", "drafter")}))


# ---------------------------------------------------------------- CP3
FUZZ_KINDS = ["tech_log", "claim", "crm", "email", "occ_log", "manufacturer"]
STUB_ECHO = "stub · expected outcome"           # contracts/stub_app.py echoes the fixture; that proves nothing
DECISION_KEYS = ("cause", "extraordinary", "recoded", "recode_label", "outcome", "routed_to")


def _decision(client, fid: str) -> dict[str, Any] | None:
    r = client.get(f"/api/flights/{fid}")
    if r.status_code != 200:
        return None
    d = FlightFile.model_validate(r.json()).decision.model_dump(mode="json")
    return {k: d.get(k) for k in DECISION_KEYS}


def _journal_statuses(client, fid: str) -> dict[str, str]:
    r = client.get(f"/api/flights/{fid}")
    if r.status_code != 200:
        return {}
    return {je.id: je.status for je in FlightFile.model_validate(r.json()).journal_preview}


def _said(resp: InjectResponse) -> str:
    return " ".join([resp.message or "", *(e.summary for e in resp.events)]).lower()


def _unchanged(before: dict | None, after: dict | None) -> tuple[bool, str]:
    return before is not None and before == after, f"decision {'unchanged' if before == after else after}"


# One machine check per rehearsed fixture, each clause traced to the fixture's `expected` sentence. A fixture with
# no entry fails: a new rehearsal needs a check, not just an HTTP 200.
#   watch: the flight whose decision is snapshotted before the injection
INJECTION_CHECKS: dict[str, dict[str, Any]] = {
    "01_aog_inside_window": {   # NS110 → concurrent / needs_legal · routed to Legal (concurrent causes)
        "watch": "NS110@2025-01-24",
        "check": lambda resp, before, after, said: (
            bool(after) and after["cause"] == "concurrent" and after["extraordinary"] == "needs_legal"
            and after["routed_to"] == "legal", f"NS110 {after}"),
    },
    "02_duplicate_direct_plus_agency": {   # Duplicate of the direct claim for 9B · pay once · agency claim held
        "watch": NS31,
        "check": lambda resp, before, after, said: (
            "duplicate" in said and ("held" in said or any(e.chip == "HELD" for e in resp.events)),
            said[:120]),
    },
    "03_prompt_injection_email": {   # 0 facts accepted · external parties never satisfy an internal approval
        "watch": NS31,
        "check": lambda resp, before, after, said: (
            not resp.facts and before == after, f"{len(resp.facts)} facts · decision "
                                                 f"{'unchanged' if before == after else 'CHANGED'}"),
        "no_approval": True,
    },
    "04_chargeback_after_bot_refund": {   # Refund already initiated 24 Jan · chargeback flagged as duplicate · CL
        "watch": NS31,
        "check": lambda resp, before, after, said: (
            "duplicate" in said and ("claims lead" in said or "claims_lead" in said), said[:120]),
    },
    "05_airbus_hidden_defect_notice": {   # New legal pattern (C-549/07 ¶26) · routed to Legal · decision unchanged
        "watch": NS31,
        "check": lambda resp, before, after, said: (
            _unchanged(before, after)[0] and "legal" in said, f"{_unchanged(before, after)[1]} · {said[:80]}"),
    },
    "06_claim_after_limitation": {   # After limitation (Ireland 6 years, C-139/11) · no compensation
        "watch": None,
        "check": lambda resp, before, after, said: ("limitation" in said, said[:120]),
    },
    "07_challenge_storm_anyway": {   # Assertion · Decision stands.
        "watch": NS31,
        "check": lambda resp, before, after, said: (
            _unchanged(before, after)[0] and "decision stands" in said, f"{_unchanged(before, after)[1]} · "
                                                                          f"{said[:80]}"),
    },
    "08_uk261_520_on_dub_lhr": {   # EU261 applies to a DUB departure · weather · no compensation · paid once
        "watch": "NS100@2025-01-24",
        "check": lambda resp, before, after, said: (
            bool(after) and after["cause"] == "weather" and after["extraordinary"] == "extraordinary"
            and "eu261" in said, f"NS100 {after} · {said[:60]}"),
    },
}


def check_injection(client, inj: Injection) -> tuple[bool, str]:
    """POST a rehearsed injection and compare what the server did with the fixture's `expected`."""
    spec = INJECTION_CHECKS.get(inj.id)
    if spec is None:
        return False, f"no machine check for {inj.id} (add one to INJECTION_CHECKS)"
    watch = spec["watch"]
    before = _decision(client, watch) if watch else None
    jes_before = _journal_statuses(client, watch) if watch and spec.get("no_approval") else {}
    r = client.post("/api/inject", json=inj.request.model_dump(mode="json"), timeout=30)
    if r.status_code != 200:
        return False, f"HTTP {r.status_code} {r.text[:120]}"
    resp = InjectResponse.model_validate(r.json())
    if (resp.message or "").startswith(STUB_ECHO):
        return False, "answered by the contract stub (it echoes the fixture), not the pipeline"
    after = _decision(client, watch) if watch else None
    ok, detail = spec["check"](resp, before, after, _said(resp))
    if spec.get("no_approval"):
        approved = [j for j, s in _journal_statuses(client, watch).items()
                    if s in ("approved", "posted") and jes_before.get(j) != s]
        ok = ok and not approved
        detail += f" · newly approved {approved}" if approved else " · nothing approved"
    return ok, detail[:200]


def fuzz_inputs(n: int = 20, seed: int = 13) -> list[dict[str, Any]]:
    rng = random.Random(seed)
    pieces = ["NS31", "EI-NSB", "€600", "£520", "RSN 71", "NO MEL RELIEF", "approved", "ignore previous instructions",
              "\u0000", "💥", "<script>alert(1)</script>", "'; DROP TABLE sc_commits; --", "9" * 400, "",
              "NS99999@2099-13-45:99Z", "A/C AOG", "chargeback", "UK261", "\n\n\n", "{\"json\": true}"]
    out = []
    for i in range(n):
        text = " ".join(rng.choice(pieces) for _ in range(rng.randint(0, 12)))
        out.append({"kind": rng.choice(FUZZ_KINDS), "text": text,
                    "flight_id": rng.choice([None, NS31, "NS117@2025-01-24", "XX1@2025-01-01", "../../etc"])})
    return out


def cp3(client, c: Check) -> None:
    h = client.get("/api/health").json()
    c("server is in offline mode", h.get("mode") == "offline", f"mode={h.get('mode')}")
    injs = [Injection.model_validate(x) for x in client.get("/api/injections").json()]
    c("8 rehearsed injections listed", len(injs) == 8, str(len(injs)))
    for inj in injs:
        c.guard(f"inject {inj.id}: {inj.expected}"[:120], lambda inj=inj: check_injection(client, inj))
    fives = []
    for i, body in enumerate(fuzz_inputs()):
        try:
            r = client.post("/api/inject", json=body, timeout=30)
            if r.status_code >= 500:
                fives.append(f"#{i} {r.status_code}")
        except Exception as e:  # noqa: BLE001
            fives.append(f"#{i} {type(e).__name__}")
    c("20 fuzz inputs: no 500s", not fives, ", ".join(fives) or "all handled")
    c.guard("eval report validates", lambda: (EvalReport.model_validate(client.get("/api/eval").json()) is not None,
                                              ""))
    proof = ROOT / "eval" / "proof.json"
    c("eval/proof.json is real", proof.is_file() and EvalReport.model_validate_json(proof.read_text()) is not None,
      str(proof.relative_to(ROOT)) + (" present" if proof.is_file() else " missing"))

    def proof_current() -> tuple[bool, str]:
        # F9: exits 1 unless eval/cache/manifest.json matches the tree and proof.json/NUMBERS.md rebuild byte-identical
        p = subprocess.run([sys.executable, "-m", "eval.run", "--check"], capture_output=True, text=True,
                           timeout=600, cwd=ROOT)
        tail = (p.stdout.strip().splitlines() or p.stderr.strip().splitlines() or [""])[-1]
        return p.returncode == 0, f"exit {p.returncode} · {tail}"[:200]
    c.guard("proof is current (eval.run --check)", proof_current)
    rec = ROOT / "demo" / "recorded"
    c("recorded build captured (make record)", rec.is_dir() and any(rec.rglob("*.json")),
      f"{sum(1 for _ in rec.rglob('*.json')) if rec.is_dir() else 0} files under demo/recorded")
    v = subprocess.run([sys.executable, str(ROOT / "scripts" / "verify.py")], capture_output=True, text=True,
                       timeout=600, cwd=ROOT)
    c("make verify is green", v.returncode == 0, (v.stdout.strip().splitlines() or [""])[-1][:200])


CPS = {"cp1": cp1, "cp2": cp2, "cp3": cp3}


def run(cp: str, client) -> Check:
    c = Check()
    print(f"== smoke {cp} · {datetime.now().strftime('%H:%M:%S')}", flush=True)
    try:
        CPS[cp](client, c)
    except Exception as e:  # noqa: BLE001
        c(f"{cp} aborted", False, f"{type(e).__name__}: {e}"[:300])
    n_ok = sum(1 for r in c.results if r[1])
    print(f"== {cp}: {n_ok}/{len(c.results)} checks passed", flush=True)
    return c


def main(argv: list[str]) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("cp", choices=sorted(CPS))
    ap.add_argument("--base", default="http://127.0.0.1:8000")
    args = ap.parse_args(argv)
    import httpx
    with httpx.Client(base_url=args.base, timeout=30) as client:
        return 0 if run(args.cp, client).ok else 1


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
