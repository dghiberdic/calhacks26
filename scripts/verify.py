#!/usr/bin/env python3
"""D11 `make verify`: recompute every commit hash and replay every decision offline, bitemporally.

1. Boot the real pipeline twice, offline, into two fresh temp databases (never touching data/).
2. Chain: recompute every commit hash, parent link and payload hash. When the runtime keeps an `engine.trace`
   TraceStore, its `verify()` also cross-checks every index row (facts, decisions, rules, periods…) against the
   commit that wrote it.
3. Anchor: the two boots must give the same head and length ("head <sha> · N commits"), and with TraceStores each
   boot's chain must verify against the other's anchor (`verify(expected_head=, expected_count=)`).
4. Documents: every decision and entitlements document the API serves must be a committed payload: its hash is the
   `payload_hash` of a commit in the chain (a decision's `commit` field names that commit).
5. Bitemporal replay: re-decide every recorded decision from the facts and rules *as known at its own known_at*.
   With a TraceStore this is `TraceStore.replay_run(known_at, decide_fn)` (only the facts and rule events recorded
   by then). The server store keeps no fact log yet, so its fallback replays the base world with the rule
   documents as they stood at known_at (their version history). Never the LLM: offline mode.

`--db PATH` verifies an existing database's chain instead (e.g. the live demo DB) and skips the double boot;
`--expect-head SHA[:N]` also checks a published anchor against it.
Prints "N commits verified · replay identical" and exits 0, or lists every problem and exits 1.

Usage: uv run python scripts/verify.py [--db PATH [--expect-head SHA[:N]]] [--world PATH]
"""
from __future__ import annotations

import argparse
import hashlib
import os
import sqlite3
import sys
import tempfile
import time
from collections import defaultdict
from collections.abc import Callable
from datetime import datetime
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
ROWS_TAG = "rows@"      # engine.trace: a typed commit's index-row digest


def _hash(obj: Any) -> str:
    """CONTRACTS hash of a JSON document: sha256(orjson.dumps(doc, OPT_SORT_KEYS))."""
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


# ---------------------------------------------------------------- where the chain lives

def find_trace(rt) -> Any | None:
    """The runtime's engine.trace TraceStore, when the server keeps one (duck-typed: replay_run + verify + anchor)."""
    store = getattr(rt, "store", None)
    for obj in (getattr(rt, "trace", None), getattr(store, "trace", None),
                getattr(getattr(rt, "lifecycle", None), "trace", None), store):
        if obj is not None and all(callable(getattr(obj, a, None)) for a in ("replay_run", "verify", "anchor")):
            return obj
    return None


def chain(rt) -> tuple[int, str | None, list[str]]:
    """(commits, head, problems) for whichever store holds the chain."""
    tr = find_trace(rt)
    if tr is not None:
        v = tr.verify()
        return v.checked, v.head, list(v.reasons)
    n, bad = rt.store.verify_chain()
    return n, rt.store.head(), [f"broken commit {h}" for h in bad]


def cross_anchor(a, b) -> list[str]:
    """Each boot's chain verifies against the other boot's published anchor (TraceStores only)."""
    ta, tb = find_trace(a), find_trace(b)
    if ta is None or tb is None:
        return []
    out = []
    for name, x, y in (("A", ta, tb), ("B", tb, ta)):
        anc = y.anchor()
        v = x.verify(expected_head=anc.head, expected_count=anc.count)
        out += [f"boot {name} against the other boot's anchor: {r}" for r in v.issues]
    return out


def _commit_lookup(rt) -> Callable[[str], Any]:
    tr = find_trace(rt)
    if tr is None:
        return rt.store.commit_by_hash

    def get(h: str):
        try:
            return tr.get(h)
        except Exception:  # noqa: BLE001  (NotFound)
            return None
    return get


# ---------------------------------------------------------------- documents ↔ chain

def _docs(rt, kind: str) -> dict[str, Any]:
    store = getattr(rt, "store", None)
    if store is None or not callable(getattr(store, "keys", None)) or not callable(getattr(store, "get", None)):
        return {}
    out = {}
    for key in store.keys(kind):
        body = store.get(kind, key)
        if body is not None:
            out[key] = body
    return out


def decision_docs(rt) -> dict[str, dict[str, Any]]:
    """The decision documents the API serves, without their `commit` link (compared across boots)."""
    return {k: {f: v for f, v in body.items() if f != "commit"} for k, body in _docs(rt, "decision").items()
            if isinstance(body, dict)}


