# KICKOFF: how each person runs their two overnight lanes

Each person opens **two** Claude Code sessions, one per lane, each in its own git worktree.

## Steps

1. **Create your worktrees.** Example for Filip:
   ```bash
   git fetch origin && git worktree add ../sc-filip-a -b filip/a-world origin/main
   git worktree add ../sc-filip-b -b filip/b-books origin/main
   ```

2. **Configure each worktree.** In each worktree, run:
   ```bash
   git config core.hooksPath .githooks
   export STORMCHECK_OWNER=<david|filip|justin>
   uv sync
   ```
   Justin also runs `cd web && pnpm i`.

3. **Optional: set up your Claude Code permissions.** These are *your own* settings, and you choose them. Allowing the repo's routine commands (`uv run …`, `pnpm …`, `make …`, `git add/commit/push`, `scripts/land.sh`) stops your agents from stalling on permission prompts overnight.

4. **Paste the kickoff prompt** for your lane (below) into its session.

5. **Check in.** At 02:00, 04:00 and 07:00, glance at `STATUS.md` and your branch's commits.

---

## Kickoff prompt template (fill in NAME and LANE)

> You are the **NAME lane LANE** agent for the StormCheck hackathon project (Cal Hacks 13.0, Hyphenate track). Read `CLAUDE.md`, `IMPLEMENTATION_PLAN.md`, `CONTRACTS.md` and `THREAD_NAME.md`.
>
> Work through the **Lane LANE** task queue in `THREAD_NAME.md`, in order, until it is empty or the 22:00 feature freeze.
>
> For each task:
> 1. Write its tests first.
> 2. Implement.
> 3. Run the lane suite.
> 4. Commit with message `<area>: <task-id> <what>`, with no AI attribution lines.
> 5. Run `scripts/land.sh`.
>
> **I authorize you to commit and push to this repository (branch `NAME/LANE-*` and main via land.sh) for the whole session.**
>
> Do not stop between tasks to ask me anything:
> - Log judgment calls in `<area>/DECISIONS.md`.
> - Update your line in `STATUS.md` every hour.
> - If you're stuck for more than 20 minutes on a task, write `BLOCKED: <why>` in `<area>/TASKS.md` and continue with the next task.
>
> Never edit files outside your lane's directories. Never weaken acceptance tests. Never edit `contracts/fixtures/golden/expected/`. Hit the checkpoints in `IMPLEMENTATION_PLAN.md §7`.

## Lane map

| Person | Lane A | Lane B |
|---|---|---|
| David | `engine/` (D1 → D2 → D3 → D6 → D4 → D8 → D5 → D9 → D7) | `contracts/` + `server/` + `scripts/` (D0a → D0b → D10a → D10b → D10c → D11) |
| Filip | `world/` + `eval/` (F1 → F2 → F0 → F3a → F3b → F3c → F3d → F9) | `books/` + `llm/` (F8a → F4 → F5 → F6 → F8b → F8c → F7*) |
| Justin | `web/` core (J0 → J1 → J2 → J3) | `web/` rest + `pitch/` + docs (J10 → J4 → J5 → J6 → J7 → J8 → J9 → J11) |

\* F7 is a stretch task.

## Checkpoints (PDT)

| Checkpoint | Time | Owner | What lands |
|---|---|---|---|
| CP0a | 01:45 | David B | stub |
| CP0b | 04:00 | David B | golden + helpers |
| D10a | 06:00 | David B | thin real server |
| F8a | 07:00 | Filip B | books golden-exact |
| CP1 | 09:00 | everyone | — |
| CP2 | 15:00 | everyone | — |
| CP3 | 22:00 | everyone | feature freeze |
| Submit | Sun 08:30 | everyone | Devpost |
