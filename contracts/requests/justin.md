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
