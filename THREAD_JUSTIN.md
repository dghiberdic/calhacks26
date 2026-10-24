# Thread: Justin · Frontend, Pitch & Docs (v2)

**Mission:** make judges *see* it in 20 seconds. That means:
- 8 screens, with the storm timeline as the hero visual
- role sessions and a time scrubber
- a recorded build that can't go down
- `/pitch` slides
- the demo, video and Q&A scripts
- the README and the Devpost write-up

**Size:** ~30 agent-hours, run as **two lanes in parallel**. Each lane gets its own Claude Code session and git worktree:
- **Lane A** owns `web/src/app/`, `web/src/screens/{storm-run,flight-file,questions}/`, `web/src/components/`, `web/src/api/`, `web/package.json` and `pnpm-lock.yaml` (*only lane A edits deps*).
- **Lane B** owns `web/src/screens/{policies,trace,close,desk,proof}/`, `web/src/pitch/`, `web/scripts/`, `pitch/`, `demo/recorded/`, `README.md` and `DEVPOST.md`.

Lane B starts with `pitch/` and docs while lane A lands J0 (~02:00). **Branches:** `justin/a-<wp>`, `justin/b-<wp>`. Land with `scripts/land.sh`.

**Data sources:**
- **Before CP0a (01:45):** local mocks typed from `CONTRACTS.md`, in `web/src/mocks/`.
- **CP0a → CP1:** the stub, run with `make stub` (port 8001), reached via the Vite proxy (`/api → :8001`).
- **After CP1:** the real server on `:8000`.

**Never hard-code a number in a component.** Everything comes from the API or `demo/recorded/`.

## Stack (decided)
- Vite + React 19 + TypeScript + Tailwind 4 + shadcn/ui, pnpm
- TanStack Query
- `openapi-fetch` with types from `pnpm gen:api` (`openapi-typescript ../contracts/openapi.json -o src/api/schema.d.ts`, output committed)
- Recharts for charts
- **Storm timeline:** hand-rolled SVG with `d3-scale` (`scaleUtc`) + `motion`
- **Map:** a static SVG built with `d3-geo` and bundled Natural Earth 110m land (public domain), centred on Dublin. No tiles, no network, nothing to fail offline.
- SSE via `EventSource('/api/stream')` with resume. Fallback: poll `/api/trace?since=seq` every 2 s.
- Vitest + Playwright

## Visual language: Hyphenate's grammar, our skin
- **Do:**
  - **Status chips:** mono kebab-case, e.g. `weather · no-compensation`, `technical · owed`, `needs-ruling`, `ruling-cited`, `shadow`, `locked`.
  - **Feed rows:** past tense, ending `ID · €amount · STATUS`, with one reason line under each.
  - **Confidence:** always shown as `cause-finding confidence 91% · fault logged before storm`.
  - **Routing:** "Routed to the Claims Lead" with an initials avatar (CL / LG / CT), plus "Holds €600".
  - **Footers:** ↻ style, e.g. "↻ Next storm: 31 voucher cases settled, ruling cited".
  - **Actions:** [Edit][Approve] pairs.
  - **Labels:** micro-labels like "NOT YET POSTED · BUILT FROM 3 SOURCES" and "TIES TO GL 2140". Negatives in parentheses.
- **Don't:** use Hyphenate's crimson or orange, sand textures, Saans fonts, or the "INPUT NEEDED" flag. No dashboards of red flags ("homework"). **No "New rule" button, and no rule editor anywhere.** Never say "Input Needed".
- **Palette:** storm navy-slate base, cloud greys, cool blue for METAR/window, **amber = held**, **red only for "Not weather"**, green only for "ties to GL" / invariant ok.
- **Wording:** follow `IMPLEMENTATION_PLAN.md §9` exactly. Examples: "EU261 compensation liability", "no compensation; refunds and care still due", "172 payouts drafted, pending Claims Lead approval", "Decision stands."

---

## Lane A: core screens

### J0 · Scaffold (00:00–02:00)
- Vite app, Tailwind, shadcn, theme tokens.
- Shell with left nav: Storm Run · Flight File · Questions · Policies · Trace · Liability & Close · Judge's Desk · Proof · Pitch.
- **Role switcher:** calls `POST /api/session` and stores the token. Options: Claims Lead / Legal / Controller / Ops / CFO / Judge.
- **Time scrubber:** `POST /api/clock`.
- Typed API client, a `useStream()` SSE hook, and an error boundary that never shows stack traces.
- `pnpm dev | build | test | e2e`.

### J1 · Storm Run (home). Polish this first and most.
- **Static SVG map:** Dublin plus arcs to every destination, coloured by verdict (grey weather, red not-weather, amber held, slate operated).
- **Storm timeline:**
  - x axis: 18:00 the day before → 24:00 UTC
  - gust and sustained lines from METAR, with the raw METAR in a tooltip
  - window band(s) shaded cool blue, labelled with the definition
  - a tick per flight at STD (and STA for inbound/return sectors)
  - **solid ticks for the 11 operated departures, 15:30–17:30Z** ("everyone else flew")
  - a tech-log marker at 23 Jan 21:40Z
