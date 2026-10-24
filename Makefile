.PHONY: help stub stub-fixtures golden openapi test test-david dev dev-reload web-build web-build-offline demo \
        demo-offline verify smoke-1 smoke-2 smoke-3 record

PORT ?= 8000

help:
	@echo "stub | stub-fixtures | golden | openapi | test | test-david | dev | dev-reload | demo | demo-offline |"
	@echo "verify | smoke-1 | smoke-2 | smoke-3 | record"

# ---- contracts
stub:                       ## contract stub API on :8001 (fixtures in contracts/fixtures/api/)
	uv run uvicorn contracts.stub_app:app --port 8001 --reload

stub-fixtures:              ## rebuild contracts/fixtures/api/ + injections/ from golden + fakes
	uv run python scripts/build_api_fixtures.py

golden:                     ## rebuild contracts/fixtures/golden/world.json + curves.json (expected/ is frozen)
	uv run python scripts/build_golden.py

openapi:                    ## write contracts/openapi.json from the stub
	uv run python scripts/write_openapi.py

# ---- tests
test:
	uv run pytest -q

test-david:
	uv run pytest contracts engine server scripts -q

# ---- real server (server/app.py; serves web/dist at / when built)
dev:                        ## real server on :8000
	uv run uvicorn server.app:app --host 127.0.0.1 --port $(PORT)

dev-reload:
	uv run uvicorn server.app:app --host 127.0.0.1 --port $(PORT) --reload

web-build:                  ## build web/dist if the frontend and pnpm are there (else the API runs alone)
	@if [ -f web/package.json ] && command -v pnpm >/dev/null 2>&1; then \
	  cd web && pnpm install --frozen-lockfile && pnpm build; \
	else echo "web-build: skipped (no web/package.json or no pnpm); serving the API only"; fi

web-build-offline:          ## no network: reuse web/dist, or build from an existing node_modules
	@if [ -f web/dist/index.html ]; then echo "web: using existing web/dist"; \
	elif [ -d web/node_modules ] && command -v pnpm >/dev/null 2>&1; then cd web && pnpm build; \
	else echo "web-build-offline: no web/dist and no node_modules; serving the API only"; fi

demo: web-build             ## one process on :8000 (API + web/dist), cache mode
	STORMCHECK_MODE=cache uv run uvicorn server.app:app --host 0.0.0.0 --port $(PORT)

demo-offline: web-build-offline   ## wifi off: pinned METAR, LLM_MODE=offline, no uv sync
	STORMCHECK_MODE=offline LLM_MODE=offline UV_OFFLINE=1 uv run --offline uvicorn server.app:app --host 0.0.0.0 --port $(PORT)

# ---- verification and checkpoints
verify:                     ## recompute every commit hash + replay every decision offline
	STORMCHECK_MODE=offline LLM_MODE=offline uv run python scripts/verify.py

smoke-1:                    ## CP1: golden decisions + Books numbers from the real server
	bash scripts/smoke_cp1.sh

smoke-2:                    ## CP2: desk, inject → SSE, Q1 → Herminia, blame → METAR
	bash scripts/smoke_cp2.sh

smoke-3:                    ## CP3: offline, 8 injections + 20 fuzz, eval, recorded build, verify
	bash scripts/smoke_cp3.sh

record:                     ## capture every GET route into demo/recorded/api/ (Justin commits it)
	STORMCHECK_MODE=offline LLM_MODE=offline uv run python scripts/record.py
