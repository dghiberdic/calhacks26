# Requests from server/ (David lane B, server agent)

- david-server Sat 10:00 PDT: **Makefile `dev`** → `uv run uvicorn server.app:app --port 8000` (the real server lands with D10a; it serves `web/dist` at `/` when built). `make demo` can reuse it once D11 lands. Env knobs: `STORMCHECK_DB` (default `data/stormcheck.db`, `baseline.db` beside it), `STORMCHECK_WORLD`, `STORMCHECK_MODE`, `*_IMPL`.
