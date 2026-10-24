# Demo script · 3:00 live

The live demo from `IMPLEMENTATION_PLAN.md` §4, with the clicks and the words. Screen names follow §3 of the plan. Where the build's button labels differ from this file, the build wins; fix this file after the first full rehearsal.

Two rules on stage:
- **Say only numbers that are on screen.** The golden ones (5,292 passengers, 172, €99,000, €34,650, €82,146) are asserted by tests. Everything else comes from the API.
- **Use the §9 wording:** "EU261 compensation liability" (never "provision"), "drafted, pending approval" (never "booked" or "paid"), "service-desk voucher", "cause-finding confidence 91%", "no compensation; refunds and care still due".

## At a glance

| t | Screen | Role | Beat |
|---|---|---|---|
| 0:00 | Storm Run | Judge | Northstar, two seats, one step between them |
| 0:10 | Storm Run | Judge | All 27 coded weather. NS31: "Not weather. Broken plane." 71 → 41. €34,650 |
| 0:35 | Flight File (NS31) | Judge | Struck 71, CRM-bot handoff, Challenge → "Decision stands." |
| 1:00 | Questions | Claims Lead | Q1 voucher, 39% · sources disagree → rule → "Never asked again" |
| 1:25 | Questions | Legal | One question, three flights → 3 settled, cited 3× |
| 1:40 | Questions → Liability & Close | Controller | Reject the Isha release → rule → "All storm cohorts?" · TIES TO GL 2140 |
| 2:00 | Judge's Desk | Judge | "Name an airport and a date." Miscode caught, voucher rule cited |
| 2:35 | Proof | any | Plain Claude ×3: three numbers. StormCheck ×3: same hash |
| 2:50 | Storm Run | any | Human runtime → drafted by morning → who doesn't need it |

Who speaks and who drives isn't decided. Suggested: one voice, one driver, and the third person takes Q&A on what they built (engine, rules and trace: David; books, eval and the Claude roles: Filip; product and UI: Justin). Answers are in `pitch/QA.md`.

---

## Before you start

### 30 minutes before

**Machine**
- [ ] Demo laptop on the demo tag: `git checkout v1.0-demo`. Charger in. `caffeinate -d` running in a terminal.
- [ ] Do Not Disturb on. Slack, Mail and Messages quit. Dock hidden.
- [ ] Spare laptop on the same tag, with every step below done. Phone hotspot ready.

**Server**
- [ ] `uv sync`, then `cd web && pnpm i && pnpm build`. `make demo` serves `web/dist`, so build it first.
- [ ] Start one of:
  - `make demo`: one process on :8000, API and web. The default.
  - `make demo-offline`: no network, pinned METAR, `LLM_MODE=offline`. Use it if the venue network is unreliable; it must pass with wifi off. The Judge's Desk then only knows pinned station-days, so check `data/pinned/` and have two ready.
- [ ] `curl -s localhost:8000/api/health` returns `ok`, the `mode` you expect, and real `impl`s, not fakes.
- [ ] `make verify` is green ("N commits verified · replay identical"). Note N for Q&A.

**Browser**
- [ ] Chrome with a clean profile: no extensions, bookmarks bar hidden (Cmd+Shift+B), full screen (Cmd+Ctrl+F).
- [ ] Zoom: start at 100%. On Storm Run the headline, the whole storm timeline and the liability tiles must fit without scrolling. Go to 110% only if they still fit. Use the same zoom in every tab.
- [ ] Reduce motion is off (System Settings → Accessibility → Display), or the Storm Run animation won't play.
- [ ] Tab 1: `http://localhost:8000`, on Storm Run. Tab 2: the recorded build, `{{links.recorded_build}}` (no backend). Nothing else open.
- [ ] The video, `stormcheck.mp4`, on the desktop.

