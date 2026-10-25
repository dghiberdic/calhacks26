import { createHash } from "node:crypto";
import { readFile } from "node:fs/promises";
import assert from "node:assert/strict";
import { test } from "node:test";
import { Box3, Texture, Vector3 } from "three";
import { GLTFLoader } from "three/addons/loaders/GLTFLoader.js";

const manifest = JSON.parse(
  await readFile(
    new URL("../src/story/data/aircraftModel.json", import.meta.url),
    "utf8",
  ),
);
const bytes = await readFile(
  new URL("../public/story/idg-a320neo/stormcheck.glb", import.meta.url),
);
const { scene } = await new GLTFLoader()
  // Geometry validation does not require a DOM image decoder. Browser tests load real textures.
  .register(() => ({
    name: "geometry_only",
    loadTexture: () => Promise.resolve(new Texture()),
  }))
  .parseAsync(
    bytes.buffer.slice(bytes.byteOffset, bytes.byteOffset + bytes.byteLength),
    "",
  );
scene.updateMatrixWorld(true);

test("downloaded A320neo retains full scale, grounded gear, fans and a valid pump anchor", () => {
  const bounds = new Box3().setFromObject(scene);
  const size = bounds.getSize(new Vector3());
  assert.ok(
    size.x > 37 && size.x < 38,
    "A320 must not be stretched to A321 length",
  );
  assert.ok(size.z > 35 && size.z < 36);
  assert.ok(size.y > 11.5 && size.y < 12.5);
  assert.ok(Math.abs(bounds.min.y) < 0.02, "gear should rest on the apron");
  for (const name of ["Fan", "Fan_1", "Cone", "Cone_1"])
    assert.ok(scene.getObjectByName(name)?.isMesh, `${name} missing`);
  const engine = scene.getObjectByName("EnginePWRight");
  assert.ok(engine, "starboard engine assembly missing");
  assert.ok(
    new Box3()
      .setFromObject(engine)
      .containsPoint(new Vector3().fromArray(manifest.leak)),
  );
  assert.ok(
    bytes.length < 12 * 1024 * 1024,
    "model exceeds the local preview budget",
  );
});

test("converted surfaces are finite with normalized shading normals and embedded textures", () => {
  scene.traverse((o) => {
    if (!o.isMesh) return;
    for (const [name, attr] of Object.entries(o.geometry.attributes))
      assert.ok(
        attr.array.every(Number.isFinite),
        `${o.name}.${name} has nonfinite values`,
      );
    const normals = o.geometry.attributes.normal;
    for (let i = 0; i < normals.count; i++)
      assert.ok(
        Math.abs(new Vector3().fromBufferAttribute(normals, i).length() - 1) <
          0.001,
      );
  });
  const gltf = JSON.parse(
    bytes.subarray(20, 20 + bytes.readUInt32LE(12)).toString(),
  );
  assert.ok(gltf.images.length >= 4);
  assert.ok(
    gltf.images.every(
      (image) => Number.isInteger(image.bufferView) && !image.uri,
    ),
  );
});

test("matching posters, projected line art and redistributable source are present", async () => {
  for (const width of [1280, 2560]) {
    const image = await readFile(
      new URL(
        `../public/story/idg-a320neo/poster-${width}.webp`,
        import.meta.url,
      ),
    );
    assert.equal(image.toString("ascii", 0, 4), "RIFF");
    assert.equal(image.toString("ascii", 8, 12), "WEBP");
  }
  const lines = JSON.parse(
    await readFile(
      new URL("../src/story/data/aircraftHeroLines.json", import.meta.url),
      "utf8",
    ),
  );
  assert.ok(lines.length > 0 && lines.length < 6000);
  assert.ok(lines.every((d) => /^M[\d.,-]+(?:L[\d.,-]+)+$/.test(d)));
  const license = await readFile(
    new URL("../public/story/idg-a320neo/COPYING.txt", import.meta.url),
    "utf8",
  );
  assert.match(license, /GNU GENERAL PUBLIC LICENSE/);
  const source = await readFile(
    new URL("../public/story/idg-a320neo/source.zip", import.meta.url),
  );
  assert.equal(source.toString("ascii", 0, 2), "PK");
});

test("all views use one measured, branded aircraft and a cache-safe revision", async () => {
  assert.equal(
    manifest.revision,
    createHash("sha256").update(bytes).digest("hex").slice(0, 12),
  );
  const dimensions = new Box3().setFromObject(scene).getSize(new Vector3());
  for (const [key, axis] of [
    ["length", "x"],
    ["height", "y"],
    ["span", "z"],
  ])
    assert.ok(Math.abs(dimensions[axis] - manifest.dimensions[key]) < 0.001);
  let decals = 0;
  scene.traverse((o) => {
    if (o.isMesh && o.name.startsWith("livery_")) decals++;
  });
  assert.ok(
    decals >= 6,
    "StormCheck wordmarks and tail logos must be baked into the exported model",
  );
  const sketches = JSON.parse(
    await readFile(
      new URL("../src/story/data/aircraftSketches.json", import.meta.url),
      "utf8",
    ),
  );
  for (const name of ["side", "top"]) {
    assert.ok(
      sketches[name].length > 100,
      `${name} drawing is empty or incomplete`,
    );
    const [x, y, width, height] = manifest.views[name];
    for (const d of sketches[name]) {
      assert.match(d, /^M[\d.,-]+(?:L[\d.,-]+)+$/);
      const coordinates = d.match(/-?\d+(?:\.\d+)?/g).map(Number);
      for (let i = 0; i < coordinates.length; i += 2) {
        assert.ok(coordinates[i] >= x && coordinates[i] <= x + width);
        assert.ok(coordinates[i + 1] >= y && coordinates[i + 1] <= y + height);
      }
    }
  }
  // Port is +z and appears below the plan centreline; the starboard leak stays above it.
  assert.ok(manifest.leak[2] < 0);
});
