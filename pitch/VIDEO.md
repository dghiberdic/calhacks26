# Video · storyboard and recording (≤3:00)

Hyphenate asks for a video that opens with the moment. This one does: 0:00–0:35 is NS31, "Not weather. Broken plane." Everything on screen is captured from the recorded build, so every number matches the live demo and the API.

Rules for the edit:
- The first frame is Storm Run, not a logo.
- A caption only repeats a number that is on screen in that shot.
- Wording follows `IMPLEMENTATION_PLAN.md` §9. Watch for "EU261 compensation liability" (never "provision"), "drafted, pending approval", "service-desk voucher", "cause-finding confidence 91%".
- Target 2:55. Hard cap 3:00.

## Storyboard

Voice-over is timed at about 155 words a minute. If a line runs long, cut words; don't speed up.

### The moment (0:00–0:35)

| # | Time | On screen | Voice-over | Caption |
|---|---|---|---|---|
| 1 | 0:00–0:05 | Storm Run, full frame, as it loads. 27 cancelled ticks, all `71`. | "Dublin, Storm Éowyn. At 5 a.m., operations codes all 27 cancellations 'weather'." | Storm Éowyn · Dublin · Fri 24 Jan 2025 · 05:12Z: 27 cancellations, all coded weather |
| 2 | 0:05–0:11 | METAR gust and sustained lines draw. The window band fills 02:30–15:00Z. 23 ticks turn grey, 3 amber. The 11 departures that operated 15:30–17:30Z appear as solid ticks. | "The real METAR puts the storm at 02:30 to 15:00. After it, eleven departures flew." | Real METAR, EIDW · storm window 02:30–15:00Z · 11 departures operated 15:30–17:30Z |
| 3 | 0:11–0:19 | Push in on NS31's tick at 16:30Z, then on the tech-log marker at 23 Jan 21:40Z with the AMOS line in mono. | "NS31 to Boston was due at 16:30, after the storm. The night before, its tech log: hydraulic pump leak, no MEL relief." | 23JAN 21:40Z EI-NSB · EXT LEAK EDP CASE DRAIN PORT, EXCEEDS AMM LIMIT · NO MEL RELIEF · A/C AOG |
| 4 | 0:19–0:23 | NS31 slides out of the band and turns red: "Not weather. Broken plane." · `71 → 41`. Hold. | "Not weather. Broken plane." | 71 → 41 · cause-finding confidence 91% · fault logged before storm |
| 5 | 0:23–0:31 | The NS31 liability tile settles on €34,650: not €0, not €99,000. | "If all 172 passengers claim, that's €99,000. Northstar's history says 35% will: €34,650 drafted. Not zero. Not €99,000." | €99,000 = full Art. 7 entitlement if every passenger claims · 35% expected ultimate claim rate → €34,650 |
| 6 | 0:31–0:35 | "172 payouts drafted, pending Claims Lead approval." The headline: "5,292 passengers · 3 questions · 3 people". | "172 payouts drafted, pending Claims Lead approval." | Drafted, pending approval · journals parked |

### The rest (0:35–2:57)