**Roles** (check once in this build)
- [ ] The role switcher lists Claims Lead, Legal, Controller, Ops, CFO and Judge.
- [ ] As Judge, Storm Run shows €34,650 and the Challenge box on the Flight File takes text. `CONTRACTS.md` doesn't fix which roles may challenge. If this build hides either from Judge, run 0:00–1:00 as Ops instead.
- [ ] As Claims Lead, the Q1 card shows "Waiting on Claims Lead 3h · reminder sent". If it doesn't after a reset, move the time scrubber forward 3 h before each run (the clock only goes forward; a reset undoes it).

**Rehearse**
- [ ] One full run with a stopwatch. Hit each start time within 5 s. If you're late, cut words, not beats.

### Before every judge group
- [ ] Reset: `curl -s -X POST localhost:8000/api/reset` → `{"ok":true}`. Reload Tab 1.
- [ ] If rehearsal showed the reminder chip needs it: time scrubber forward 3 h.
- [ ] Role switcher on Judge (the default with no token).
- [ ] The Storm Run headline reads "5,292 passengers · 3 questions · 3 people".

### Paste, don't type

LLM calls are cached by their exact input, so the rehearsed path only replays if the text is identical. Copy these from `web/scripts/record.mjs` (the recorded run) into a text expander or clipboard manager. One different character, such as a hyphen for "−" or an "x" for "×", misses the cache: under `make demo` that means a live Claude call (slower), and offline it means a template fallback.

| Snippet | Paste into | Text (plan wording; `record.mjs` is the source of truth) |
|---|---|---|
| `;ch` | Flight File → Challenge | The storm would have grounded it anyway |
| `;q1` | Questions (Claims Lead) → explanation | No signed acceptance, no offset: pay €600 cash; the voucher stays as goodwill. |
| `;q2` | Questions (Legal) → explanation | A return sector of a storm-cancelled rotation is extraordinary only if no aircraft and crew could operate it within 3 h of STD, and passengers were offered the earliest reroute on any carrier (C-74/19). |
| `;q3` | Questions (Controller) → explanation | Never release the tail. At M12 keep (ultimate − M12 rate) × entitlement until the six-year limitation. |

The challenge text is also in `contracts/fixtures/injections/07_challenge_storm_anyway.json`.

---

## The run

### 0:00 · Storm Run · Judge

**Clicks:** none. Storm Run is already loaded. At about 0:08, press Cmd+R so the load animation plays under the next line.

**Say:**
> "Northstar Air: a fictional €1.1B Irish airline. Two seats, the claims and revenue accountants, and one step between them: what really caused each cancellation."

**If it breaks:** the page is blank or shows an error. Switch to Tab 2 and say once, "Same build, recorded run." Carry on from this beat.

### 0:10 · Storm Run · Judge (the moment)

**On screen:** all 27 cancelled flights start as `71`. The METAR gust and sustained lines and the cool-blue window band (02:30–15:00Z) are drawn. 23 ticks turn grey, the 3 knock-on returns turn amber, and NS31 slides out of the band and turns red: "Not weather. Broken plane." · `71 → 41`. The 11 departures that operated 15:30–17:30Z are solid ticks. The tech-log marker sits at 23 Jan 21:40Z.

**Clicks:**
1. Let the animation finish. Touch nothing until NS31 is red.
2. Hover the red NS31 tick.
3. Move to the NS31 liability tile (€34,650 drafted), then to the payouts tile. Read the count off the screen: 171 on the real engine, because 14C waits on her ruling.

**Say:**
> "At 5 a.m., operations coded all 27 'weather'. The METAR says Dublin's storm was over by 15:00, and everyone else flew. NS31's plane broke the night before, with no MEL relief. Not weather. Broken plane. Seventy-one becomes forty-one.
> €34,650, at a 35% expected ultimate claim rate: not €0, not €99,000. 172 passengers owed: 171 payouts drafted, pending Claims Lead approval, and 14C waits on her ruling."