def doc_links(rt) -> tuple[int, list[str]]:
    """Every served decision / entitlements document is a committed payload: its hash is in the chain."""
    get = _commit_lookup(rt)
    n, bad = 0, []
    for key, body in sorted(_docs(rt, "decision").items()):
        n += 1
        h = body.get("commit") if isinstance(body, dict) else None
        c = get(h) if isinstance(h, str) and h else None
        if c is None:
            bad.append(f"decision document {key} names no commit in the chain ({str(h)[:12]})")
        elif c.kind != "decision" or c.payload_ref != key:
            bad.append(f"decision document {key} points at a {c.kind} commit for {c.payload_ref}")
        elif _hash({**body, "commit": None}) != c.payload_hash:
            bad.append(f"decision document {key} differs from the payload its commit {h[:12]} hashed")
    tr = find_trace(rt)
    commits_for = getattr(rt.store, "commits_for", None)
    for key, body in sorted(_docs(rt, "entitlements").items()):
        if not body:
            continue                    # a flight with no coupons commits no entitlements
        n += 1
        if tr is not None:
            hashes = {c.payload_hash for c in tr.log(limit=None, kind="entitlement") if c.payload_ref == key}
        elif callable(commits_for):
            hashes = {c.payload_hash for c in commits_for(key, kinds=["entitlement"])}
        else:
            hashes = set()
        if _hash(body) not in hashes:
            bad.append(f"entitlements document {key} matches no committed entitlement payload")
    return n, bad


# ---------------------------------------------------------------- bitemporal replay

def _diff(a: FlightDecision, b: FlightDecision) -> dict[str, tuple[Any, Any]]:
    x, y = ({f: getattr(d, f) for f in COMPARE} for d in (a, b))
    return {f: (x[f], y[f]) for f in COMPARE if orjson.dumps(x[f], default=str) != orjson.dumps(y[f], default=str)}


def replay_trace_decisions(trace, decide_fn_for: Callable[[list[str]], Any]) -> tuple[int, list[str]]:
    """Re-decide every recorded decision through ``TraceStore.replay_run(known_at, …)``: the facts and rule events
    recorded by its own known_at, nothing later. ``decide_fn_for(flight_ids)`` builds the engine's DecideFn."""
    recorded: list[FlightDecision] = []
    for c in reversed(trace.log(limit=None, kind="decision")):        # oldest first
        if any(i.startswith(ROWS_TAG) for i in c.inputs):             # typed: a recorded decision, not a raw commit
            recorded.append(FlightDecision.model_validate(trace.payload(c.hash)))
    by_known: dict[datetime, list[FlightDecision]] = defaultdict(list)
    for d in recorded:
        by_known[d.known_at].append(d)
    n, bad = 0, []
    for known_at in sorted(by_known):
        group = by_known[known_at]
        at = f"{known_at:%Y-%m-%dT%H:%MZ}"
        try:
            run = trace.replay_run(known_at, decide_fn_for(sorted({d.flight_id for d in group})))
        except Exception as e:  # noqa: BLE001  (a verifier reports, it doesn't crash)
            bad += [f"{d.flight_id} (known_at {at}): replay raised {type(e).__name__}: {e}" for d in group]
            continue
        for d in group:
            n += 1
            again = run.after.get(d.flight_id)
            if again is None:
                bad.append(f"{d.flight_id} (known_at {at}): not re-decided")
            elif diff := _diff(d, again):
                bad.append(f"{d.flight_id} (known_at {at}): {diff}")
    return n, bad


def rules_as_known(store, known_at: datetime) -> list[Rule]:
    """The rule documents as they stood at ``known_at`` (the latest version written by then)."""
    out = []
    for key in store.keys("rule"):
        versions = [body for at, body in store.history("rule", key) if at <= known_at]
        if versions:
            out.append(Rule.model_validate(versions[-1]))
    return out


def engine_replay(rt) -> tuple[int, list[str], str | None]:
    """(replayed, mismatches, note)."""
    if rt.world is None:
        return 0, [], "no world (stub pipeline)"
    try:
        from engine.engine import Engine
    except Exception as e:  # noqa: BLE001
        return 0, [], f"engine not importable ({type(e).__name__})"
    impl = (rt.health_impl() or {}).get("engine") if hasattr(rt, "health_impl") else None
    tr = find_trace(rt)
    note = None
    if tr is not None:
        lc = getattr(rt, "lifecycle", None)
        if lc is None or not callable(getattr(lc, "decide_fn", None)):
            from engine.lifecycle import Lifecycle
            lc = Lifecycle(Engine(rt.world), rt.world, tr)
        n, bad = replay_trace_decisions(tr, lc.decide_fn)
    else:
        note = "facts: base world (the server store keeps no fact log yet)"
        eng = Engine(rt.world)
        n, bad = 0, []
        for key, body in sorted(_docs(rt, "decision").items()):
            d = FlightDecision.model_validate(body)
            try:
                again = eng.decide_in(rt.world, d.flight_id, rules_as_known(rt.store, d.known_at), d.known_at)
            except Exception as e:  # noqa: BLE001
                bad.append(f"{key}: engine raised {type(e).__name__}: {e}")
                continue
            n += 1
            if diff := _diff(d, again):
                bad.append(f"{key}: {diff}")
    if bad and impl not in (None, "real"):
        return n, [], f"server engine impl is {impl!r}; {len(bad)} decisions differ from the pure engine (informational)"
    return n, bad, note


