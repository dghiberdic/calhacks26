# Requests from Justin (web/)

Additive only, per CONTRACTS.md. The UI works without each of these today (fallbacks noted), but every
fallback is either a static table or a number the UI can't get from the API, which the plan forbids.

| # | Request | Why | UI fallback until then |
|---|---|---|---|
| 1 | `GET /api/airports` → `list[Airport]` (the World's airports, plus anything `WorldAPI.airport()` resolves) | Judge's Desk autocomplete (IATA/ICAO/name), and coordinates for the static route map | a bundled reference table in `web/src/lib/airports.ts` (names + coordinates only) |
| 2 | `GET /api/clock` → `{"known_at"}` | The time scrubber has to show the current known-at after a reload; today it only knows what this tab set | shows "server clock" until the first `POST /clock` |
| 3 | `StormRun.name: str \| None` (e.g. "Storm Éowyn") — or `real_context.name` | The storm's name in the shell and on Storm Run | a static name lookup by station-day in `web/src/lib/storms.ts` |
| 4 | `Question.others_settled: int = 0` (cases the same pattern settled automatically since it was asked) | The reminder chip: "Waiting on Claims Lead 3h · reminder sent · N others settled", with N from the API (THREAD_JUSTIN J3) | chip shows "reminder sent" without N |
| 5 | `FlightFile.entitlements_summary` keys documented: `full_entitlement_cents`, `drafted_liability_cents`, `claim_rate`, `coupons`, `elections` | Storm Run's "€34,650 drafted: not €0, not €99,000" tile and the Flight File summary read them | reads `CfoMetrics` (`/books/cfo`) for the hero cohort |
| 6 | `Rule.cases_settled_by_storm: dict[str, int] = {}` (or a count on `/rules`): cases each storm settled by citing this rule | `/pitch` business slide footer: "Next storm: 31 voucher cases settled, ruling cited", with 31 from the API | the footer reads "cases like hers settle on their own, ruling cited" with no number |
| 7 | `/desk` runs carry `real_context.metar_source` ("IEM asos.py (real)", "AWC (real, last 30 days)") | The desk's METAR chip says "real METAR" only when the API says so | the chip says "METAR" with no claim either way |
| 8 | Define `InjectResponse.fallback_used`: true only when the Reader timed out or failed and the labelled regex fallback ran (not "extracted nothing") | The desk shows "Reader timed out; used the labelled regex fallback" off this flag | the mock sets it when nothing was extracted |
| 9 | Type `FlightFile.timeline` items (`{at, kind, label, source_id}`) and list the `kind` values (tech_log, mcc, occ, metar, crm, …) | The Flight File timeline strip places and colours marks by kind | marks are read loosely (`TimelineMark` has an index signature) |
| 10 | Document every `entitlements_summary` key the UI reads, beyond #5: `status_line`, `band_label`, `claim_rate_label`, `full_entitlement_label`, `statuses`, `compensation_breakdown`, `reduction_7_2` | The Flight File money card prints the server's own wording first | falls back to plan §9 wording when a key is missing |
| 11 | Map a release-proposal question to its proposed rule: `Question.proposal_rule_id: str \| None` | Q3's "Reject" posts `/rules/{id}/reject` with the right id | the UI answers with the server's "Reject: …" option instead |
| 12 | Say whether `Confidence.features` holds raw inputs or contributions (weights) | The confidence card draws flags as yes/no, measures with units, weights as diverging bars | the card guesses from the values |
| 13 | `Rule.origin_quote: str \| None` (the ruler's words), or the ruling step with its quote in `/blame?target=<rule@v>` | Policies' Ruled/Rejected cards show the person's own words with the grounded phrases lit | the card shows the grounding phrases alone |
| 14 | `/rules/{id}/widen` returns `widen_next` with its `question` text ("All storm cohorts?") | The widen dialog names the next rung in words | falls back to "drop <condition>" |
| 15 | `Commit.recorded_at: ISODateTime \| None` (when the commit was written, beside the event time) | The commit log shows both times | each row shows its own date |
| 16 | Period lock state: `Rollforward.locked: bool` or `GET /books/periods` | Liability & Close shows "Jan 2025 locked" and gates Lock | inferred from LOCKED trace events and `period_lock` commits |
| 17 | `POST /books/month-end` is idempotent per period (a second call returns the first draft) | A presenter can click month-end twice on stage | the mock already behaves this way |
| 18 | `je_ids` on rollforward rows | The "J" (agrees with its journals) check is exact | matched by journal kind |
| 19 | `CfoMetrics.cohort: str` | The CFO bridge says which cohort it describes | treated as the hero storm's NS31 cohort |

## Open questions (the demo script hedges on these until answered)

| # | For | Question | What the UI/docs assume now |
|---|---|---|---|
| Q-a | David | Which roles may `POST /flights/{id}/challenge`? The access matrix doesn't list it. | Any session, the Judge included (the demo opens it as the Judge, Ops as fallback) |
| Q-b | David | Is Q1 already 3 h old in the seeded world (so "reminded 3h" shows after `POST /reset`), or does the presenter scrub the clock forward 3 h? | The demo checklist scrubs +3 h only if rehearsal shows it's needed |
| Q-c | David | Plan §1.3 says "weather at 21:40Z: 13 kt, no gust"; the committed METAR has 13 kt at 21:00Z and 14 kt at 21:30Z. | The UI shows the raw METAR nearest the tech-log time and the docs quote no speed |
| Q-d | Filip | Judge's Desk on an EU airport (e.g. AMS): both directions depart the EU, so no case can "ask again" the way BOS→DUB does. Should the desk beat show a non-EU departure (e.g. LHR→DUB, 21 Jan 2024) instead? | The script reads the count and the asking case off the screen |
