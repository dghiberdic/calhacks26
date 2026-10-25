# Aircraft assets

The story now uses the **downloaded IDG A320neo exterior from FlightGear**, including the original fuselage, swept wings/sharklets, cockpit glazing, PW1100G engines, landing gear and StormCheck livery. It is the single base for the real-time scene, port/top sketches, interlude line art and matching stills. The original A321 assets remain intact, but are no longer rendered.

Source: [IDG A32X mirror](https://github.com/omega13a/A320Family-With-All-Liveries), pinned to `3cd4eb7433ac3ac0fe16cee97ef7b870553da4df`. Geometry and textures are GPL-2.0. `public/story/idg-a320neo/` includes the license, credits, and corresponding AC3D/XML/texture source archive plus importer. See `CREDITS.txt` for modifications and attribution.

The model is an A320neo, **not an A321**. Its length is preserved at approximately 37.57 m; it has not been stretched to fit the case. The caption explicitly calls it an A320neo family illustration. The fictional accounting case remains an A321. The schematic hydraulic overlay follows the shared A320neo geometry and pump anchor. This is an explanatory illustration, not maintenance CAD.

## Regeneration

From `web/`:

1. Extract `public/story/idg-a320neo/source.zip` to a local source directory.
2. Run `python3 scripts/import-flightgear-aircraft.py /path/to/source-directory`. Only static AC3D geometry, textures and XML assembly offsets are parsed. Simulator scripts are not executed. Gear is in its neutral down pose, with wheels on the apron. Web materials replace simulator reflection colours inside engines and use smoked glazing for the exterior-only model.
3. Start the Vite dev server and open `/scripts/aircraft-studio.html`. Inspect the nose, side, engines and whole aircraft using the preset buttons and orbit controls. After regenerating the GLB, change its studio query version if the browser has cached it.
4. Click **Save story assets**, then run `node scripts/import-aircraft-render.mjs /path/to/stormcheck-aircraft-assets.json`. This saves `stormcheck.glb`, 1280/2560 WebP renders, side/top/hero projections, and `aircraftModel.json`. The manifest provides one cache revision and model measurements for every active view.
5. Run `node --test scripts/aircraft-assets.test.mjs`, the frontend build/tests, and `e2e/story-aircraft.spec.ts`.

The studio is for asset authoring and is excluded from the production build. The branded GLB embeds all textures; it does not fetch assets from third parties at runtime. The scene lazy-loads near the section and retains the still fallback and reduced-motion behavior. `Fan`, `Fan_1`, `Cone`, and `Cone_1` rotate around the engine X axes. The illustrative starboard pump anchor is `(13.4, 1.55, -6.65)` in the normalized model coordinates (x aft, y up, z port).

## StormCheck paint and matching sketches

`aircraft-livery.mjs` applies the existing gust/check brand mark and wordmark with native vector canvas textures, white fuselage/wings, navy fin/nacelles/sharklets and thin brass/navy stripes. It preserves cockpit/passenger glazing, metal engine interiors and the source geometry. Decals are baked into the exported GLB; their rectangles are excluded from blueprint edges and ghost surfaces.

`aircraft-sketches.mjs` extracts silhouettes and creases, depth-tests them against the actual mesh, then joins visible segments. Side and top drawings are expressed in the same metres as the live scene. The side sketch and initial camera share a 45 m horizontal frame centred at x=19.5 m. Hero lines use the exact still-image camera. The hydraulic routing remains explanatory; its engine-2 anchor shares `(13.4, 1.55, -6.65)` with the 3D scene.

Inspect **Side sketch** and **Top sketch** in the studio before saving. `stormcheck-design-source.zip` accompanies the public GPL model with the livery, projections, authoring page, import scripts and this rebuild guide. The unpainted base `aircraft.glb` remains the studio's input; it is not used by the story.
