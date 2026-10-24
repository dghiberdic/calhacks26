# STATUS (one line per lane; update hourly; merge=union)

| lane | time (PDT) | last task done | next | blocked? |
|---|---|---|---|---|
| david-a | | | D1 | |
| david-b | 10:45 | D0b (golden world, expected/, fields/parse/normalize, calibration, fakes, api fixtures) + D11 (make dev/demo/demo-offline/verify/record, smoke-1/2/3; CP1 smoke 12/12 green) | CP2/CP3 smoke go green as server D10b/c lands | no |
| filip-a | | | F1 | |
| filip-b | | | F8a | |
| justin-a | 15:59 | CP1 on the D10a real server (43/46 e2e, 3 skip by design); plain copy pass; per-route titles + Open Graph/Twitter cards (og.jpg) | e2e re-run after the /story + /pitch merge; record at CP3 | Q-e (171 vs 172 drafted); requests 20–21 |
| justin-b | 15:59 | /story: real Meteosat IR loop of Éowyn (© EUMETSAT) on one clock with ERA5 isobars + wind, 4K render, every beat moves at 60 fps; /pitch: 4K cover with clouds turning about the low, slides build in, copy check in e2e | Q&A/video | PR #5 (contracts/requests) waiting to merge |
| filip-b (llm) | Sat 11:05 | F5 Reader on contracts fields/parse/normalize (29 recordings) | F7 personas | no (F6, F8b, F8c moved to other agents) |
| justin-a | 15:59 | CP1 on the D10a real server (43/46 e2e, 3 skip by design); plain copy pass; per-route titles + Open Graph/Twitter cards (og.jpg) | e2e re-run after the /story + /pitch merge; record at CP3 | Q-e (171 vs 172 drafted); requests 20–21 |
| justin-b | 15:59 | /story: real Meteosat IR loop of Éowyn (© EUMETSAT) on one clock with ERA5 isobars + wind, 4K render, every beat moves at 60 fps; /pitch: 4K cover with clouds turning about the low, slides build in, copy check in e2e | Q&A/video | PR #5 (contracts/requests) waiting to merge |
| filip-a | Sat 11:40 | PR #6: F3d WorldAPI, shared F3c integration, 140 supplemental inputs, F9 proof, Q1/Q2/Q3 replay, Books limitation guard | live baseline and calibration promotion follow-up | API key unavailable; fitted confidence rejected by unchanged acceptance gate |
| filip-b (llm) | Sat 11:05 | F5 Reader on contracts fields/parse/normalize (29 recordings) | F7 personas | no (F6, F8b, F8c moved to other agents) |
| filip-a | | | F1 | |
| filip-b (llm) | Sat 11:40 | F7 personas (stretch) + F5 on contracts fields/parse/normalize | queue done | no (F6, F8b, F8c moved to other agents) |
| justin-a | 15:59 | CP1 on the D10a real server (43/46 e2e, 3 skip by design); plain copy pass; per-route titles + Open Graph/Twitter cards (og.jpg) | e2e re-run after the /story + /pitch merge; record at CP3 | Q-e (171 vs 172 drafted); requests 20–21 |
| justin-b | 15:59 | /story: real Meteosat IR loop of Éowyn (© EUMETSAT) on one clock with ERA5 isobars + wind, 4K render, every beat moves at 60 fps; /pitch: 4K cover with clouds turning about the low, slides build in, copy check in e2e | Q&A/video | PR #5 (contracts/requests) waiting to merge |
| filip-b2 (books agent) | Sat | F8b postings + F8c invariants / CFO / audit, golden-exact vs expected/ | (queue done) | no |
| filip-a (F3d finish agent) | Sat 13:00 | F3d judge day: airport-local day, METAR across every needed hour, plants re-simulated (DUB fault, no extras), BOS→DUB context on EU days, `.json.gz` load, CPU-time timing tests | — | no |
