#!/usr/bin/env python3
"""Reject changes to paths you don't own (see OWNERS; longest prefix wins; '*' = anyone).

Usage:
  STORMCHECK_OWNER=david python3 scripts/check_owners.py --staged
  STORMCHECK_OWNER=david python3 scripts/check_owners.py --range origin/main..HEAD
"""
from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


def load_owners() -> list[tuple[str, str]]:
    rules = []
    for line in (ROOT / "OWNERS").read_text().splitlines():
        line = line.split("#", 1)[0].strip()
        if not line:
            continue
        prefix, owner = line.split()[:2]
        rules.append((prefix, owner))
    return sorted(rules, key=lambda r: len(r[0]), reverse=True)


def owner_of(path: str, rules: list[tuple[str, str]]) -> str | None:
    for prefix, owner in rules:
        if path.startswith(prefix):
            return owner
    return None


def changed_files(args: list[str]) -> list[str]:
    if "--staged" in args:
        cmd = ["git", "diff", "--cached", "--name-only", "--diff-filter=ACMRD"]
    elif "--range" in args:
        rng = args[args.index("--range") + 1]
        # only commits authored on this branch (exclude merges from main)
        cmd = ["git", "log", "--no-merges", "--name-only", "--pretty=format:", rng]
    else:
        print(__doc__)
        sys.exit(2)
    out = subprocess.run(cmd, cwd=ROOT, capture_output=True, text=True, check=True).stdout
    return sorted({p for p in out.splitlines() if p.strip()})


def main() -> int:
    me = os.environ.get("STORMCHECK_OWNER")
    if not me:
        print("check_owners: set STORMCHECK_OWNER=<david|filip|justin> (see KICKOFF.md)", file=sys.stderr)
        return 1
    rules = load_owners()
    bad = []
    for path in changed_files(sys.argv[1:]):
        owner = owner_of(path, rules)
        if owner is None or owner == "*" or owner == me:
            continue
        bad.append((path, owner))
    if bad:
        print(f"check_owners: {me} may not change these paths:", file=sys.stderr)
        for path, owner in bad:
            print(f"  {path}  (owner: {owner})", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