- **On load, animate:** all 27 cancelled ticks start as `71`. 23 turn grey, the 3 knock-on returns turn amber, and NS31 slides out of the band and turns red: **"Not weather. Broken plane." · `71 → 41`**.
- **Headline:** "5,292 passengers · 3 questions · 3 people", taken from `counters`.
- **Liability tiles:**
  - **NS31 €34,650 drafted** (not €0, not €99,000)
  - storm total
  - "172 payouts drafted, pending Claims Lead approval"
- **Learns strip:** four small cards (`self-learning` / `ai-automated` / `needs-review` / `new-policy`) from `StormRun.learned` and `questions`, with avatars, e.g. "Read 18 months of claims · 35% of owed long-haul passengers claim · takes the 50% reroute cut (41 of 42)".
- **Live feed:** `TraceEvent`s with chips.
- **Real-context strip:** "Dublin, 24 Jan 2025 · 179 departures (Eurocontrol) vs ~300 normal · ~119 cancelled (reported) · red warning 06:00–11:00".
- **Playwright:** the NS31 red tick, "€34,650", "71 → 41", and "5,292" are all visible.

### J2 · Flight File
- Verdict chip, reason line and `recode_label`.
- **Evidence ranked by trust tier**, with verbatim quotes. The losing source (OCC `71`) is struck through; the AMOS tech-log line is shown in mono.
- **Confidence:** feature bars, caps as separate chips, and "uncalibrated" when `score` is null.
- **Band margin:** e.g. "1,486 km · 14 km under the €400 band".
- Rules cited, linking to Policies. Entitlement summary.
- **JE card:** "NOT YET POSTED · BUILT FROM N SOURCES", with Dr/Cr lines.
- **Handoff row:** "32 refunds already initiated · not repeated · 32 corrected rights notices drafted · Drafter saw 0 PII".
- **Why?** and **Challenge** box. A challenge returns the classification chip plus a reply that starts **"Decision stands."**, or it creates a Legal question.
- **Flight timeline strip:** tech log → MCC → OCC → METAR marks → CRM.
- **Playwright:** "cause-finding confidence 91%", a struck evidence row, "NOT YET POSTED", and the challenge returns "Decision stands."

### J3 · Questions (role-scoped)
- **Lists:** open questions for the current role. One card covers a whole pattern (e.g. "3 flights").
- **Card layout:** **What it found / Why it flagged it / What it recommends**, with the recommended option **preselected**. Also shows evidence, confidence, holds and a reminder chip ("Waiting on Claims Lead 3h · reminder sent · N others settled", with N from the API).
- **PII:** visible only to Claims Lead; masked for Ops.
- **Answer flow:** choose an option and type an explanation, then the **rule preview** appears:
  - the DSL as a sentence
  - **grounding highlights** over the ruler's own words
  - the checks
  - "would change N past decisions · Δ€"

  Then **Confirm** → "Saved as policy · Never asked again".
- **Playwright:** Q1 is visible to claims_lead and not to ops; confirming shows "Never asked again".

---

## Lane B: remaining screens, recorded build, pitch and docs

### J10 · Docs first (until J0 lands)
- `pitch/DEMO_SCRIPT.md`: the 3:00 script from plan §4, with exact clicks and the words to say.
- `pitch/VIDEO.md`: a ≤3:00 storyboard that **opens on the moment** (0:00–0:35), plus how to record it (screen capture of the recorded build).
- `pitch/QA.md`: about 25 expected judge questions with crisp answers. Sources: plan §9–10, `research/blind_round/RESULTS.md`, the CPA wording, and the airline realism notes. Examples:
  - "Would the MEL allow dispatch?"
  - "Why not swap aircraft?"
  - "Where's the provision?"
  - "Why 35%?"
  - "Is the reduction capped at nil?"
  - "What does the LLM touch?"
- `README.md`:
  - how to run (`make demo`, `make demo-offline`, `make stub`)
  - architecture (2 Claude roles + 1 engine)
  - what's real / simulated
  - how to run the eval
  - **how each teammate sets their own Claude Code permission allowlist** for repo commands. This is optional and personal: each person changes only their own settings.
- `DEVPOST.md`: the write-up skeleton, filled with real numbers from `eval/proof.json` / `eval/NUMBERS.md` once they exist.

