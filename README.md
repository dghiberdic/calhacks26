# StormCheck

StormCheck fills two seats at Northstar Air, the Passenger Claims Accountant and the Revenue Accountant, with one step between them: what really caused each cancellation. It drafts every payout and the EU261 compensation liability; the Claims Lead approves every payment.

Built at Cal Hacks 13.0 for the Hyphenate track (autonomous systems for finance). Northstar Air is fictional: an EU-licensed Irish carrier reporting under IFRS in EUR, with about €1.1B revenue, about 65 aircraft and a Dublin hub. The storm is real.

## What it does

The morning after Storm Éowyn (Dublin, Friday 24 January 2025), StormCheck:
1. Reads real weather (METAR), the schedule, the operations cancellation log, the tech log, PSS coupons and reaccommodation, CRM and claims.
2. Decides each cancellation's cause deterministically, with evidence and a calibrated confidence.
3. Works out each passenger's EU261 entitlement.
4. Drafts refunds, payouts and the EU261 compensation liability, a reduction of passenger revenue under IFRS 15.
5. Asks a person only about the 1% where the evidence disagrees, and asks the right one: the Claims Lead, Legal or the Controller.

Each ruling becomes a scoped, versioned rule, so the question is never asked twice. Every euro traces back, with `blame`, to a log line, a weather hour, a rule and the person who ruled. It writes only drafts (case recommendations and parked journals) and never releases a payment run.

The hero case: operations coded all 27 cancellations "weather". NS31 to Boston was due out at 16:30Z, after the storm window closed at 15:00Z, and its tech log from 21:40Z the night before shows a hydraulic pump leak with no MEL relief. StormCheck recodes it 71 → 41 (technical, owed) at cause-finding confidence 91%. The full Art. 7 entitlement if every passenger claims is €99,000; it drafts €34,650 at a 35% expected ultimate claim rate. 172 passengers owed; 171 payouts drafted, pending Claims Lead approval, while 14C waits on her ruling. For the whole storm (27 cancellations, 5,292 passengers) the day-1 EU261 compensation liability is €82,146: NS31 plus three knock-on returns held for Legal. The 23 weather flights get no compensation; refunds and care are still due.

## Run it

