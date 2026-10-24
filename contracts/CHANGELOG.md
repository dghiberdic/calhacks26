# contracts/CHANGELOG.md (additive-only; merge=union)

- v2 (plan commit, Sat 2026-10-24 ~01:00 PDT): models.py + interfaces.py generated verbatim from CONTRACTS.md §1–2; real METAR fixtures for Éowyn (EIDW 2025-01-23T18Z..2025-01-25T00Z) and Herminia (EIDW 2025-01-26).
- D0a (Sat 2026-10-24, david-b), additive only: `Rule.title: str | None = None` (card title); `StormRun.airports: list[Airport] = []` (map coordinates/tz/eu for every airport in `flights`); new API models for CONTRACTS §3 shapes that had none: `Health`, `StormSummary`, `SessionRequest`, `SessionResponse`, `ConfirmResponse`, `RejectRequest`, `PeriodRequest`, `MonthEndResponse`, `LockResponse` (`locked` = the period), `ClockRequest`, `ClockResponse`, `OkResponse`, `ErrorBody`, `ErrorEnvelope`. Added `contracts/stub_app.py`, `contracts/fixtures/api/*.json` and `contracts/openapi.json` (`make openapi`; a test fails if it is stale).

## Requests
<!-- other threads: append "- <name> <time>: <request>" here or in contracts/requests/<name>.md -->
