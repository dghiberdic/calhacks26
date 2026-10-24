#!/usr/bin/env python3
"""Reject changes to paths you don't own (see OWNERS; longest prefix wins; '*' = anyone; no entry = nobody).

Usage:
  STORMCHECK_OWNER=david python3 scripts/check_owners.py --staged
  STORMCHECK_OWNER=david python3 scripts/check_owners.py --range origin/main..HEAD

What counts as a change:
  --range A..B   the branch's net diff against the merge base (`git diff A...B`): edits made inside merge commits
                 count, while changes merged in from A (main) do not.
  --staged       the index against HEAD; while a merge is in progress, only paths that differ from both HEAD and
                 MERGE_HEAD (a file taken as-is from the branch being merged is not your edit).
Both sides of a rename count (`--no-renames`: a move out of a lane deletes that lane's file), paths are read raw
(`-z`, `core.quotePath=false`), so non-ASCII or odd names can't hide behind git's quoting, and a path that no
OWNERS entry covers is denied (e.g. a root conftest.py that could skip every test): add it to OWNERS first.
Stdlib only: the pre-commit hook runs it with the system python3.
"""
from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


def load_owners() -> list[tuple[str, str]]:
    rules = []
    for line in (ROOT / "OWNERS").read_text(encoding="utf-8").splitlines():
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


def git(*args: str) -> bytes:
    return subprocess.run(["git", "-c", "core.quotePath=false", *args], cwd=ROOT, capture_output=True,
                          check=True).stdout


def parse_name_status(out: bytes) -> set[str]:
    """`git diff --name-status -z` → every path named (both sides of a rename/copy, should one slip through)."""
    parts = out.split(b"\0")
    paths: set[bytes] = set()
    i = 0
    while i < len(parts):
        status = parts[i]
        if not status:
            i += 1
            continue
        n = 2 if status[:1] in (b"R", b"C") else 1
        paths.update(parts[i + 1:i + 1 + n])
        i += 1 + n
    return {p.decode("utf-8", "surrogateescape") for p in paths if p}


def diff_paths(*args: str) -> set[str]:
    return parse_name_status(git("diff", "--name-status", "-z", "--no-renames", *args))


def merging() -> bool:
    return subprocess.run(["git", "rev-parse", "-q", "--verify", "MERGE_HEAD"], cwd=ROOT, capture_output=True
                          ).returncode == 0


def changed_files(args: list[str]) -> list[str]:
    if "--staged" in args:
        paths = diff_paths("--cached")
        if merging():
            paths &= diff_paths("--cached", "MERGE_HEAD")
    elif "--range" in args:
        rng = args[args.index("--range") + 1]
        if "..." not in rng:
            base, _, tip = rng.partition("..")
            rng = f"{base}...{tip or 'HEAD'}"
        paths = diff_paths(rng)
    else:
        print(__doc__)
        sys.exit(2)
    return sorted(paths)


def main() -> int:
    me = os.environ.get("STORMCHECK_OWNER")
    if not me:
        print("check_owners: set STORMCHECK_OWNER=<david|filip|justin> (see KICKOFF.md)", file=sys.stderr)
        return 1
    rules = load_owners()
    bad = []
    for path in changed_files(sys.argv[1:]):
        owner = owner_of(path, rules)
        if owner == "*" or owner == me:
            continue
        bad.append((path, owner))
    if bad:
        print(f"check_owners: {me} may not change these paths:", file=sys.stderr)
        for path, owner in bad:
            shown = path.encode("utf-8", "backslashreplace").decode("utf-8")
            print(f"  {shown}  ({'no owner in OWNERS: add an entry first' if owner is None else 'owner: ' + owner})",
                  file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