| # | Time | On screen | Voice-over | Caption |
|---|---|---|---|---|
| 7 | 0:35–0:46 | Title: StormCheck, then the seats line (the `/pitch/0` cover carries both, over the real Éowyn satellite image). | "StormCheck fills two seats at Northstar, a fictional €1.1B Irish airline: the claims accountant and the revenue accountant, and the one step between them: what really caused each cancellation." | Real Dublin weather, traffic and EU law; simulated logs |
| 8 | 0:46–0:59 | Flight File, NS31: evidence ranked by trust tier, the OCC `71` struck through, then the handoff row. | "Evidence comes ranked: the tech log beats a 5 a.m. batch code. The CRM bot had already refunded 32 people. StormCheck doesn't do it twice, and drafts their corrected rights notices without seeing a name." | 32 refunds already initiated · not repeated · 32 corrected rights notices drafted · Drafter saw 0 PII |
| 9 | 0:59–1:08 | The Challenge box: "The storm would have grounded it anyway" → "Decision stands.", with the citations. | "Push back, and it defends the decision with the record: the METAR, the eleven flights that left, the fault logged before the storm." | Challenge: assertion → Decision stands. |
| 10 | 1:08–1:27 | Questions as Claims Lead. The Q1 card and its chips; the ruling pasted; the preview with her words highlighted; Confirm → "Saved as policy · Never asked again". | "It asks only when the evidence disagrees, and it asks the right person. CRM says this passenger took a €300 service-desk voucher. She says she never agreed, and there's no signature. The Claims Lead rules once. Her words become a scoped rule." | Routed to the Claims Lead · confidence 39% · sources disagree · Holds €600 |
| 11 | 1:27–1:35 | The next storm, Herminia (`EIDW@2025-01-26`): "31 voucher cases settled, ruling cited"; the BOS→DUB case asks. | "Two days later, Storm Herminia: 31 cases settle on her ruling. The one that doesn't leave the EU asks." | ↻ Next storm: 31 voucher cases settled, ruling cited · BOS→DUB asks |
| 12 | 1:35–1:46 | Questions as Legal: "3 flights", 47% · no precedent → ruling → "3 settled, cited 3×". | "New legal questions go to Legal, once. Three return flights the storm stranded: one question, one ruling, three settled." | The engine decides facts; Legal rules on law · C-74/19 |
| 13 | 1:46–1:57 | Questions as Controller: the Isha release proposal (72%) → rejected → rule → "All storm cohorts?" | "When the Controller says no, that's a lesson too. 'Never release the tail' becomes a rule, and it asks once whether it holds for every storm." | Rejected → R-CTL-1 · reduce to the expected tail at M12; derecognise at limitation |
| 14 | 1:57–2:10 | Liability & Close: the CFO bridge; Month-end for February → "+€3,990 change in estimate"; the rollforward at €25,740 · TIES TO GL 2140 · Jan locked, untouched. | "A month on, claims run ahead of the curve. It re-estimates: plus €3,990, a change in estimate for the Controller to approve. January stays locked, and it ties to the ledger." | A/E 1.45 · Bornhuetter-Ferguson · €25,740 = (35% − 9%) × €99,000 · TIES TO GL 2140 |
| 15 | 2:10–2:27 | Judge's Desk: Heathrow, 21 Jan 2024 → real METAR → Run → the contradicted 'weather' code → the ↻ voucher line. | "Pick any airport and date. It pulls that day's real METAR, simulates Northstar's flights on it, mess included, and runs the same engine. A 'weather' code the weather doesn't back up: caught." | Judge's Desk · your airport, your date, real METAR |
| 16 | 2:27–2:40 | Proof: the headline, the scorecard tiles, the reliability bins and their label. | "Plain Claude, same documents, three runs: three different numbers. StormCheck: €34,650, three times, same hash, scored on storms it never saw." | Plain Claude ×3: {{eval.baseline_eur_a}} / {{eval.baseline_eur_b}} / {{eval.baseline_eur_c}} · StormCheck ×3: €34,650, same hash. Second line, smaller: calibrated on synthetic labels; validates the pipeline, not the world |
| 17 | 2:40–2:50 | Trace → Blame for NS31's €34,650: the chain down to the METAR observation. | "Every euro traces back to a log line, a weather hour, a rule and the person who ruled." | € → entitlement → rule → tech-log line → METAR hour |
| 18 | 2:50–2:57 | End card: StormCheck · "It drafts. It never pays." · links. | "StormCheck. It drafts. It never pays." | {{links.repo}} · {{links.recorded_build}} |

Fill the `{{…}}` captions from `eval/proof.json` and the links list in `DEVPOST.md`. Shot 14 isn't in the live demo; it's in the video because "time" is one of the hard parts the track asks for.

## Record it

### Source
- **Primary: the recorded build on Vercel** (`VITE_MODE=recorded`, `{{links.recorded_build}}`). It replays the saved GET responses and the timed SSE log from `demo/recorded/` with no backend, so every take shows the same numbers.
- **Shots that write** (challenge, answer, confirm, month-end, desk run): if a step doesn't replay in the recorded build, record that shot from `make demo` on localhost, right after `curl -s -X POST localhost:8000/api/reset`, with the same browser setup.
- Use the same desk example as the rehearsal: Heathrow, 21 Jan 2024 (pinned).

