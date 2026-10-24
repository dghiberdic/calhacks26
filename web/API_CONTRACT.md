# StormCheck UI ⇄ engine contract (proposal)

The web app in `web/` currently runs on fixtures (`web/src/data/*.ts`) shaped exactly like this.
If the engine serves these endpoints, the UI swaps the fixtures for `fetch` calls and nothing else changes.
Times are UTC (`"21:30"`, ISO for full timestamps). Money is integer euros.

Every response that contains a decision carries the same three things the UI shows everywhere:
`confidence`, `evidence[]`, and `rules[]` (id **and version**). That is what powers "Why this €?".

## GET `/api/storms/:stormId`
```json
{ "id": "bram-2025-12-09", "name": "Storm Bram", "date": "2025-12-09", "station": "EIDW",
  "window": [{ "start": "13:30", "end": "19:00" }], "gustLimitKt": 40,
  "recheckedAt": "2025-12-10T09:00:00Z",
  "totals": { "cancelled": 14, "weather": 13, "owedFlights": 1, "passengers": 2910,
              "exposure": 127200, "provision": 44520, "openQuestions": 3 } }
```

## GET `/api/storms/:stormId/flights`
```json
[{ "id": "NS31", "dest": "BOS", "city": "Boston", "sched": "21:30", "reg": "EI-NSA", "type": "A321neo",
   "pax": 212, "km": 4802, "opsCode": { "code": 71, "label": "WX", "by": "OCC", "at": "08:12" },
   "verdict": "technical",            // weather | technical | extraordinary | review
   "owed": true, "perPax": 600,
   "confidence": 91, "runnerUp": { "cause": "weather", "share": 9 },
   "decisionId": "d-7f3a19" }]
```

## GET `/api/flights/:id`
The side sheet. Everything above, plus:
```json
{ "timeline": [{ "t": "07:55", "kind": "fault", "label": "HYD G leak" },
               { "t": "21:30", "kind": "departure" }],
  "evidence": [{ "source": "tech_log", "at": "07:55", "ref": "EI-NSA ATL p.412 ATA 29-11",
                 "quote": "HYD G RSVR LO LVL. LEAK FOUND AT ENG 1 EDP CASE DRAIN LINE.", "rank": 1 },
               { "source": "metar", "at": "21:30", "quote": "EIDW 092130Z 23017G30KT …", "rank": 2 },
               { "source": "ops_code", "at": "08:12", "quote": "71 WX", "rank": 3, "overruledBy": "R-2@1" }],
  "rules": [{ "id": "R-3", "version": 2 }, { "id": "R-4", "version": 1 }],
  "payouts": { "count": 212, "each": 600, "status": "held" },
  "provision": { "amount": 44520, "claimRate": 0.35, "ruleId": "R-6", "ruleVersion": 4 } }
```

## GET `/api/trace?entity=provision:NS31` · `payout:NS31-041` · `je:JE-2041`
The "Why this €?" receipt, top (amount) to bottom (who ruled):
```json
{ "amount": 44520, "steps": [
  { "label": "Exposure × claim rate", "value": "€127,200 × 35%", "rule": "R-6@4" },
  { "label": "Passengers × tier", "value": "212 × €600", "rule": "R-4@1", "note": "4,802 km" },
  { "label": "Cause", "value": "Technical fault", "rule": "R-3@2" },
  { "label": "Tech log", "value": "07:55Z · ATA 29-11", "quote": "HYD G RSVR LO LVL…" },
  { "label": "Weather", "value": "13:30–19:00Z", "quote": "METAR window, gust ≥ 40 kt" },
  { "label": "Who ruled", "value": "Legal", "at": "2026-03-12" } ],
  "journalEntry": "JE-2041", "decisionId": "d-7f3a19",
  "asOf": "2025-12-10T09:00:00Z" }
```
Optional: `?asOf=<iso>` replays with the rule versions known then (powers a "before R-7" toggle).

## GET `/api/payouts?storm=bram-2025-12-09&flight=NS31&status=held&cursor=…`
Sorted for work (asked → held → drafted → not owed), 50 per page:
```json
{ "items": [{ "id": "NS31-042", "name": "Aoife Byrne", "flight": "NS31", "amount": 600,
              "status": "asked", "rule": "R-3@2" }],
  "counts": { "all": 2910, "held": 211, "asked": 1, "notOwed": 2698 }, "next": "…" }
```
`id` must be stable: the auditor's link carries it (`/app/payouts?flight=NS31&why=NS31-042`, or
`/app?why=provision&flight=NS31` for the provision), never a name.
`POST /api/payouts/approve` `{ "ids": [...] | "all-held", "by": "claims-lead" }` → `{ "queued": 211 }`.
It queues for Payments; no money moves.

## GET `/api/questions` → POST `/api/questions/:id/answer`
```json
{ "id": "Q-12", "title": "Offset a gate voucher?", "owner": "claims-lead",
  "why": "Voucher disputes on EU-departing flights are yours.",
  "confidence": 39, "reason": "sources disagree",      // | no precedent | needs approval
  "held": 600, "question": "The CRM says …",
  "evidence": [{ "source": "crm", "at": "…", "quote": "…" }],
  "answers": [{ "id": "no-offset", "label": "No signed acceptance, no offset.", "effect": "Pay €600",
                "delta": 0, "rule": { "id": "R-7", "version": 1, "sentence": "…",
                "grounding": { "signed acceptance": "No signed acceptance" }, "scope": "EU departures",
                "replay": { "pastChanged": 0, "openApplied": 31 } } }] }
```
`POST` body: `{ "answer": "no-offset", "by": "claims-lead", "text"?: "free-text ruling" }`
Response: `{ "rule": { …R-7@1 }, "settled": 31 }`. **Never asks twice:** the same pattern later returns
`answeredBy: "R-7@1"` instead of creating a question.

## GET `/api/rules`
`[{ "id", "version", "title", "sentence", "source": "law|ruling|policy|learned", "sourceLabel", "scope",
"applied", "asked", "updated", "history": [{ "version", "when", "change", "by" }] }]`

## GET `/api/ledger`
`{ "provision": {…}, "claimCurve": [{ "month": 0, "expected": 0, "filed": 0 }], "journal": [{ "id", "when", "memo",
"status": "drafted|held|posted", "source": "R-3@2 · R-6@4", "lines": [{ "account", "dr"?, "cr"? }] }] }`

## POST `/api/desk/check` (the judge's desk)
`{ "station": "EIDW", "date": "2025-12-09", "sched": "21:30", "pax": 212, "km": 4802, "log": "07:55Z HYD G …", "gustLimitKt": 40 }`
→ `{ "window": [...], "verdict", "owed", "confidence", "reasons": [string], "rules": [...], "routeTo"?: "Legal" }`
The UI already has a live METAR proxy at `GET /api/metar?station=EIDW&date=2025-12-09&limit=40` and a
deterministic stand-in in `web/src/lib/engine.ts`; the engine can replace it.

## Roles (least privilege)
Every endpoint accepts `X-Role: claims-lead | legal | controller | ops`. For `ops`, passenger names and
claim emails come back redacted (`"Passenger 041"`); the UI already renders that state.