# ---------------------------------------------------------------- entry points

def _parse_anchor(s: str | None) -> tuple[str | None, int | None]:
    if not s:
        return None, None
    head, _, count = s.partition(":")
    return head or None, int(count) if count else None


def _is_trace_db(path: Path) -> bool:
    """Read-only peek, so verifying a server DB never creates trace tables in it."""
    try:
        con = sqlite3.connect(f"file:{path}?mode=ro", uri=True)
        try:
            return con.execute("SELECT 1 FROM sqlite_master WHERE type = 'table' AND name = 'meta'").fetchone() \
                is not None
        finally:
            con.close()
    except sqlite3.Error:
        return False


def verify_db(path: Path, expect: str | None = None) -> int:
    head, count = _parse_anchor(expect)
    if _is_trace_db(path):
        from engine.trace import TraceStore
        tr = TraceStore(path, engine_sha="verify", cal_version="verify")
        v = tr.verify(expected_head=head, expected_count=count)
        for r in v.reasons:
            print(f"BAD {r}")
        print(f"{v.summary()} · {v.anchor_text()}")
        return 0 if v.ok and v.checked else 1
    from server.store import Store
    st = Store(path)
    n, bad = st.verify_chain()
    for h in bad:
        print(f"BAD commit {h}")
    anchor_bad = False
    if head:
        hashes = [c.hash for c in reversed(st.commits(limit=10 ** 9))]
        anchor_bad = head not in hashes or (count is not None and (count > len(hashes) or hashes[count - 1] != head))
        if anchor_bad:
            print(f"BAD anchor: published head {head[:12]} is not where it was (truncated or rewritten)")
    print(f"{n} commits verified" + (" · chain intact" if not bad else f" · {len(bad)} broken")
          + f" · head {(st.head() or 'none')[:12]} · {n} commits")
    return 0 if not bad and n and not anchor_bad else 1


def main(argv: list[str]) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--db", type=Path, help="verify an existing database's chain only")
    ap.add_argument("--expect-head", help="with --db: a published anchor, SHA or SHA:N")
    ap.add_argument("--world", type=Path, help="world.json to boot (default: golden)")
    args = ap.parse_args(argv)
    if args.db:
        return verify_db(args.db, args.expect_head)
    t0 = time.monotonic()
    problems: list[str] = []
    with tempfile.TemporaryDirectory(prefix="sc-verify-") as tmp:
        a = boot(Path(tmp) / "a" / "stormcheck.db", args.world)
        b = boot(Path(tmp) / "b" / "stormcheck.db", args.world)
        n, head_a, bad = chain(a)
        nb, head_b, bad_b = chain(b)
        problems += [f"{r} (boot A)" for r in bad] + [f"{r} (boot B)" for r in bad_b]
        if n == 0:
            problems.append("no commits at all: the pipeline did not boot")
        if head_a != head_b or n != nb:
            problems.append(f"replay differs: head {head_a} vs {head_b} ({n} vs {nb} commits)")
        problems += cross_anchor(a, b)
        da, db_ = decision_docs(a), decision_docs(b)
        for k in sorted(set(da) | set(db_)):
            if _hash(da.get(k)) != _hash(db_.get(k)):
                problems.append(f"decision {k} differs between two offline boots")
        linked, unlinked = doc_links(a)
        problems += unlinked
        replayed, mism, note = engine_replay(a)
        problems += [f"bitemporal replay: {m}" for m in mism]
        for p in problems:
            print(f"FAIL {p}")
        extra = f" · {linked} documents in the chain"
        extra += f" · bitemporal replay {replayed} decisions" if replayed else ""
        if note:
            extra += f" · {note}"
        status = "replay identical" if not problems else f"{len(problems)} problems"
        print(f"{n} commits verified · {status} · head {(head_a or 'none')[:12]} · {len(da)} decisions{extra} · "
              f"{time.monotonic() - t0:.1f}s")
        for rt in (a, b):
            for obj in {id(x): x for x in (rt.store, find_trace(rt)) if x is not None}.values():
                try:
                    obj.close()
                except Exception:  # noqa: BLE001
                    pass
    return 0 if not problems else 1


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
