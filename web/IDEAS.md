# Ideas from the UI side

Notes from Justin's Claude after building the landing and the app overnight. For the team; take what helps.

## The pitch, in the order a judge sees it
1. **Open on `/moment`.** 20 seconds, self-playing, all real Storm Bram data: the storm, the METAR window,
   NS31 after it, the 07:55 tech log, "Not weather. Broken plane.", €127,200 → €44,520, the trace. Record it at
   1920×1080 for the Devpost video's first 20 s.
2. **The proof shot.** At 21:30Z the EUMETSAT GeoColour frame shows clear sky and Dublin's city lights. "The
   storm had cleared. The plane hadn't." Any judge can check it on EUMETView. It's the landing hero's last frame.
3. **Live demo path (under 3 min):**
   - Overview: 14 cancellations, all ops-coded 71. NS31 is the red row (71 → 41, 91%).
   - Open NS31: the evidence, strongest first; the aircraft inks in with engine 1 in red.
   - "Why this €?": €44,520 → claim rate → 212 × €600 → R-3 v2 → tech log → METAR → Legal.
   - "Replay the 09:00Z run": the work StormCheck did before anyone was in.
   - Inbox: rule on the voucher. It becomes R-7 v1 and 31 cases settle. Then show it in Rules.
   - Judge's desk: let a judge pick their own airport and date. Live METAR, verdict and euros move.
4. **Lines that land:** "Every euro, traced." · "Weather has a window." · "It drafts. It never pays." ·
   "It asks the right person once."

## Cheap things that read as depth
- **IATA delay codes:** show ops' 71 (weather) being overruled to 41 (aircraft defects). Already in the UI.
- **Art. 7(3):** vouchers count against compensation only with the passenger's *signed* agreement. The
  Claims Lead's ruling (R-7) operationalises it for CRM "accepted" flags. Cite it; it makes the learned rule look
  grounded, not invented.
- **Wallentin-Hermann (C-549/07)** for technical faults; **Pešková (C-315/15)** for bird strikes (the desk
  already returns "extraordinary" for a bird strike).
- **EU261 reform:** Regulation (EU) 2026/2202 (published 2 Oct 2026) keeps €250/400/600. A December 2025 flight
  is still under 261/2004. Good Q&A answer.
- **Least privilege you can see:** "View as Ops" hides passenger names (GDPR); only the Claims Lead can approve
  payouts or letters; only the Controller can post journal entries.

## Ideas we could still add (ranked by value per hour)
1. **"As of" replay on Rules:** pick a date, see which rule versions applied and which euros would flip. The
   engine's replay endpoint (see `API_CONTRACT.md`) is all the UI needs.
2. **Evidence states on every flight row:** pencil (pending), ink (agreed), red pencil (escalated). Same visual
   language as the landing.
3. **Eval page:** "on storms it never saw: X% straight-through, Y miscoded caught (€Z), 0 repeat questions"
   as a small, honest scorecard with the answer-key link. Judges asked for proof.
4. **A second storm replay** (Éowyn data is already in `public/data/`) to show the rules carry over.

## Risks I noticed
- **Timing:** Éowyn's peak at Dublin was 04:00–10:00 UTC. Bram fits the story. With Bram, use a **40 kt** gust
  limit: at 32–35 kt the real 21:00Z report (G39) opens a second window over NS31's slot.
- **Seat count:** 212 passengers is high for a 184-seat A321LR. Fine for a fictional all-economy cabin; have the line ready.
- **"The AI decides":** never say it. The engine decides; the model reads the mess and drafts.
- **Claim rate:** 35% needs its source on screen (the Ledger shows the curve and the lookback).
