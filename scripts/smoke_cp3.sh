#!/usr/bin/env bash
# CP3 (Sat 22:00, feature freeze): offline mode, 8 injections + 20 fuzz never 500, eval, recorded build, verify.
export STORMCHECK_MODE=offline LLM_MODE=offline
exec "$(dirname "$0")/smoke_server.sh" cp3
