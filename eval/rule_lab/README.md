# StormCheck Rule Lab — isolated proposal

StormCheck already turns an authorized ruling into a grounded, previewed rule. This
extension adds a **ruling-owned regression pack**: demonstrate the cases that a draft
should resolve and the nearby cases it must leave alone, before a person confirms it.

The standalone lab lives in `eval/rule_lab/`. It imports the real Engine,
Lifecycle, rule checks and Books through their existing interfaces and runs as a
separate process with in-memory SQLite stores. It does not change the main server
routes, rule store, fixtures, caches or project dependencies.

This review branch also adds a native Rule Lab section to the animated story and
app sidebar. See [the frontend integration guide](../../web/src/features/rule-lab/README.md)
for the live-service proxy and explicitly labeled saved-evidence mode.

## Run it

From the repository root with the project's Python 3.12 environment installed:

```sh
LLM_MODE=offline STORMCHECK_MODE=offline PYTHONDONTWRITEBYTECODE=1 \
  uv run python -m eval.rule_lab --serve
```

Open [the separate localhost viewer](http://127.0.0.1:4186/). Choose another port
with `--port 4187` if needed. The viewer binds only to `127.0.0.1`. It makes no model
calls and needs no API key. Stop it with Ctrl-C.

The command-line interface prints the same JSON evidence:

```sh
uv run python -m eval.rule_lab --preset scoped --check
uv run python -m eval.rule_lab --preset broader_scope --check
uv run python -m eval.rule_lab --preset missing_guard --check
uv run python -m eval.rule_lab --preset wrong_authority --check
```

With `--check`, the scoped candidate exits 0; the three deliberate mistakes exit 1.
Omit `--check` to inspect a blocked report without a failing exit status. The viewer's
**Export evidence** button downloads the full report in the browser. Neither entry
point saves evidence or modifies existing project files automatically.

## What it demonstrates

The original Q1 Claims Lead ruling says: “No signed acceptance, no offset: pay €600
cash; the voucher stays as goodwill.” Its first scope is EU departures. Removing
that boundary needs a separate authorized widening decision; the lab does not judge
whether the broader policy could eventually be justified.

| Scenario | Existing proposal checks | New regression pack | Outcome |
| --- | --- | --- | --- |
| Original scoped draft | Pass | 32 intended + 6 protected cases pass | Ready for human review |
| Remove EU-departure scope | Pass | Non-EU case is settled without a new ruling | Blocked |
| Remove unsigned-consent condition | Pass | Draft matches a signed voucher outside the ruling's intent | Blocked |
| Submit with agent authority | Author gate fails | Candidate simulation is not run | Blocked |

The consent mutation does **not** cause a bad payment in the existing engine: its
signed-acceptance handling already protects the €300 offset. The added pack catches
the rule's broader applicability while showing that the existing monetary defense
still holds. This is evidence of layered controls, not a claim of a vulnerability.

The passing report includes 51 checks: six existing proposal gates, 38 case checks,
five accounting checks and two isolation checks.

### Test cases and their oracle

- The original DUB–JFK case should move from `needs_ruling` to `owed`, with €600 cash
  entitlement and no unsigned-voucher offset.
- All 31 eligible next-storm coupons in the golden demo should settle with €250
  compensation each. The ruling automates voucher treatment; it does not turn every
  route into a €600 route.
- Six protected cases cover a non-EU departure, signed acceptance, no compensation
  voucher, a staff fare, 15-day notice and a weather cancellation.
- Four protected cases are explicitly labeled synthetic counterexamples. They are
  copies in memory, not edits to the fixtures. The other cases use existing golden
  demo data. No passenger names or source documents are returned by this viewer.

`oracle.py` contains fixed expected protected outcomes; `runner.py` selects golden
cases and the original/handoff amounts. **The draft under test does not generate or
rewrite its oracle.** Every candidate faces the same intent. This first version is
a curated executable pack; it does not claim automatic test generation for arbitrary
rulings or correctness on unseen data.

### Accounting evidence

The real Books implementation runs in a disposable ledger and checks:

1. Q1 alone preserves the whole-storm €82,146 estimate, including unresolved Legal
   cases. The separate Q2 Legal ruling is not applied in this experiment.
2. Repeating the same processing creates no duplicate journal entries.
3. Every journal entry balances.
4. An engine agent's journal approval attempt is rejected by Books.
5. No journal entry is approved by the lab.

`cash_cents` is compensation less a voucher offset, not a payout instruction. The
lab does not execute payments, confirm a policy, or write a production approval.

### Evidence binding

The export includes SHA-256 fingerprints for the candidate, golden world, curves,
runner/oracle pack, imported Engine/Books/contracts source and the complete report.
`report_sha256` hashes the report before that one field is added. The project hash
format is SHA-256 of sorted-key `orjson` JSON. Repeated runs produce identical
reports on identical sources. These checksums detect changed inputs; they are not
signatures, production certification, authentication, or proof against a malicious
local code change.

## How it fits the existing idea

Current flow, unchanged:

`human ruling → proposed rule → existing checks and preview → human confirmation`

Proposed future integration point:

`human ruling → proposed rule → existing checks → ruling-owned regression evidence → human confirmation`

The lab calls the real Lifecycle to obtain Q1's proposed rule, then evaluates an
active **copy** only inside scratch simulations. The stored proposal stays proposed.
There is deliberately no activation or approval endpoint. The original server does
not import this folder. Its behavior remains unchanged until the team chooses to
wire a reviewed regression gate into its confirmation boundary.

Next packs could cover Q2 Legal cause rules and Q3 Controller reserve releases.
Adding supplier invoice, delivery or credit-note cases would be a separate future
supply-chain pack; no procurement or bank functionality is added here.

## Validate

```sh
LLM_MODE=offline STORMCHECK_MODE=offline PYTHONDONTWRITEBYTECODE=1 \
  uv run pytest -p no:cacheprovider eval/rule_lab/tests
uv run ruff check --no-cache eval/rule_lab
uv run ruff format --check --no-cache eval/rule_lab
```

The existing root `eval.run --check`/v2 cache issue is outside this extension. Its
caches and metrics are intentionally unchanged; this lab is not a replacement for
the team's overall benchmark.