**If it breaks:**
- The animation didn't run: don't reload again. Narrate the end state; it's the same story.
- A number differs from this script: the state wasn't reset. Don't fix it live; switch to Tab 2.

### 0:35 · Flight File (NS31) · Judge

**Clicks:**
1. Click the red NS31 tick (or its red arc on the map). The Flight File opens for `NS31@2025-01-24`.
2. Point at the verdict chip (`technical · owed`) and "cause-finding confidence 91% · fault logged before storm".
3. Point at the evidence: the AMOS tech-log line in mono, ranked first, and the OCC `71`, struck through. If the struck row is below the fold, scroll once before you speak.
4. Point at the handoff row: "32 refunds already initiated · not repeated · 32 corrected rights notices drafted · Drafter saw 0 PII".
5. Click the Challenge box, paste `;ch`, submit.
6. The reply starts "Decision stands.", with the `assertion` chip and the cited evidence.

**Say:**
> "NS31's file. The tech log outranks a 5 a.m. batch code, so the 71 is struck. The CRM bot had already refunded 32 passengers: not repeated, and their 'weather, no compensation' emails get 32 corrected rights notices. The Drafter saw zero PII. Now I'll push back."
>
> *[paste, submit]*
>
> "Decision stands. It cites the METAR, the eleven departures that flew, and the fault logged before the storm."

**If it breaks:**
- No reply after 5 s: say "It's classifying the challenge," give it 5 more seconds, then move on. Show rehearsed scenario 07 on the Judge's Desk during Q&A.
- It routes to Legal instead of standing: read the result as it is. "Challenges route; they never flip a decision."

### 1:00 · Questions · Claims Lead

**Clicks:**
1. Role switcher → **Claims Lead**.
2. Left nav → **Questions**. Open the Q1 card: NS31 / 14C, the service-desk voucher in lieu.
3. Point at What it found / Why it flagged it / What it recommends, the `confidence 39% · sources disagree` chip, "Waiting on Claims Lead 3h · reminder sent · N others settled", and "Holds €600". The passenger's name is visible to this role.
4. Check that the preselected option is the cash payout with no offset. Paste `;q1` into the explanation. Submit the answer.
5. The rule preview opens: the rule as a sentence, her words highlighted, the checks, and "would change N past decisions · Δ€". Click **Confirm**.
6. "Saved as policy · Never asked again."

**Say:**
> "Claims Lead now, so her name shows. CRM says 14C took a €300 service-desk voucher; her claim says she never agreed, and there's no signature. 39%, sources disagree, waiting three hours. She rules: no signed acceptance, no offset."
>
> *[paste, submit]*
>
> "Her own words, highlighted, become a scoped rule."
>
> *[Confirm]*
>
> "Never asked again."

If a judge asks about the name: Ops sees it masked, and the Drafter never sees it at all.

**If it breaks:**
- No Q1 card: check that the switcher says Claims Lead (questions are role-scoped). If Q1 shows as answered, the state wasn't reset: Tab 2.
- The preview takes more than 5 s: say "It drafts the rule from her words and replays it before anyone confirms," and move to Legal. Show the rule in Policies during Q&A.
- A check fails (for example `grounded`): read it out. "It won't save a rule it can't ground in her words." Move on.

### 1:25 · Questions · Legal

