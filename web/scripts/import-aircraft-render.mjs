/** Import one authoring bundle so every rendered aircraft shares geometry and a revision. */
import { readFile, writeFile } from "node:fs/promises";
import { createHash } from "node:crypto";
const path = process.argv[2];
if (!path)
  throw new Error(
    "Usage: node scripts/import-aircraft-render.mjs /path/to/stormcheck-aircraft-assets.json",
  );
const bundle = JSON.parse(await readFile(path, "utf8"));
for (const width of [1280, 2560]) {
  if (!bundle.images?.[width]?.startsWith("data:image/webp;base64,"))
    throw new Error(`Missing WebP render at ${width}px`);
}
for (const lines of [
  bundle.lines,
  bundle.sketches?.side,
  bundle.sketches?.top,
]) {
  if (
    !Array.isArray(lines) ||
    !lines.length ||
    !lines.every((d) => /^M[\d.,-]+(?:L[\d.,-]+)+$/.test(d))
  )
    throw new Error("Invalid projected line art");
}
if (!bundle.model?.startsWith("data:model/gltf-binary;base64,"))
  throw new Error("Missing branded GLB");
const model = Buffer.from(bundle.model.split(",")[1], "base64");
if (
  model.toString("ascii", 0, 4) !== "glTF" ||
  model.readUInt32LE(4) !== 2 ||
  model.readUInt32LE(8) !== model.length
)
  throw new Error("Invalid GLB export");
if (
  !["length", "height", "span"].every(
    (key) =>
      Number.isFinite(bundle.geometry?.[key]) && bundle.geometry[key] > 0,
  )
)
  throw new Error("Missing model measurements");
if (
  !["side", "top"].every(
    (key) =>
      bundle.views?.[key]?.length === 4 &&
      bundle.views[key].every(Number.isFinite),
  )
)
  throw new Error("Missing projection bounds");
const revision = createHash("sha256").update(model).digest("hex").slice(0, 12);
const manifest = {
  model: "idg-a320neo/stormcheck.glb",
  revision,
  posters: {
    small: "idg-a320neo/poster-1280.webp",
    large: "idg-a320neo/poster-2560.webp",
  },
  dimensions: bundle.geometry,
  views: bundle.views,
  leak: [13.4, 1.55, -6.65],
  source: "IDG A320neo",
  livery: "StormCheck",
};
// Validate the complete bundle before replacing any active assets.
await writeFile(
  new URL("../public/story/idg-a320neo/stormcheck.glb", import.meta.url),
  model,
);
for (const width of [1280, 2560])
  await writeFile(
    new URL(
      `../public/story/idg-a320neo/poster-${width}.webp`,
      import.meta.url,
    ),
    Buffer.from(bundle.images[width].split(",")[1], "base64"),
  );
for (const [name, value] of Object.entries({
  aircraftHeroLines: bundle.lines,
  aircraftSketches: bundle.sketches,
  aircraftModel: manifest,
}))
  await writeFile(
    new URL(`../src/story/data/${name}.json`, import.meta.url),
    `${JSON.stringify(value, null, 2)}\n`,
  );
console.log(
  `Imported StormCheck model ${revision}, ${bundle.sketches.side.length} side paths, ${bundle.sketches.top.length} plan paths and ${bundle.lines.length} hero paths.`,
);
