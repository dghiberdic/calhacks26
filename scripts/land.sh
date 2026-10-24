#!/usr/bin/env bash
# Land your branch: merge origin/main, run checks, push your branch, then fast-forward main.
# Usage: scripts/land.sh [lane-test-command...]
#   e.g. scripts/land.sh uv run pytest engine -q
#        scripts/land.sh "cd web && pnpm test"
# Env: STORMCHECK_OWNER (required), LAND_MAIN=0 to skip updating main, LAND_LOCK_WAIT=<s> (default 2400).
# Landings are serialised: every worktree of this clone shares git's common dir, so one flock there means local
# agents land one at a time and main can't move under a running test. The lock is released when this script exits.
set -euo pipefail
cd "$(git rev-parse --show-toplevel)"

: "${STORMCHECK_OWNER:?set STORMCHECK_OWNER=<david|filip|justin> (see KICKOFF.md)}"
branch="$(git rev-parse --abbrev-ref HEAD)"
[ "$branch" = "main" ] && { echo "land.sh: work on your own branch, not main"; exit 1; }

lock="$(git rev-parse --git-common-dir)/land.lock"
exec 9>"$lock"
if ! flock -n 9; then
  echo "waiting for land lock… ($lock)"
  flock -w "${LAND_LOCK_WAIT:-2400}" 9 || { echo "land.sh: lock wait timed out"; exit 1; }
fi

for attempt in 1 2 3; do
  git fetch origin --quiet
  git merge --no-edit origin/main
  uv run pytest contracts -q 9>&-
  if [ "$#" -gt 0 ]; then bash -c "$*" 9>&-; fi   # children don't inherit the lock (a leftover server can't hold it)
  python3 scripts/check_owners.py --range origin/main..HEAD
  git push origin "HEAD:$branch"
  if [ "${LAND_MAIN:-1}" = "1" ]; then
    if git push origin HEAD:main; then echo "landed $branch → main"; exit 0; fi
    echo "main moved; retrying ($attempt/3)"; sleep 2
  else
    echo "pushed $branch (main not updated)"; exit 0
  fi
done
echo "land.sh: could not fast-forward main after 3 attempts"; exit 1
