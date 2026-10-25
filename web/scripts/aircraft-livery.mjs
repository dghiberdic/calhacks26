// Native StormCheck branding, projected onto the original aircraft surfaces.
// The gust/check path is the same vector used by src/components/brand/Logo.tsx.
import * as T from "three";
import { DecalGeometry } from "three/addons/geometries/DecalGeometry.js";

const NAVY = "#162238";
const WHITE = "#f4f6f9";
const GOLD = "#c9a96b";
const MARK = "M2 15 q2.5 -7 5 0 t5 0 t5 0 L23 24 L46 3";

function brandTexture(wordmark, color) {
  const canvas = document.createElement("canvas");
  canvas.width = wordmark ? 4096 : 1024;
  canvas.height = wordmark ? 512 : 640;
  const ctx = canvas.getContext("2d");
  ctx.save();
  const scale = wordmark ? 12 : 20;
  ctx.translate(wordmark ? 60 : 30, wordmark ? 80 : 40);
  ctx.scale(scale, scale);
  ctx.strokeStyle = color;
  ctx.lineWidth = 2.8;
  ctx.lineCap = "round";
  ctx.lineJoin = "round";
  ctx.stroke(new Path2D(MARK));
  ctx.restore();
  if (wordmark) {
    ctx.fillStyle = color;
    ctx.font = "600 390px Arial";
    ctx.textBaseline = "middle";
    ctx.fillText("StormCheck", 770, 285, 3200);
  }
  const texture = new T.CanvasTexture(canvas);
  texture.colorSpace = T.SRGBColorSpace;
  texture.anisotropy = 8;
  return texture;
}

export function applyStormCheckLivery(aircraft) {
  aircraft.updateMatrixWorld(true);
  const body = aircraft.getObjectByName("Fuselage006");
  const fins = [];
  const doors = [];
  aircraft.traverse((o) => {
    if (!o.isMesh) return;
    const ancestors = [];
    for (let p = o.parent; p; p = p.parent) ancestors.push(p.name);
    const part = ancestors.join("/");
    const coat = (original) => {
      const material = original.clone();
      if (
        /fuselage|hstab|vstab|wings|sharklets/i.test(part) &&
        !/Engine|PW1100|pylon/i.test(part)
      ) {
        // Glazing remains dark; remove the demonstration livery from painted panels.
        if (!/glass|unvisible/i.test(material.name)) {
          material.map = null;
          material.color.set(/vstab|sharklets/i.test(part) ? NAVY : WHITE);
          material.metalness = 0.12;
          material.roughness = 0.3;
        }
      }
      if (/NacellePW|ReverserPW/.test(o.name) && material.map) {
        material.map = null;
        material.color.set(NAVY);
        material.metalness = 0.16;
        material.roughness = 0.3;
      }
      if (/pylon/i.test(part)) {
        material.map = null;
        material.color.set(WHITE);
      }
      return material;
    };
    o.material = Array.isArray(o.material)
      ? o.material.map(coat)
      : coat(o.material);
    if (/Vstab_|Rudder_/.test(o.name)) fins.push(o);
    if (/^Door[LR][1-4]$/.test(o.name)) doors.push(o);
  });

  const wordmark = brandTexture(true, NAVY);
  const mark = brandTexture(false, WHITE);
  let sequence = 0;
  function decal(mesh, position, size, side, map, color = WHITE) {
    const geometry = new DecalGeometry(
      mesh,
      new T.Vector3(...position),
      new T.Euler(0, side < 0 ? Math.PI : 0, 0),
      new T.Vector3(...size),
    );
    if (!geometry.attributes.position.count) return;
    // Move the decal just above the skin. This survives GLB export without custom shaders.
    const p = geometry.attributes.position,
      n = geometry.attributes.normal;
    for (let i = 0; i < p.count; i++)
      p.setXYZ(
        i,
        p.getX(i) + n.getX(i) * 0.003,
        p.getY(i) + n.getY(i) * 0.003,
        p.getZ(i) + n.getZ(i) * 0.003,
      );
    const material = new T.MeshStandardMaterial({
      map,
      color,
      transparent: !!map,
      depthWrite: !map,
      roughness: 0.32,
      metalness: 0.1,
    });
    const surface = new T.Mesh(geometry, material);
    surface.name = `livery_${sequence++}`;
    surface.renderOrder = 3;
    aircraft.add(surface);
  }
  for (const side of [1, -1]) {
    decal(body, [12.8, 5.8, side * 1.5], [13.3, 1.05, 2.5], side, wordmark);
    for (const panel of [body, ...doors]) {
      decal(
        panel,
        [17.3, 4.55, side * 1.7],
        [27, 0.085, 2.8],
        side,
        null,
        GOLD,
      );
      decal(panel, [17.3, 4.42, side * 1.7], [27, 0.14, 2.8], side, null, NAVY);
    }
    for (const fin of fins)
      decal(fin, [33.95, 9.25, side * 0.2], [3.2, 1.9, 0.38], side, mark);
  }
  aircraft.userData.livery = "StormCheck · navy / cloud white / brass";
  aircraft.updateMatrixWorld(true);
}
