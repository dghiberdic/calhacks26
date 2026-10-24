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
B612 Mono only for machine text (METAR, tech log, codes, amounts). Evidence inks the drawing: pencil until the
sources agree. Art direction lives on the Claude Design canvas "StormCheck — Design".