**Clicks:**
1. Role switcher → **Legal**.
2. Questions → the Q2 card: "3 flights", NS113 / NS115 / NS117, `no precedent`. Read the confidence off the card (the plan's 47% was illustrative; the real server computes its own).
3. Check that the preselected option matches the ruling. Paste `;q2`, submit, then **Confirm** in the preview.
4. "3 settled, cited 3×."

**Say:**
> "Legal. One question, three flights: return legs the storm stranded. No precedent. The engine decides facts; Legal rules on law."
>
> *[paste, submit, Confirm]*
>
> "One ruling: three settled, cited three times."

**If it breaks:** same as 1:00. If "3 settled" doesn't show, keep going and open Policies → Ruled → `R-LEG-1` in Q&A.

### 1:40 · Questions → Liability & Close · Controller

**Clicks:**
1. Role switcher → **Controller**.
2. Questions → the Q3 card: the Storm Isha cohort (`EIDW@2024-01-21`, long haul), a release proposal at M12, `confidence 72% · no new claims in 3 months`. The release is preselected as the recommendation.
3. Choose the option that rejects it. Paste `;q3`, submit, then **Confirm** in the preview (`R-CTL-1`).
4. StormCheck asks "All storm cohorts?" Point at it. Don't answer it on stage.
5. Left nav → **Liability & Close**. Point at the CFO bridge ("Cash basis €0 · full entitlement €99,000 · drafted €34,650 (±5pp ±€4,950)") and the `TIES TO GL 2140` chip on the 2140 rollforward.

**Say:**
> "The Controller. It proposed releasing Storm Isha's last €3,600: no claims in three months. She says no: never release the tail."
>
> *[paste, submit, Confirm]*
>
> "The rejection becomes a rule, and it asks once: all storm cohorts?"
>
> *[Liability & Close]*
>
> "And the rollforward ties to GL 2140."

**If it breaks:** if Liability & Close is slow, skip it: "It ties to GL 2140; I'll show you the February true-up after." Get to the desk on time.

### 2:00 · Judge's Desk · Judge

**Clicks:**
1. Role switcher → **Judge**. Left nav → **Judge's Desk**.
2. Ask. Type their airport in the airport box (IATA or ICAO; pick from the autocomplete), set their local date, click **Run**.
3. Keep talking while it runs (target: under 5 s).
4. Point at the METAR curve and window band (or the "max gust … · no storm window" line), at the flight whose 'weather' code the METAR contradicts, and at the ↻ line: "N voucher cases settled, ruling cited", with the non-EU departure asking.

**Say:**
> "Your turn. Name an airport and a date."
>
> *[type, Run]*
>
> "That's the real METAR for that day. It simulates Northstar's flights to Dublin on that weather, mess included, and runs the same engine."
>
> *[point]*
>
> "A 'weather' code the weather doesn't back up: caught. And the Claims Lead's voucher rule from a minute ago: N cases settled, ruling cited. The one flight that doesn't leave the EU asks again, because her rule covers flights that leave the EU."

Read N off the screen. On the Herminia day (`EIDW@2025-01-26`) it's 31 settled and the BOS→DUB case asks; on a judge's day the counts are smaller.

**If the judge hesitates,** offer "Heathrow, 21 January 2024: Storm Isha." `EGLL 2024-01-21` is pinned and covered by David's tests. LHR→DUB doesn't depart the EU, so the voucher case asks there.

**If it breaks:**
- A 422 (future date, unknown airport, no METAR): read the message out ("It refuses rather than guesses") and run Heathrow, 21 Jan 2024.
- A calm day ("max gust … · no storm window") is a correct answer. Say "No storm window that day, so a 'weather' code wouldn't survive." If there's time, run Heathrow.
- Slow, or offline: click one of the 8 rehearsed-scenario buttons and read its result.

### 2:35 · Proof · any role

**Clicks:** left nav → **Proof**. Point at the headline, then the scorecard tiles.

**Say:**
> "How we know. Real Dublin weather, traffic and EU law; simulated logs. Plain Claude on the same documents, three runs: three different numbers. StormCheck: €34,650 three times, same hash."

**If it breaks:** the scorecard is empty (no `proof.json`). Don't fill it in from memory. Switch to Tab 2, or go straight to the close.

### 2:50 · Storm Run · any role

**Clicks:** left nav → **Storm Run**.

**Say:**
> "Today it's a human runtime: a 5 a.m. code and a spreadsheet. StormCheck drafts it by morning and asks only about the 1%. A three-route charter doesn't need it."

Then stop talking.

---

## If the whole thing breaks
1. **Server down or a beat stuck:** Tab 2, the recorded build, at the same beat. Say once: "Same build, recorded run."
2. **Laptop down:** the spare laptop on the same tag, `make demo-offline`.
3. **Nothing works:** play `stormcheck.mp4` and take questions over it.

---

## Not in the live demo: ready for Q&A

Each of these is a click or two from where the run ends. Reset after anything that changes state.

| They ask | Clicks (role) | On screen | Say |
|---|---|---|---|
| "What happens a month later?" (Feb true-up, estimate card) | Controller. Liability & Close → **Lock period** 2025-01 if it isn't locked → time scrubber to 28 Feb 2025 if the Feb claims aren't in → **Month-end** 2025-02 | "+€3,990 change in estimate". Estimate card: expected-loss €21,750 · Bornhuetter-Ferguson €25,740 (selected) · chain-ladder; A/E 1.45; ±5pp ±€4,950. Rollforward: €34,650 → (€3,600) → (€9,300) → +€3,990 → €25,740 · TIES TO GL 2140 · Jan locked, untouched | "Claims ran ahead of the curve, so it re-estimates: a change in estimate for the Controller to approve. January stays locked." |
| "Can it approve its own entry?" | Liability & Close → a JE draft → **[Approve]** as the principal the card names as its preparer | `DENIED · SoD` | "Preparer and approver are different people, in code." |
| "Where does €34,650 come from?" (Trace, blame) | Trace → **Blame**, target NS31's €34,650 | € → entitlement → rule@v → ruling quote → facts → span → METAR obs | "Every euro walks back to a log line, a weather hour, a rule and the person who ruled." Then Commits (`llm_call` rows) and `make verify`. |
| "Who can see what?" (Access, Controls) | Trace → **Access**, then **Controls** | Principals × resources, people and agents; denied log `agent.drafter approve_payout → DENIED · SoD`; "view as Ops" masks PII. Controls: "SOC 2 is the floor", CC6.1 · CC6.3 · CC7.2 · CC8.1 · PI1 | "It's a mapping to evidence, not a certification." |
| "What if a rule is wrong?" (revert) | Policies → Ruled → `R-LEG-1@1` → **Revert** | Replay diff: "flips N · Δ€ · Jan locked, untouched" | "Revert replays everything the rule touched and drafts the correction in the open period." |
| "Where do the rules come from?" | Policies | Learned ("41 of 42"), Ruled, Rejected (the Controller's sentence), Regulation (Reg (EU) 2026/2202 · in force 22 Oct 2026 · applies from 23 Oct 2027) | "No rule editor. Rules come from history, rulings, rejections and regulation." |
| "And later?" (time scrubber) | Time scrubber, forward | Reminders fire, claims arrive, month-end opens | "One clock drives everything, and it only goes forward." |
| "Other airlines flew during your window." | Flight File → NS108 (any weather flight) → **Defence prepared · Art. 5(3)** | The METAR at STD inside the window · "the window closed 6 h 45 min after STD" · known before deciding: the 05:12Z OCC list · against us: 179 departures · still owed: refunds and care | "We never argue Dublin was shut. Each flight is argued on its own weather, and the file says what's against us too." |
| "What if Airbus says it was a hidden defect?" | Judge's Desk → rehearsed scenario 05 (or Flight File → Challenge with the notice) | `new_legal_pattern` → routed to Legal, `confidence 52% · no precedent` | "A new legal question goes to Legal. A challenge routes; it doesn't flip." |
| The other rehearsed scenarios | Judge's Desk → the 8 buttons: AOG inside the window, duplicate direct + agency claim, prompt-injection email, chargeback after a bot refund, hidden-defect notice, claim after limitation, "storm anyway", UK261 £520 on DUB–LHR | The facts with quoted spans, what changed, and each scenario's expected outcome | Read the result. Don't predict it. |