### Screen and browser
- **1920×1080.** Easiest: an external 1080p display with Chrome full screen on it. Without one, pick a scaled display resolution at least 1920 wide and capture a 1920×1080 region. Either way, check in the console that `innerWidth` × `innerHeight` reads 1920 × 1080.
- **A clean Chrome window**: its own profile, no extensions, no tabs or address bar on screen:
  ```bash
  open -na "Google Chrome" --args --user-data-dir="$HOME/sc-video-profile" --app="{{links.recorded_build}}"
  ```
  For shots recorded from `make demo`, use `--app="http://localhost:8000"`.
- Zoom 100%, the same in every shot.
- Reduce motion off (System Settings → Accessibility → Display), or the Storm Run animation won't play. Do Not Disturb on. Dock and desktop icons hidden.
- **Recorder:** OBS (canvas and output 1920×1080, 30 fps; 60 fps if the timeline animation stutters at 30) or macOS Screenshot (Cmd+Shift+5). Record each shot as its own take, with 2 s of still frame before and after.

### Cursor
- **0:00–0:35: no cursor.** Park it off the capture area, or turn off cursor capture for those takes. The animation carries the moment.
- **After that:** show it. Move in straight, unhurried lines, rest on the thing the voice-over names, and pause half a second before each click. Don't hover anything you aren't talking about; tooltips will pop.

### Pacing
- Reload before each Storm Run take so the load animation plays from the start.
- Hold every end state for at least 2 s.
- Don't scroll under an important line. Scroll before it, or cut.
- Paste text (the snippets in `pitch/DEMO_SCRIPT.md`); never type on camera.
- Cut on clicks, not mid-motion.

### Voice-over
- One voice for the whole video. Who isn't decided yet.
- Record after picture lock, line by line from the storyboard. Quiet room, soft furnishings, mic 10–15 cm away and slightly off-axis. 48 kHz, 24-bit WAV.
- Clean-up: light noise reduction, a high-pass around 80 Hz, loudness to −16 LUFS integrated with peaks under −1 dBTP.
- Music: none, or a quiet bed at least 18 dB under the voice, under a licence that allows it.

### Captions
- Burn in the caption column above: lower third, inside the 90% safe area, at least 36 px tall at 1080p, two lines at most. The story should work with the sound off.
- Also export an `.srt` of the voice-over for the upload.

### Export
- H.264 (High profile), MP4, 1920×1080, 30 fps constant, yuv420p, CRF 18 (or 12–16 Mbps two-pass), AAC 48 kHz 192 kbps stereo, `faststart`.
- From an edit master:
  ```bash
  ffmpeg -i master.mov -c:v libx264 -preset slow -crf 18 -pix_fmt yuv420p -r 30 \
    -c:a aac -b:a 192k -ar 48000 -movflags +faststart stormcheck.mp4
  ```
- **Check before upload:** duration ≤ 3:00; the first frame is Storm Run; every number matches the recorded build; the Proof figures match `eval/proof.json`; the captions pass the §9 wording list.
- Upload to YouTube as Unlisted (or to Vimeo) and put the link in Devpost. Keep `stormcheck.mp4` on the demo laptop as the last-resort fallback for the live demo.
- Export a still of shot 4 (NS31 red, "Not weather. Broken plane.") for the Devpost image and the video thumbnail.

## Optional: the 20-second title film

Justin's earlier web build (the Next.js app on branch `justin/ui`, draft PR #2) has a self-playing `/moment` page and a renderer that captures it frame by frame in headless Chrome, so there are no dropped frames:

```bash
cd web            # in that build, not this repo's web/
npm run dev       # the film's timeline is exposed only in development
npm run film      # → moment.mp4, 1920×1080, 30 fps; needs Node 22+, Chrome, and Blender or ffmpeg
npm run film -- --fps 60 --out ~/Desktop/stormcheck-moment.mp4
npm run film -- --url http://localhost:3100/moment   # if the dev server isn't on :3000
```

It predates the plan. It tells the story on Storm Bram (9 Dec 2025) with 212 passengers, €127,200 and €44,520, and its wording ("provision", "held for the Claims Lead", "Confidence 91%") is on the §9 don't-say list. It can open the video only once it's re-cut to Éowyn's numbers and §9 wording; it would then replace shots 1–6, so keep it to 35 s or less. Until then, don't use it. The recorded build stays the primary source.
