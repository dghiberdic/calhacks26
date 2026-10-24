# web/ decisions (Justin's lanes)

Judgment calls, newest first within each task. One line each, with the why. Requests to other lanes are in
`contracts/requests/justin.md`.

## Across the app
- **Copy reads like a person who knows the job wrote it.** Justin's call (24 Oct): no words that sound generated. The learns strip's workshop tags from FINAL_IDEA (`self-learning`, `ai-automated`, `needs-review`, `new-policy`) show as plain ones: "from its own history", "overnight", "asks a person", "becomes policy"; the four steps (Learns → Runs → Escalates → Improves) stay. No rhetorical questions in headings.
- **SEO and link previews:** each route sets its own title ("NS31 · Flight File · StormCheck"); index.html carries Open Graph and Twitter cards with `og.jpg` (1200×630, the real Éowyn MODIS image with "Not weather. Broken plane.") and an Apple touch icon. Absolute URLs come from `SITE_URL`, else Vercel's production host.
- **J0 · Geist Mono for machine text; B612 Mono only as `font-cockpit`.** B612 sets ":" "," "." at the left of a full cell, so running text read "09: 00Z" and "€227, 000". The Airbus cockpit face stays for display imitations (the split-flap board).
- **J0 · Money and clocks in prose use tabular Archivo (`.figure`).**
- **J0 · Colour discipline is code.** `components/chips.tsx` tones: red only for "Not weather", green only for ties-to-GL and invariant ok, amber for held and asked, cool blue for METAR and the window. Denials are ink, not red.
- **J0 · One typed client, three transports.** `http` (Vite proxy → stub :8001 or server :8000), `mock` (in-memory world typed from CONTRACTS.md, `src/mocks/`), `recorded` (demo/recorded/, J9). Picked by `?api=`, then `VITE_API_MODE`, then the Vite mode (`vite --mode mock`, `vite build --mode recorded`). The root .gitignore drops `.env.*`, so no mode file is needed.
- **J0 · Hand-written `src/api/types.ts` until `contracts/openapi.json` exists.** It mirrors `contracts/models.py` field for field; defaulted fields are optional, as openapi-typescript will emit them. `pnpm gen:api` replaces it at CP0a. Additive fields we asked for are marked in place.
- **J0 · SSE fallback.** `EventSource('/api/stream')` resumes via Last-Event-ID; after 3 failed reconnects it polls `/api/trace?since=seq` every 2 s. A burst of events causes one refetch (350 ms debounce).
- **J0 · Screens show server-scoped data; the stream only refetches.** Storm Run's "What it did" is the storm's own `run.feed`; the whole live trace, every storm, is Trace's Live tab.
- **J0 · Storm names come from `real_context.name`,** falling back to a static lookup (`src/lib/storms.ts`). Names aren't numbers; every count and € comes from the API.
- **J0 · The time scrubber shows the server's known-at** (`GET /clock`, additive) and falls back to what this tab set.
- **J0 · The storm selector follows the page:** `/run/:id`, `/flights?storm=`, or a flight's own date.
- **J0 · Tests:** Playwright uses the installed Chrome; it runs against the mock world by default (`E2E_API_MODE=http` for the stub or server). Vite crawls every screen for dependencies at startup, so a cold run never reloads mid-test.
- **Art · The A321 renders, line art and `a321.glb` were re-made in Blender with the registration EI-NSB.** The decal read EI-NSA; NS31 is EI-NSB (plan §1.3).

## J0b · Mock world
- Storm windows stay in time order, as the engine will return them; screens pick the story's window with `mainWindowOf()` (the longest).
- The clock starts at 25 Jan 09:00Z, so Q1 already shows "reminder sent" after a reset. The books are shown at the Feb close with January locked, so every golden number is visible without moving the clock.
- Herminia (my design): NS112 DUB–LIS was miscoded 71 and carries the 31 unsigned vouchers; NS30 BOS→DUB carries the one voucher that doesn't depart the EU.
- Judge's Desk: airports other than Dublin's demo days run on generated METAR, every line marked `RMK MOCK`. Injections are read by regex but labelled the way the real Reader labels things.
- Operated flights carry a placeholder decision (cause "unknown"), so screens key off `flight.status` first.

## J1 · Storm Run
- The headline's three counts sit on one line on a laptop and stack on a phone; a line never starts with a dot.
- "Not weather. Broken plane." lands once the timeline has settled (about 4 s), beside the story rather than over the chart.
- Phones pan the timeline, opening on NS31, instead of squeezing 30 hours into 350 px.
- Route map labels are placed greedily, most serious verdict first, away from the hub; whatever doesn't fit shows on hover.

## J2 · Flight File
- The server's own wording first (`status_line`, `band_label`, `claim_rate_label`, …); plan §9 wording when a key is missing.
- Operated flights get a slate chip and no confidence card or challenge box.
- Confidence feature bars pick their form from the values: flags show yes/no, measures show units, weights get diverging bars.

## J3 · Questions
- The recommended option is preselected; the explanation box starts empty, so the words are the ruler's.
- Rejecting Q3 goes through `answer` when the server offers a "Reject: …" option; `/rules/{id}/reject` is used only when the UI has to add the option for a modelled proposal.
- Server-raised follow-ups (BOS→DUB, "All storm cohorts?") appear as their own cards; the UI never adds an ask.

## J4 · Policies
- Rulings about releases (kind release, keep-tail or deny-release actions) count as Rejected; other rulings as Ruled.
- The newest active version is in force; a newer shadow version (from Widen) shows as pending with Review.
- Each card's id is its versioned ref, so `/policies#R-CL-1@1` lands on it.

## J5 · Trace
- A Live tab (the default) shows the whole trace, every storm, merged with the stream.
- `?target=` opens blame for a flight, entry or rule (a question opens its events) and filters Live to it.

## J6 · Liability & Close
- Rollforward reductions always show negative, whichever sign the API stores. Integrity checks are shown only when true; a failure is stated with its amount.
- Locked periods are inferred from LOCKED events, `period_lock` commits and the locked-period invariant until the API has a field (request 16).
- The close rail moves under the rollforward below 1400 px, so the Total column never scrolls away.

## J7 · Judge's Desk
- Autocomplete uses a bundled table of about 230 airports (codes, names, time zones); anything outside coverage gets the server's plain 422.
- Future dates are dimmed but can be typed; the server stays the judge.
- The METAR chip says "real METAR" only when `real_context.metar_source` says so, and "mock METAR" for `RMK MOCK` lines.
- The run and the last injection live in a store, so they survive navigating away mid-demo; the URL names the day but never auto-runs it.

## J8 · Proof
- Plain-Claude runs that land exactly on the cash basis or the full entitlement are named as such on the dot plot.

## J9 · Recorded mode
- The recorder posts the plan's scripted texts character for character: LLM calls are cached by exact input.
- The Vercel build ships the recorded demo once `demo/recorded/` exists, and the mock world until then; the sidebar says which.

## J11 · /pitch
- The deck waits up to 1.6 s for fonts and the API's figures before a slide lays out, so a cold open never shifts (it did on three slides).
- The cover is a fresh NASA GIBS MODIS Terra export of 24 Jan 2025 at 3840×2160 with the colour grade baked in; its clouds turn counter-clockwise about the low in WebGL while land and sea stay still, and a slow GPU gets half resolution, then the still.
- Eyebrows dropped "example ·"; every slide's rendered text is checked in e2e against the banned-words list (no generated-sounding words, em dashes, "!", "AI" as a selling word or rhetorical questions).
- The seats line sits on the cover. The Business slide's footer carries no number until the API counts cases settled by a cited ruling (request 6).
