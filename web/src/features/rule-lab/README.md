# Rule Lab in the StormCheck interface

This is the native React integration of `eval/rule_lab/`. It follows the voucher
ruling in `/story`, with the story's scroll reveals and rolling figures. The same
workbench is available at `/rule-lab` from the app sidebar. Both use the team's
existing typography, colors, query client and motion preferences.

The user explicitly requested integration into the team's animated interface.
This work stays on `codex/rule-lab-interface` for review. The earlier standalone
Rule Lab remains available independently; this branch changes no Engine, Books,
approval route, fixture, rule store or existing recording.

## Try it

From the repository root, start the optional lab service:

```sh
LLM_MODE=offline STORMCHECK_MODE=offline PYTHONDONTWRITEBYTECODE=1 \
  uv run python -m eval.rule_lab --serve
```

In another terminal, start the frontend with the existing storm recording:

```sh
cd web
pnpm install --frozen-lockfile
pnpm dev --mode recorded
```

Open `/story` and click **Rule Lab** in the top navigation. Try **Widen the scope**
to see the non-EU case fail, **Drop consent** to see the signed-voucher scope
failure, and **Change the author** to see the authority gate stop simulation.
**Keep the scope** restores the passing proposal. Case marks reveal their actual
before/after evidence. **Export evidence** downloads the complete report.

The section prepares evidence for review. There is no confirm, approve or pay
action here, and these tests do not govern the existing app's activation route.
It is a fixed Q1 voucher demonstration, not arbitrary rule generation.

## Live and saved evidence

- In development, `/rule-lab-api/report` proxies to the loopback lab on port 4186.
  Set `RULE_LAB_TARGET` to use another lab address. The main `/api` is unchanged.
- When the optional service is unavailable, or its envelope is inconsistent, the
  client displays committed runner output labeled **Saved evidence · simulated
  cases**. It explicitly says a fresh run has not occurred. It never labels saved
  evidence as live or silently uses a report for a different candidate.
- Production builds use saved evidence by default. A deliberate live integration
  can set `VITE_RULE_LAB_API` to a same-origin proxy prefix ending before `/report`.
  The loopback lab is a development service, not a public deployment design.
- Requests time out after eight seconds and cancel on candidate switches. Results
  are cached for the session until **Refresh evidence** / **Run checks again**.
- All amounts, outcomes and check counts come from the report. Saved reports are
  loaded separately per candidate. No model calls or extra packages are needed.

## Refresh the saved reports

Run from the repository root using its Python environment. These are actual
deterministic runner outputs, not frontend-made numbers:

```sh
LLM_MODE=offline STORMCHECK_MODE=offline uv run python - <<'PY'
from pathlib import Path
import orjson
from eval.rule_lab.runner import PRESETS, run_lab

folder = Path("web/src/features/rule-lab/recorded")
for preset in PRESETS:
    report = run_lab(preset)
    (folder / f"{preset}.json").write_bytes(
        orjson.dumps(report, option=orjson.OPT_INDENT_2 | orjson.OPT_SORT_KEYS) + b"\n"
    )
PY
```

Review the embedded source/input fingerprints when refreshing. The browser
checks the envelope and candidate identity; it does not authenticate a server or
cryptographically certify reports. Existing `eval/rule_lab/README.md` describes
the curated oracle, synthetic boundary cases and limitations.

## Validation

From `web/`: `pnpm test`, `pnpm typecheck`, `pnpm lint`,
`pnpm build:recorded`, and `pnpm e2e rule-lab.spec.ts story.spec.ts`.
The new browser tests force the optional lab offline to verify honest fallback;
they cover normal story motion, candidate changes, authority stops and a narrow
screen with reduced motion. Transport/component tests cover live results,
cancellation and malformed/mismatched report fallback.
