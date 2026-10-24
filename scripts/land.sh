#!/usr/bin/env bash
# Land your branch: merge origin/main, run checks, push your branch, then fast-forward main.
# Usage: scripts/land.sh [lane-test-command...]
#   e.g. scripts/land.sh uv run pytest engine -q
#        scripts/land.sh "cd web && pnpm test"
# Env: STORMCHECK_OWNER (required), LAND_MAIN=0 to skip updating main.
set -euo pipefail
cd "$(git rev-parse --show-toplevel)"

: "${STORMCHECK_OWNER:?set STORMCHECK_OWNER=<david|filip|justin> (see KICKOFF.md)}"
branch="$(git rev-parse --abbrev-ref HEAD)"
[ "$branch" = "main" ] && { echo "land.sh: work on your own branch, not main"; exit 1; }

for attempt in 1 2 3; do
  git fetch origin --quiet
  git merge --no-edit origin/main
  uv run pytest contracts -q
  if [ "$#" -gt 0 ]; then bash -c "$*"; fi
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