You need Python 3.12 with [uv](https://docs.astral.sh/uv/), Node with pnpm, and `make`.

```bash
# once per checkout
git config core.hooksPath .githooks   # owner check and secret scan on every commit
uv sync
cd web && pnpm i && pnpm build && cd ..
cp .env.example .env                  # ANTHROPIC_API_KEY; never commit .env
```

A key is only needed when a call misses the LLM cache (a new injection or challenge, or a fresh eval run). `make demo-offline` and the tests need none.

**Demo**
```bash
make demo           # API and web in one process on :8000 (serves web/dist)
make demo-offline   # the same with no network: pinned METAR, LLM_MODE=offline
```
Open http://localhost:8000. Reset to the demo baseline with `curl -X POST localhost:8000/api/reset`.

**Develop**
```bash
make stub                      # contract stub API on :8001, served from fixtures
make dev                       # real server on :8000 (serves web/dist if it exists)
cd web && pnpm i && pnpm dev   # frontend on :5173, proxies /api to :8001 (API_TARGET=http://localhost:8000 for the server)
make openapi                   # regenerate contracts/openapi.json from the stub
cd web && pnpm gen:api         # regenerate the TypeScript API types from it
make record                    # record a full demo run into demo/recorded/
```

**Test and verify**
```bash
uv run pytest -q               # all Python tests; they run with LLM_MODE=offline
make verify                    # recompute every commit hash and replay every decision offline
make smoke-1                   # checkpoint smoke tests; also smoke-2 and smoke-3
cd web && pnpm test            # Vitest; pnpm e2e runs the Playwright demo walk-through
scripts/land.sh                # merge origin/main, run checks, push (needs STORMCHECK_OWNER)
```

**Modes**
- `STORMCHECK_MODE=live|cache|offline` (default `cache`) and `LLM_MODE=live|cache|offline`.
- `READER_IMPL`, `DRAFTER_IMPL`, `BOOKS_IMPL`, `WORLD_IMPL` and `ENGINE_IMPL` are each `fake|real`.
- The recorded build (`cd web && pnpm build:recorded`) serves `demo/recorded/` with no backend. It's deployed at `{{links.recorded_build}}`.
- `cd web && pnpm dev:mock` runs the frontend on an in-memory world typed from `CONTRACTS.md`, with no backend at all.

## Architecture

Two Claude roles and one deterministic engine.

```
 Feeds: METAR (IEM/AWC) · schedule · OCC log · tech/MCC log (AMOS-like) · PSS coupons · CRM · claims · spares
                │
   Reader  (Claude)        messy text → typed Facts. Every Fact quotes a verbatim span, and
                │          contracts/parse.py re-parses the value from it (mismatch → dropped).
                │          The Reader never decides anything.
   Engine  (deterministic) storm windows at both ends (in|out|unknown) → cause (ATA table, rotation;
                │          recoding needs tier-1 evidence) → EU261 entitlement → rules@version
                │          → confidence → route or hold → access broker (people and agents)
   Books   (deterministic) obligation register → parked journal drafts → 2140 rollforward
                │          → claim curves (Bornhuetter-Ferguson) → invariants
   Trace                   every fact, decision, rule, ruling, journal event and LLM call is a
                │          content-hashed commit: blame · replay(known_at) · revert · audit · make verify
   Drafter (Claude)        rights notices, journal memos, "why?", challenge classification, rule drafts
                │          (numbers in prose must appear in the evidence, else a template)
   FastAPI + SSE ──► Web (React) · role sessions with a signed token per principal
```

Claude is `claude-opus-5-5`, called only from `llm/` (Reader at low effort, Drafter at medium, structured outputs, a disk cache and a dollar cap). The frontend never calls Anthropic.

It sits on top of Amadeus Altéa or Navitaire (PNRs, coupons, reaccommodation), NetLine (cancellation messages, delay codes), AMOS (tech log, MEL, AOG orders), Accelya revenue accounting (BSP, SIS), the claims tool and the payment provider. It writes only drafts: case recommendations and parked SAP journals. In this repo those systems are simulated feeds behind an `ErpAdapter` interface.

## Binding rules

1. The LLM never decides who is owed, never computes an amount and never derives a root cause. `engine/` and `books/` don't import `anthropic`, call `datetime.now()` or use `random`; an AST test enforces it. One injected `Clock` drives everything.
2. Every LLM call is recorded as an `llm_call` commit, and its outputs are stored as Facts or Drafts. Replay never calls the LLM.
3. Rules come only from mined history, rulings, rejections and regulation versions. There is no rule editor.
4. Hard controls are code: preparer ≠ approver; payouts need the Claims Lead; locked periods are never written; auto-drafting only below €50k per flight and at ≥0.90 confidence; a rule's author must hold the authority it automates; external parties never satisfy an internal approval.
5. Storage is event-sourced and append-only. Status fields are views over events.
6. Money is integer euro cents. Time is UTC ISO-8601 with `Z`. IDs use only `[A-Za-z0-9@.:_-]`.
7. User input never causes a 500. Unknown input becomes a low-confidence escalation; bad desk input is a 422 with a plain message.
8. Contracts are additive-only. Nobody edits `contracts/fixtures/golden/expected/` (checked against `SHA256SUMS`) or weakens an acceptance test.

Wording follows the table in `IMPLEMENTATION_PLAN.md` §9 everywhere: UI, docs and pitch.

## Repo layout and owners

Ownership is by path (`OWNERS`, longest prefix wins) and is enforced by the pre-commit hook with `STORMCHECK_OWNER`.

| Path | What | Owner |
|---|---|---|
| `contracts/` | Pydantic models, Protocols, fixtures (incl. golden), stub server, field registry, parse and normalize | David |
| `engine/` | timeline, cause and ATA table, EU261, rules, confidence and routing, trace, lifecycle, access broker, miner | David |
| `server/` | FastAPI and SSE | David |
| `scripts/`, `.githooks/`, `Makefile`, `pyproject.toml`, `uv.lock` | landing, owner check, smoke tests, build | David |
| `world/` | METAR (pinned → IEM → AWC), airports, the Northstar generator | Filip |
| `llm/` | the Claude client (cache, modes, cap), Reader, Drafter | Filip |
| `books/` | IFRS 15 postings, estimates, rollforward, invariants | Filip |
| `eval/` | eval, calibration, baseline, `proof.json` | Filip |
| `data/` | pinned METAR, calibration, answer key, demo LLM cache | Filip |
| `web/` | the React app and `/pitch` | Justin |
| `pitch/` | demo script, video storyboard, judge Q&A | Justin |
| `demo/recorded/` | recorded API responses for the no-backend build | Justin |
| `README.md`, `DEVPOST.md` | this file, the Devpost write-up | Justin |
| `STATUS.md`, `contracts/requests/`, `contracts/CHANGELOG.md` | lane status, cross-thread requests, contract changes | anyone |

The plan documents (`IMPLEMENTATION_PLAN.md`, `CONTRACTS.md`, `THREAD_*.md`, `KICKOFF.md`, `CLAUDE.md`, `FINAL_IDEA.md`, `OWNERS`), `research/`, `archive/` and the repo config files (`.gitignore`, `.gitattributes`, `.env.example`) belong to David.

## What's real and what's simulated

Real Dublin weather, real airport traffic, real distances and real EU law. Northstar's schedule, logs, passengers and claims are simulated on top, with the mess left in.

| Real | Source |
|---|---|
| METAR for Dublin (EIDW) and any station or date on the Judge's Desk | Iowa Environmental Mesonet `asos.py`; NOAA AWC for the last 30 days. Demo days are pinned in the repo. |
| Airport-day traffic | Eurocontrol: EIDW had 179 departures on 24 Jan 2025 against about 292–316 normally. About 119 departures and 109 arrivals were reported cancelled (Cirium). Met Éireann's red warning for Dublin ran 06:00–11:00. |
| Distances | OurAirports, great circle per Art. 7(4), R = 6,371 km |
| Law | EU261 Arts 3, 5, 7, 8, 9, 14 and 15; CJEU C-549/07 *Wallentin-Hermann*, C-257/14 *van der Lans*, C-74/19 *TAP*, C-12/11 *McDonagh*, C-139/11 *Moré* |
| ATA chapters and MEL categories | FAA JASC (ATA Spec 100); EASA MMEL categories |
| Claim-rate benchmark | Steer 2020 for the European Commission |

Simulated: Northstar Air itself, its schedule and tails, tech, MCC and OCC logs, PSS coupons, CRM events, claims, care costs and claim history, with planted errors. BTS data isn't used; it covers US domestic flights only. Regulation (EU) 2026/2202 is in force from 22 Oct 2026 but applies from 23 Oct 2027, so it appears only as a static, future-dated rule card with no engine logic.

## Eval

- **World:** Northstar operations on real EIDW METAR: storm days selected from the data (gusts ≥35 kt for at least 3 h) plus about 40 background days, July 2023 to June 2025.
- **Ground truth:** latent causes (internal fault, weather, rotation, crew), with about 5% deliberately invisible to the features, so calibration isn't circular. At least five of each planted error type per split. The answer key is written by the generator from ground truth, never by the engine.
- **Split:** learn July 2023 to December 2024; score January to June 2025, which includes Éowyn.
- **Baseline:** plain Claude on the same raw documents, three runs, for Éowyn and two more storms.
- **Output:** `eval/proof.json` (an `EvalReport`) and `eval/NUMBERS.md`, served at `GET /api/eval` and on the Proof screen. Calibration is labelled honestly: "calibrated on synthetic labels; validates the pipeline, not the world".

```bash
LLM_MODE=offline uv run pytest eval -q   # proof.json validates and re-scores offline from the cache
{{eval.command}}                         # regenerate eval/proof.json (command lands with F9)
```

## Optional: your own Claude Code permission allowlist

Each of us runs two Claude Code agents overnight, and an agent waiting on a permission prompt at 3 a.m. loses hours. If you want, allowlist the repo's routine commands in **your own** settings so they run without asking. This is personal and optional: you choose what goes in, you edit only your own settings, and nothing here changes anyone else's.

Put it in `.claude/settings.local.json` at the root of the checkout you start Claude Code in. Example:

```json
{
  "permissions": {
    "allow": [
      "Bash(uv run *)",
      "Bash(pnpm *)",
      "Bash(make *)",
      "Bash(git add *)",
      "Bash(git commit *)",
      "Bash(git push *)",
      "Bash(scripts/land.sh)",
      "Bash(scripts/land.sh *)"
    ],
    "deny": [
      "Bash(git push --force *)",
      "Bash(git push -f *)",
      "Read(./.env)"
    ]
  }
}
```

- `Bash(cmd *)` matches the command followed by anything; the older `Bash(cmd:*)` form means the same. Deny rules win over allow rules. A rule has to match every part of a compound command, so `Bash(make *)` doesn't allow `make x && rm -rf y`.
- The deny lines are a suggestion: they keep the agent out of your key file and block the common force-push spellings (not every possible one).
- You run two worktrees. Run `/permissions` in each session to see which rules loaded and where from; if the second worktree doesn't show them, copy the file into it. To apply the rules to every project instead, put them in `~/.claude/settings.json`.
- Keep the file out of git. The docs don't promise it's ignored, and the shared `.gitignore` belongs to David's lane, so use your local exclude file: `echo .claude/settings.local.json >> "$(git rev-parse --git-path info/exclude)"`.
- An allowlist only removes prompts; it grants no authority. Commit and push for this repo are authorized by the kickoff prompt you paste (`KICKOFF.md`), the pre-commit hook still blocks paths you don't own, and `pnpm *` includes `pnpm add`, while only Justin's lane A changes `web/package.json`.

## Docs

- `IMPLEMENTATION_PLAN.md`: what we're building, the demo world, the money, screens and wording (wins on any conflict)
- `CONTRACTS.md`: models, interfaces, the HTTP API and the golden numbers (binding)
- `THREAD_DAVID.md`, `THREAD_FILIP.md`, `THREAD_JUSTIN.md`, `KICKOFF.md`: how the six lanes run
- `pitch/DEMO_SCRIPT.md`, `pitch/VIDEO.md`, `pitch/QA.md`: the 3:00 demo, the video, the judge questions
- `DEVPOST.md`: the submission write-up

Team: David (engine and API), Filip (world, intelligence and books), Justin (frontend, pitch and docs).
