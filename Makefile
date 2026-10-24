.PHONY: help stub stub-fixtures openapi test test-david dev demo demo-offline verify smoke-1 smoke-2 smoke-3 record

help:
	@echo "stub | stub-fixtures | openapi | test | test-david | dev | demo | demo-offline | verify | smoke-1|2|3 | record"

# ---- contracts (D0a)
stub:                       ## contract stub API on :8001 (fixtures in contracts/fixtures/api/)
	uv run uvicorn contracts.stub_app:app --port 8001 --reload

stub-fixtures:              ## rebuild contracts/fixtures/api/ (lands with D0b: scripts/build_api_fixtures.py)
	@if [ -f scripts/build_api_fixtures.py ]; then uv run python scripts/build_api_fixtures.py; else uv run python scripts/build_stub_fixtures.py; fi

openapi:                    ## write contracts/openapi.json from the stub
	uv run python scripts/write_openapi.py

# ---- tests
test:
	uv run pytest -q

test-david:
	uv run pytest contracts engine server -q

# ---- placeholders (later David-B tasks)
dev:
	@echo "make dev: real server on :8000 lands with D10a (use 'make stub' on :8001 until then)"

demo:
	@echo "make demo: lands with D11"

demo-offline:
	@echo "make demo-offline: lands with D11"

verify:
	@echo "make verify: lands with D11"

smoke-1:
	@echo "make smoke-1: lands with D11 (CP1)"

smoke-2:
	@echo "make smoke-2: lands with D11 (CP2)"

smoke-3:
	@echo "make smoke-3: lands with D11 (CP3)"

record:
	@echo "make record: lands with D11"
