# web/ decisions (Justin's lanes)

Judgment calls, newest first. One line each, with the why.

- **J0 · Vite replaces the overnight Next.js prototype.** The plan's stack is decided (Vite + React 19, served from `web/dist` by `make dev`/`make demo`). Design tokens, type, the line-art/render assets and the screenshot tool were ported; the prototype stays on the `justin/ui` branch of the fork.
- **J0 · Hand-written `src/api/types.ts` until `contracts/openapi.json` exists.** It mirrors `contracts/models.py` field for field; defaulted fields are optional, as openapi-typescript will emit them. `pnpm gen:api` replaces it at CP0a; screens import from `@/api/types` either way.
- **J0 · One typed client, three transports.** `http` (Vite proxy → stub :8001 or server :8000), `mock` (in-memory world typed from CONTRACTS.md, `src/mocks/`), `recorded` (demo/recorded/, J9). Picked by `?api=`, then `VITE_API_MODE`, then the Vite mode (`vite --mode mock`, `vite build --mode recorded`; the root .gitignore drops `.env.*`, so no mode file is needed), so the same build can be checked against any of them.
- **J0 · SSE fallback.** `EventSource('/api/stream')` resumes via Last-Event-ID; after 3 failed reconnects it polls `/api/trace?since=seq` every 2 s. Bursts of events cause one refetch (350 ms debounce).
- **J0 · Storm names are a static lookup (`src/lib/storms.ts`).** The contract has no name field; names aren't numbers, every count and € still comes from the API.
- **J0 · Playwright uses the installed Chrome (`channel: "chrome"`).** No browser download; the e2e suite runs against the mock world by default, `E2E_API_MODE=http` for the stub/server.
- **J0 · Colour discipline is code.** `components/chips.tsx` tones: red only for "Not weather", green only for ties-to-GL/invariant ok, amber for held/asked, cool blue for METAR/window. Denials are ink, not red.
- **J0 · Money and clocks in tabular Archivo (`.figure`), machine text in B612 Mono.** B612 sets ":" and "," at the left of a full cell, which reads "€34, 650".
