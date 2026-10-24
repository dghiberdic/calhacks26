#!/usr/bin/env bash
# CP1 (Sat 09:00): golden decisions + Books numbers from the real server. See scripts/smoke.py.
exec "$(dirname "$0")/smoke_server.sh" cp1