### J4 · Policies
- **Cards by origin:**
  - Learned (support "41 of 42")
  - Ruled (author and quote)
  - Rejected (the Controller's sentence)
  - Regulation, including the static card **"Reg (EU) 2026/2202 · in force 22 Oct 2026 · applies from 23 Oct 2027 · 9-month claim window"**
- Each card shows version history, status (`shadow` → `active`) and times cited.
- **Widen** (one rung, asked once) and **Revert** → a replay diff modal: "flips N · Δ€ · Jan locked, untouched".
- **Playwright:** nothing on the page matches `/new rule/i`.

### J5 · Trace (tabs: Commits · Blame · Access · Controls)
- **Commits:** hash prefix, kind (including `llm_call`), actor, message.
- **Blame:** a vertical chain, € → entitlement → rule@v → ruling quote → facts → span → METAR obs, using real quotes.
- **Access:** principals (people *and* agents) × resources; the denied log (`agent.drafter approve_payout → DENIED · SoD`); and a "view as Ops" PII mask.
- **Controls:** header **"SOC 2 is the floor"**, then the `/controls` mapping (CC6.1, CC6.3, CC7.2, CC8.1, PI1) with links to the evidence. Label it as a mapping, **not** a certification.
- **Playwright:** the blame chain ends in "METAR"; the denied log shows "DENIED · SoD".

### J6 · Liability & Close (Controller/CFO)
- **One CFO bridge:** "Cash basis €0 · full entitlement €99,000 · drafted €34,650 (±5pp ±€4,950)".
- **2140 rollforward** by cohort, with a `TIES TO GL 2140` chip.
- **Estimate card:**
  - header: pax · entitlement · curve LH-v1 · € basis · observed to M18 · n per point
  - expected-loss / **BF (selected)** / chain-ladder
  - A/E and credibility z
  - constraint note, tail vs. Steer 18%
  - preparer/approver
- **Claim curve chart:** expected vs. actual, by segment.
- **JE drafts** with [Edit][Approve]. Approving as the preparer shows **`DENIED · SoD`**.
- **Month-end** → "+€3,990 change in estimate". **Lock period.** **Invariants** list.
- **Playwright:** "DENIED · SoD" and "3,990".

### J7 · Judge's Desk
- **Inputs:** airport autocomplete (IATA/ICAO) and a **local** date → `POST /desk`. Render a compact Storm Run.
- **Errors:** a 422 shows its plain message (future date, no METAR, unknown airport). A day with no storm shows "max gust 18 kt · no storm window".
- **Inject panel:** a kind selector (tech_log / claim / crm / email / occ_log / manufacturer) with templated placeholders → submit.
- **Results:** the facts with quoted spans, the dropped count, the affected items and a streamed diff. Show `fallback_used` when it happens.
- **8 rehearsed scenarios** loaded from `GET /api/injections`.
- **Playwright:** all 8 render a result.

### J8 · Proof
- **Headline:** **"Plain Claude, 3 runs: €a / €b / €c. StormCheck: €34,650 ×3, same hash."**
- **Scorecard tiles:** straight-through %, miscodes caught (€), false holds, repeat questions 0, out-of-scope automated 0, liability vs. actual.
- **Reliability bins** per kind, each with n and Wilson error bars, plus coverage@0.9 and the honest label.
- Real vs. simulated columns.

### J9 · Recorded mode + Devpost URL
- `web/scripts/record.mjs` walks the demo script against the real server. It saves every GET response and the timed SSE log to `demo/recorded/`.
- `VITE_MODE=recorded` serves those files with no backend.
- Deploy to Vercel (Hobby). `make record` calls the script.

### J11 · `/pitch` slides
Slides in Hyphenate's 4-card grammar, in our colours:
1. **The business:** "An airline. The job: settle what every passenger is owed after each storm." `[€1.1B Irish carrier]` `[5,292 passengers, one storm]`. Learns / Runs / **Escalates (highlighted)** / Improves.
2. **Judged:** Real / Hireable / New / **Wow (highlighted)**. Real card: "Real Dublin weather, traffic and EU law; simulated logs, mess left in".
3. **Architecture:** Feeds → Facts (Reader) → Policies → Run (engine) → Trace. "2 Claude roles + 1 deterministic engine". "Sits on top of Altéa/Navitaire, NetLine, AMOS, Accelya; writes only parked journals."
4. **Real / simulated / how we know.**
5. **The CFO line,** and who doesn't need it ("a three-route charter").

**Seats line:** "StormCheck fills two seats at Northstar Air, the Passenger Claims Accountant and the Revenue Accountant, with one step between them: what really caused each cancellation. It drafts every payout and the EU261 compensation liability; the Claims Lead approves every payment."

**Playwright:** clicks through the whole demo script.

---

## Definition of done
- **CP1:** Storm Run renders from the **real** server, showing NS31 red, €34,650 and "71 → 41".
- **CP2:** every screen is live. Ruling → rule → replay is clickable. Desk works. Herminia shows "31 settled, ruling cited", and the BOS→DUB case asks.
- **CP3:**
  - the recorded build is on Vercel
  - the offline demo works
  - `/pitch`, DEMO_SCRIPT, VIDEO, QA, README and DEVPOST are done
  - the Playwright demo passes

## Agent rules
- Do J1 visually excellent before going broad. Commit after each task (`web: J1 storm timeline animation`) and land.
- **Never stop between tasks to ask.** Log judgment calls in `web/DECISIONS.md`. If stuck for more than 20 min, write `BLOCKED:` in `web/TASKS.md` and move on.
- If an endpoint is missing, build against the stub and log a request in `contracts/requests/justin.md`. Never edit `contracts/`, `engine/`, `server/`, `world/`, `llm/`, `books/` or `eval/`.
