# StormCheck web

Justin's part: the immersive landing page and the product app. Next.js 16 (App Router), React 19,
Tailwind 4, GSAP (ScrollTrigger, DrawSVG) + Lenis, three.js, Motion, d3.

```bash
npm install
npm run dev        # http://localhost:3000
```

| Route | What it is |
|---|---|
| `/` | Landing. Storm Bram time-lapse hero → split-flap board → METAR storm window → A321 blueprint → verdict → trace → ask-once |
| `/moment` | The 20-second "moment" as a self-playing film for the Devpost video (Space pauses, R restarts). Record at 1920×1080 |
| `/app` | Overview: KPIs, the day at Dublin, routes, cancellations, flight side sheet |
| `/app/inbox` | Escalations as handoff packets → answers become versioned rules |
| `/app/payouts`, `/app/ledger`, `/app/rules` | Payout review, provision + journal, versioned rules |
| `/app/desk` | Judge's desk: any ICAO station + date, live METAR, verdict and euros move as you edit the tech log |
| `/app?demo` or press **G** | Presenter's demo guide: the 3-minute path, each step performs its action |
| `/api/metar` | `?station=EIDW&date=2025-12-09&limit=40` live METAR from the IEM archive + computed storm windows |

## Data (all real unless marked)
- `public/data/bram/` Storm Bram, 9 Dec 2025: EUMETSAT MTG GeoColour frames every 30 min (CC BY 4.0,
  "Contains modified EUMETSAT data, 2025"), ERA5 hourly MSLP + 10 m wind (Open-Meteo archive), EIDW METAR (IEM).
- `public/data/storm-2025-01-24.json`, `sat-2025-01-24.jpg` Storm Éowyn (ERA5 + NASA GIBS MODIS), kept as a replay.
- `src/data/geo/land.ts` Natural Earth coastlines pre-projected by `scripts/build-geo.ts`.
- `src/data/scenario.ts`, `src/data/app.ts` **Simulated**: Northstar Air, flights, passengers, tech log, claims.
  Shapes follow `API_CONTRACT.md` so the engine can replace them.

Refetch: `node scripts/fetch-storm.mjs --date 2025-12-09 …`, `node scripts/fetch-mtg.mjs`, `npx tsx scripts/fetch-metar.ts`.

## Design rules
Colour only means a verdict (weather grey, owed vermilion, review amber, settled green, interactive blue).
B612 Mono only for machine text (METAR, tech log, codes, IDs, journal lines). Money anywhere, and clocks at
display size, use `.figure` (Archivo, tabular figures): B612 sets `:` and `,` at the left of a full cell, so
"€127,200" reads "€127, 200". Evidence inks the drawing: pencil until the sources agree. Art direction lives on
the Claude Design canvas "StormCheck — Design".

- Line art plots with `PLOTTED` on the paths and `UNPLOTTED` in a `.from()` (`components/motion/gsap.ts`);
  DrawSVG measures every path and costs ~250 ms across the landing's ~650.
- A pinned section has to fit one screen on a 375×667 phone; on phones the chart pans instead of shrinking.
- No page-wide `<ViewTransition>`: Suspense reveals would freeze the landing mid-scroll. App pages have one.

## Visual QA
`npm run shoot` takes headless screenshots with the Chrome you already have (Node 22+) and lists every console
error; it exits 1 if the page threw. With `npm run dev` running:

```
npm run shoot                                              # landing, 1440×900 + 390×844, 8 scroll depths
npm run shoot -- --url http://localhost:3000/app/payouts --at 0
npm run shoot -- --sizes 375x667 --at 0,0.4,0.6 --out shots
```

`npm run film` renders `/moment` to `moment.mp4` (1920×1080, 30 fps) frame by frame, encoded with Blender's
FFmpeg (or `ffmpeg` if it's on PATH). Run it against `npm run dev`; `--fps 60` and `--out` are optional.
