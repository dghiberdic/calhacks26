#!/usr/bin/env python3
"""D11 `make record`: capture every GET route of the real server into JSON files for the recorded (Vercel) build.

Boots the server in-process on a temp DB in offline mode (no network, no LLM) and writes one file per response:
`index.json` maps each URL (`/api/...`) to its file, so a static frontend can answer the same requests. File names
follow contracts/fixtures/api/ (`storm_<id>.json`, `flight_<id>.json`, `rollforward_<period>.json`, ...).

The default output, demo/recorded/api/, is Justin's directory: this script only writes it; Justin's lane commits it.

Usage: uv run python scripts/record.py [--out DIR] [--world PATH]
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import tempfile
from pathlib import Path
from typing import Any
from urllib.parse import urlencode

os.environ.setdefault("STORMCHECK_MODE", "offline")
os.environ.setdefault("LLM_MODE", "offline")

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

DEFAULT_OUT = ROOT / "demo" / "recorded" / "api"
SEGMENTS = ("long_haul_gt3500", "medium_1500_3500", "short_le1500")
PERIODS = ("2025-01", "2025-02")


def safe(name: str) -> str:
    return "".join(ch if ch.isalnum() or ch in "@._-" else "_" for ch in name)   # no ":" (Windows checkouts)


def record(client: Any, out: Path) -> dict[str, str]:
    out.mkdir(parents=True, exist_ok=True)
    for old in out.glob("*.json"):
        old.unlink()
    index: dict[str, str] = {}

    def grab(url: str, name: str, params: dict[str, str] | None = None) -> Any:
        full = url + (f"?{urlencode(params)}" if params else "")
        r = client.get(url, params=params)
        if r.status_code != 200:
            print(f"skip {full}: HTTP {r.status_code}")
            return None
        body = r.json()
        fname = safe(name) + ".json"
        (out / fname).write_text(json.dumps(body, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
        index[full] = fname
        return body

    grab("/api/health", "health")
    storms = grab("/api/storms", "storms") or []
    flight_ids: list[str] = []
    for s in storms:
        run = grab(f"/api/storms/{s['id']}", f"storm_{s['id']}")
        for row in (run or {}).get("flights", []):
            if row.get("decision"):
                flight_ids.append(row["flight"]["id"])
    journal = []
    for fid in flight_ids:
        ff = grab(f"/api/flights/{fid}", f"flight_{fid}")
        journal += (ff or {}).get("journal_preview", [])
    grab("/api/questions", "questions")
    grab("/api/questions", "questions_open", {"status": "open"})
    for path, name in (("/api/rules", "rules"), ("/api/trace", "trace"), ("/api/commits", "commits"),
                       ("/api/books/journal", "journal"), ("/api/books/cfo", "cfo"),
                       ("/api/books/invariants", "invariants"), ("/api/access/matrix", "access_matrix"),
                       ("/api/access/log", "access_log"), ("/api/controls", "controls"),
                       ("/api/injections", "injections"), ("/api/eval", "eval")):
        grab(path, name)
    for p in PERIODS:
        grab("/api/books/rollforward", f"rollforward_{p}", {"period": p})
    for s in storms:
        grab("/api/books/estimate", f"estimate_{s['id']}", {"cohort": s["id"]})
    for seg in SEGMENTS:
        grab("/api/books/curve", f"curve_{seg}", {"segment": seg})
    targets = [f"{je['id']}:{i}" for je in journal[:3] for i, ln in enumerate(je["lines"], 1) if ln["account"] == "2140"]
    for t in [*targets, *flight_ids[:1]]:
        grab("/api/blame", f"blame_{t}", {"target": t})
    for je in journal[:3]:
        grab(f"/api/audit/{je['id']}", f"audit_{je['id']}")
    (out / "index.json").write_text(json.dumps(dict(sorted(index.items())), indent=2) + "\n", encoding="utf-8")
    return index


def main(argv: list[str]) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", type=Path, default=DEFAULT_OUT)
    ap.add_argument("--world", type=Path)
    args = ap.parse_args(argv)
    from fastapi.testclient import TestClient

    with tempfile.TemporaryDirectory(prefix="sc-record-") as tmp:
        # server.app builds a module-level app from env at import: keep that one off data/ too
        os.environ["STORMCHECK_DB"] = str(Path(tmp) / "import" / "stormcheck.db")
        from server.app import create_app
        from server.config import Settings
        kw: dict[str, Any] = {"db_path": Path(tmp) / "stormcheck.db", "mode": "offline"}
        if args.world:
            kw["world_path"] = args.world
        app = create_app(Settings(**kw))
        with TestClient(app) as client:
            index = record(client, args.out)
    where = args.out.relative_to(ROOT) if args.out.is_relative_to(ROOT) else args.out
    print(f"recorded {len(index)} responses to {where}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
