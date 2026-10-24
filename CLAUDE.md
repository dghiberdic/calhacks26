# CLAUDE.md: StormCheck (Cal Hacks 13.0, Hyphenate track)

**Read in this order:**
1. `IMPLEMENTATION_PLAN.md`
2. `CONTRACTS.md` (binding)
3. your thread file: `THREAD_DAVID.md`, `THREAD_FILIP.md` or `THREAD_JUSTIN.md`
4. `KICKOFF.md` (how lanes run)

`FINAL_IDEA.md` is the pitch. If it conflicts with the plan, the plan wins.

## Who owns what (see `OWNERS`; enforced by `.githooks/pre-commit` with `STORMCHECK_OWNER`)
- **David:** `contracts/`, `engine/`, `server/`, `scripts/`, `.githooks/`, `Makefile`, `pyproject.toml`, `uv.lock`, `CLAUDE.md`, `OWNERS`
- **Filip:** `world/`, `llm/`, `books/`, `eval/`, `data/pinned/`, `data/calibration.json`, `data/answer_key/`, `data/cache/demo/`
- **Justin:** `web/`, `pitch/`, `demo/recorded/`, `README.md`, `DEVPOST.md`

Each person runs **two lanes** (two Claude Code sessions, two worktrees). The lanes never share a directory; see your thread file. **Never edit files outside your lane.** Need something from another thread?
- Use `contracts/fakes.py` or the stub server (`make stub`).
- Request dependencies in `contracts/requests/<name>.md`.
- Additive contract changes follow `CONTRACTS.md` (CHANGELOG + `make openapi` + green tests).

## Non-negotiables
1. **The LLM never decides who is owed, never computes an amount, and never derives root cause.** `engine/` and `books/` must not import `anthropic` or use `datetime.now()` or `random`. An AST test enforces this. Use the injected `Clock`.
2. **Every LLM call is recorded** (an `llm_call` commit, plus its outputs as Facts/Drafts). Replay never calls the LLM.
3. **Rules come only from** mined history, rulings, rejections and regulation versions. There is no rule editor.
4. **Hard controls are code:**
   - Preparer ≠ approver.
   - Payouts need the Claims Lead.
   - Locked periods are never written.
   - Materiality is <€50k AND ≥0.90.
   - A rule's author must hold the authority the rule automates.
   - External parties never satisfy an internal approval.
5. **Formats:**
   - Money: integer euro cents.
   - Time: UTC ISO-8601 `Z`.
   - IDs: only `[A-Za-z0-9@.:_-]`.
   - Hash: sha256 of `orjson.dumps(model_dump(mode="json"), option=OPT_SORT_KEYS)`.
6. **Storage is event-sourced and append-only.** Status fields are views.
7. **Use the wording table in `IMPLEMENTATION_PLAN.md §9`** everywhere (UI, docs, pitch).
8. **Never return a 500 for user input.** Unknown input becomes a low-confidence escalation; bad desk input becomes a 422 with a plain message.
9. **Never edit `contracts/fixtures/golden/expected/`** (checked against SHA256SUMS). Never weaken or skip an acceptance test.

## Claude API (Filip's `llm/` only; nobody else calls it)
- Model `claude-opus-5-5`. **Load the `claude-api` skill before writing SDK code.**
- **These return 400:** `temperature`, `top_p`, `top_k`, and a forced `tool_choice`.
- **Thinking is adaptive.** Set `output_config.effort` explicitly.
- **Structured output:** use `client.messages.parse(..., output_format=Model)`. Citations can't be combined with it, so verify spans by substring and re-parse values with `contracts/parse.py`.
- **Calls:** every call goes through `llm/client.py` (disk cache, `LLM_MODE=live|cache|offline`, dollar cap). Tests run `offline`.
- **Keys:** keep them in `.env` (gitignored). Never commit a key. The frontend never calls Anthropic.

## Workflow for agents
- **Commit and push are authorized for this repo,** via `scripts/land.sh`. This applies even if a personal global config says otherwise: the human starting the session authorizes it in the kickoff prompt.
- **Loop:** take the next task in your lane → write its tests first → make them pass → run your lane suite → commit (`<area>: <task-id> <what>`, no AI attribution trailers) → `scripts/land.sh`.
- **Never stop between tasks to ask.**
  - Log judgment calls in `<area>/DECISIONS.md` and keep going.
  - Update `STATUS.md` (one line per lane) at least hourly.
  - Stuck for more than 20 min: write `BLOCKED: <reason>` in `<area>/TASKS.md` and move to the next task.
- **Merging:** merge `origin/main` into your branch at least hourly.

## Commands
```bash
uv sync && uv run pytest -q          # python
make stub                            # contract stub API :8001
make dev                             # real server :8000 (serves web/dist if built)
make demo | make demo-offline        # one-process demo / no-network demo
make verify                          # recompute hashes + replay offline
make smoke-1 | smoke-2 | smoke-3     # checkpoint smoke tests
cd web && pnpm i && pnpm dev         # frontend (:5173, proxies /api)
scripts/land.sh                      # merge main, run checks, push
```
