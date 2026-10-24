#!/usr/bin/env bash
# Land your branch: merge origin/main, run checks, push your branch, then fast-forward main.
# Usage: scripts/land.sh [lane-test-command...]
#   e.g. scripts/land.sh uv run pytest engine -q
#        scripts/land.sh "cd web && pnpm test"
# Env: STORMCHECK_OWNER (required), LAND_MAIN=0 to skip updating main, LAND_LOCK_WAIT=<s> (default 2400),
#      LAND_LOCK_IMPL=mkdir to force the fallback lock.
# Landings are serialised: every worktree of this clone shares git's common dir, so one lock there means local
# agents land one at a time and main can't move under a running test. The lock is released when this script exits.
#   - flock(1) (Linux): fd 9 holds the lock. Every child runs with `9>&-`, so nothing it leaves behind (a server,
#     an ssh ControlMaster started by git fetch/push) can keep holding the lock after this script exits.
#   - no flock(1) (macOS): an atomic `mkdir <common>/land.lock.d` is the lock, removed on exit; a lock whose
#     holder pid is gone is taken over.
set -euo pipefail
cd "$(git rev-parse --show-toplevel)"

: "${STORMCHECK_OWNER:?set STORMCHECK_OWNER=<david|filip|justin> (see KICKOFF.md)}"
branch="$(git rev-parse --abbrev-ref HEAD)"
[ "$branch" = "main" ] && { echo "land.sh: work on your own branch, not main"; exit 1; }

common="$(git rev-parse --git-common-dir)"
lock="$common/land.lock"
wait_s="${LAND_LOCK_WAIT:-2400}"

if command -v flock >/dev/null 2>&1 && [ "${LAND_LOCK_IMPL:-flock}" != "mkdir" ]; then
  exec 9>"$lock"
  if ! flock -n 9; then
    echo "waiting for land lock… ($lock)"
    flock -w "$wait_s" 9 || { echo "land.sh: lock wait timed out"; exit 1; }
  fi
else
  lockdir="$lock.d"
  echo "land.sh: flock(1) not found (macOS?); using a mkdir lock at $lockdir"
  deadline=$(( $(date +%s) + wait_s ))
  announced=0
  until mkdir "$lockdir" 2>/dev/null; do
    holder="$(cat "$lockdir/pid" 2>/dev/null || true)"
    if [ -n "$holder" ] && ! kill -0 "$holder" 2>/dev/null; then
      echo "land.sh: taking over a stale land lock (pid $holder is gone)"
      rm -rf "$lockdir"
      continue
    fi
    if [ "$announced" = 0 ]; then echo "waiting for land lock… ($lockdir)"; announced=1; fi
    if [ "$(date +%s)" -ge "$deadline" ]; then echo "land.sh: lock wait timed out"; exit 1; fi
    sleep 1
  done
  echo "$$" > "$lockdir/pid"
  trap 'rm -rf "$lockdir"' EXIT
fi

for attempt in 1 2 3; do
  git fetch origin --quiet 9>&-
  git merge --no-edit origin/main 9>&-
  uv run pytest contracts -q 9>&-
  if [ "$#" -gt 0 ]; then bash -c "$*" 9>&-; fi   # children don't inherit the lock (a leftover server can't hold it)
  python3 scripts/check_owners.py --range origin/main..HEAD 9>&-
  git push origin "HEAD:$branch" 9>&-
  if [ "${LAND_MAIN:-1}" = "1" ]; then
    if git push origin HEAD:main 9>&-; then echo "landed $branch → main"; exit 0; fi
    echo "main moved; retrying ($attempt/3)"; sleep 2
  else
    echo "pushed $branch (main not updated)"; exit 0
  fi
done
echo "land.sh: could not fast-forward main after 3 attempts"; exit 1
