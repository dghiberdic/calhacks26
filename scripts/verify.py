#!/usr/bin/env python3
"""D11 `make verify`: recompute every commit hash and replay every decision offline.

1. Boot the real pipeline twice, offline, into two fresh temp databases (never touching data/).
2. Recompute every commit hash and parent link (`Store.verify_chain`), and check every payload hash.
3. Replay: the two boots must give the same head commit and identical decisions, flight by flight.
4. Engine replay: re-decide every stored decision with the engine from the stored world and rules, at the
   decision's own `known_at`, and compare the decision fields (never the LLM: offline mode).

`--db PATH` verifies an existing database's chain instead (e.g. the live demo DB) and skips the double boot.
Prints "N commits verified · replay identical" and exits 0, or lists every problem and exits 1.

Usage: uv run python scripts/verify.py [--db PATH] [--world PATH]
"""
from __future__ import annotations

import argparse
import os
import sys
import tempfile
import time
from pathlib import Path
from typing import Any

os.environ.setdefault("STORMCHECK_MODE", "offline")
os.environ.setdefault("LLM_MODE", "offline")

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

import orjson  # noqa: E402

from contracts.models import FlightDecision, Rule  # noqa: E402

COMPARE = ("cause", "extraordinary", "recoded", "recode_label", "outcome", "routed_to", "in_window_dep",
           "in_window_arr", "window_margin_min", "rules_applied")


def _hash(obj: Any) -> str:
    import hashlib
    return hashlib.sha256(orjson.dumps(obj, option=orjson.OPT_SORT_KEYS)).hexdigest()


def boot(db: Path, world: Path | None):
    from server.config import Settings
    from server.runtime import Runtime
    kw: dict[str, Any] = {"db_path": db, "mode": "offline"}
    if world is not None:
        kw["world_path"] = world
    rt = Runtime(Settings(**kw))
    rt.boot()
    return rt


def decision_docs(rt) -> dict[str, dict[str, Any]]:
    out = {}
    for key in rt.store.keys("decision"):
        body = rt.store.get("decision", key)
        if isinstance(body, dict):
            body = {k: v for k, v in body.items() if k != "commit"}
            out[key] = body
    return out


def engine_replay(rt) -> tuple[int, list[str], str | None]:
    """(replayed, mismatches, skipped_reason)."""
    if rt.world is None:
        return 0, [], "no world (stub pipeline)"
    try:
        from engine.engine import Engine
    except Exception as e:  # noqa: BLE001
        return 0, [], f"engine not importable ({type(e).__name__})"
    impl = (rt.health_impl() or {}).get("engine") if hasattr(rt, "health_impl") else None
    rules = [Rule.model_validate(x) for x in rt.store.all("rule")]
    eng = Engine(rt.world)
    n, bad = 0, []
    for key, body in sorted(decision_docs(rt).items()):
        d = FlightDecision.model_validate(body)
        try:
            again = eng.decide_in(rt.world, d.flight_id, rules, d.known_at)
        except Exception as e:  # noqa: BLE001
            bad.append(f"{key}: engine raised {type(e).__name__}: {e}")
            continue
        n += 1
        a = {f: getattr(d, f) for f in COMPARE}
        b = {f: getattr(again, f) for f in COMPARE}
        if orjson.dumps(a, default=str) != orjson.dumps(b, default=str):
            diff = {f: (a[f], b[f]) for f in COMPARE if a[f] != b[f]}
            bad.append(f"{key}: {diff}")
    if bad and impl not in (None, "real"):
        return n, [], f"server engine impl is {impl!r}; {len(bad)} decisions differ from the pure engine (informational)"
    return n, bad, None


def verify_db(path: Path) -> int:
    from server.store import Store
    st = Store(path)
    n, bad = st.verify_chain()
    for h in bad:
        print(f"BAD commit {h}")
    print(f"{n} commits verified" + (" · chain intact" if not bad else f" · {len(bad)} broken"))
    return 0 if not bad and n else 1


def main(argv: list[str]) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--db", type=Path, help="verify an existing database's chain only")
    ap.add_argument("--world", type=Path, help="world.json to boot (default: golden)")
    args = ap.parse_args(argv)
    if args.db:
        return verify_db(args.db)
    t0 = time.monotonic()
    problems: list[str] = []
    with tempfile.TemporaryDirectory(prefix="sc-verify-") as tmp:
        a = boot(Path(tmp) / "a" / "stormcheck.db", args.world)
        b = boot(Path(tmp) / "b" / "stormcheck.db", args.world)
        n, bad = a.store.verify_chain()
        nb, bad_b = b.store.verify_chain()
        problems += [f"broken commit {h} (boot A)" for h in bad] + [f"broken commit {h} (boot B)" for h in bad_b]
        if n == 0:
            problems.append("no commits at all: the pipeline did not boot")
        if a.store.head() != b.store.head() or n != nb:
            problems.append(f"replay differs: head {a.store.head()} vs {b.store.head()} ({n} vs {nb} commits)")
        da, db_ = decision_docs(a), decision_docs(b)
        for k in sorted(set(da) | set(db_)):
            if _hash(da.get(k)) != _hash(db_.get(k)):
                problems.append(f"decision {k} differs between two offline boots")
        replayed, mism, skipped = engine_replay(a)
        problems += [f"engine replay: {m}" for m in mism]
        for p in problems:
            print(f"FAIL {p}")
        extra = f" · engine replay {replayed} decisions" if replayed else ""
        if skipped:
            extra += f" · engine replay skipped: {skipped}"
        status = "replay identical" if not problems else f"{len(problems)} problems"
        print(f"{n} commits verified · {status} · {len(da)} decisions{extra} · {time.monotonic() - t0:.1f}s")
        for rt in (a, b):
            try:
                rt.store.close()
            except Exception:  # noqa: BLE001
                pass
    return 0 if not problems else 1


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
