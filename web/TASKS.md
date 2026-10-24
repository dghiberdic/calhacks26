# web/ tasks (THREAD_JUSTIN.md)

| Task | Lane | Status |
|---|---|---|
| J0 Scaffold: Vite, Tailwind 4, shadcn, theme, shell + nav, role switcher (`POST /api/session`), time scrubber (`POST /api/clock`, `GET /api/clock`), typed client, `useStream()`, error boundary, `pnpm dev/build/test/e2e` | A | done |
| J0b Mock world typed from CONTRACTS.md (`src/mocks/`): every §3 route, writes included, golden numbers under test | A | done |
| J1 Storm Run | A | done |
| J2 Flight File (`/flights`, `/flights/:id`) | A | done |
| J3 Questions | A | done |
| J10 Docs: DEMO_SCRIPT, VIDEO, QA, README, DEVPOST | B | done (Devpost numbers fill from `eval/proof.json`) |
| J4 Policies | B | done |
| J5 Trace (Live · Commits · Blame · Access · Controls) | B | done |
| J6 Liability & Close | B | done |
| J7 Judge's Desk | B | done |
| J8 Proof | B | done (reads `/eval`; mock values until F9) |
| J9 Recorded mode + Vercel | B | done in code; recording waits for the server (CP3); preview deploys the mock world until then |
| J11 `/pitch` slides | B | done |
| `/story`: the scroll story on Éowyn (beyond the plan) | B | done |
| Switch off mocks: `pnpm gen:api`, CP1 against the stub, then the server | A | waiting on David (CP0a) |
| Record the demo (`pnpm record` against `make demo`) and redeploy | B | waiting on CP3 |

Tests: `pnpm test` (221 unit), `pnpm e2e` (51 in 1.6 min, including `e2e/demo.spec.ts`, the 3:00 script clicked end to end).
