// Visible contour/crease extraction from the same mesh used by the animated aircraft.
// A GPU depth pass removes hidden segments; no hand-drawn substitute silhouettes.
import * as T from "three";

export function aircraftEdges(aircraft) {
  const result = [];
  const a = new T.Vector3(),
    b = new T.Vector3(),
    c = new T.Vector3();
  const normal = new T.Vector3(),
    ab = new T.Vector3(),
    ac = new T.Vector3();
  aircraft.updateMatrixWorld(true);
  aircraft.traverse((mesh) => {
    if (!mesh.isMesh || mesh.name.startsWith("livery_")) return;
    const edges = new Map();
    const p = mesh.geometry.attributes.position;
    const index = mesh.geometry.index;
    const count = index?.count ?? p.count;
    const key = (point) =>
      point
        .toArray()
        .map((v) => v.toFixed(4))
        .join(",");
    for (let i = 0; i < count; i += 3) {
      const points = [a, b, c];
      points.forEach((v, k) =>
        v
          .fromBufferAttribute(p, index ? index.getX(i + k) : i + k)
          .applyMatrix4(mesh.matrixWorld),
      );
      normal.crossVectors(ab.subVectors(b, a), ac.subVectors(c, a)).normalize();
      for (let j = 0; j < 3; j++) {
        const p0 = points[j],
          p1 = points[(j + 1) % 3];
        const keys = [key(p0), key(p1)].sort();
        const id = keys.join("|");
        if (keys[0] === keys[1]) continue;
        const edge = edges.get(id);
        if (edge) edge.normals.push(normal.clone());
        else
          edges.set(id, {
            a: p0.clone(),
            b: p1.clone(),
            normals: [normal.clone()],
          });
      }
    }
    result.push(...edges.values());
  });
  return result;
}

export function projectSketch(
  aircraft,
  edges,
  renderer,
  camera,
  width,
  height,
  bounds,
  minPixels = 0.7,
) {
  camera.updateMatrixWorld(true);
  const depthScene = new T.Scene();
  depthScene.background = new T.Color(1, 1, 1);
  const clone = aircraft.clone(true);
  clone.traverse((o) => {
    if (o.name.startsWith("livery_")) o.visible = false;
  });
  depthScene.add(clone);
  const depth = new T.ShaderMaterial({
    side: T.DoubleSide,
    vertexShader:
      "void main(){gl_Position=projectionMatrix*modelViewMatrix*vec4(position,1.0);}",
    fragmentShader:
      "void main(){gl_FragColor=vec4(gl_FragCoord.z,0.0,0.0,1.0);}",
  });
  depthScene.overrideMaterial = depth;
  const target = new T.WebGLRenderTarget(width, height, {
    type: T.FloatType,
    minFilter: T.NearestFilter,
    magFilter: T.NearestFilter,
  });
  const previous = renderer.getRenderTarget();
  renderer.setRenderTarget(target);
  renderer.render(depthScene, camera);
  const pixels = new Float32Array(width * height * 4);
  renderer.readRenderTargetPixels(target, 0, 0, width, height, pixels);
  renderer.setRenderTarget(previous);
  target.dispose();
  depth.dispose();

  const direction = new T.Vector3();
  camera.getWorldDirection(direction);
  const point = new T.Vector3();
  const mid = new T.Vector3();
  const projected = new T.Vector3();
  const segments = [];
  const seen = new Set();
  const emit = (start, end) => {
    const p0 = start.clone().project(camera),
      p1 = end.clone().project(camera);
    if (
      Math.hypot(((p0.x - p1.x) * width) / 2, ((p0.y - p1.y) * height) / 2) <
      minPixels
    )
      return;
    const xy = (v) =>
      [
        bounds[0] + ((v.x + 1) * bounds[2]) / 2,
        bounds[1] + ((1 - v.y) * bounds[3]) / 2,
      ].map((x) => +x.toFixed(3));
    const left = xy(p0).join(","),
      right = xy(p1).join(",");
    const key = [left, right].sort().join("|");
    if (!seen.has(key)) {
      segments.push([left, right]);
      seen.add(key);
    }
  };
  for (const edge of edges) {
    const { a, b, normals } = edge;
    const facing = camera.isOrthographicCamera
      ? direction
      : direction
          .subVectors(mid.addVectors(a, b).multiplyScalar(0.5), camera.position)
          .normalize();
    const crease =
      normals.length < 2 || normals.some((n) => n.dot(normals[0]) < 0.9);
    const silhouette =
      normals.some((n) => n.dot(facing) < 0) &&
      normals.some((n) => n.dot(facing) >= 0);
    if (!crease && !silhouette) continue;
    const screenA = a.clone().project(camera),
      screenB = b.clone().project(camera);
    const length = Math.hypot(
      ((screenA.x - screenB.x) * width) / 2,
      ((screenA.y - screenB.y) * height) / 2,
    );
    if (length < minPixels) continue;
    const steps = Math.max(1, Math.ceil(length / 3));
    let start = null;
    for (let i = 0; i <= steps; i++) {
      point.lerpVectors(a, b, i / steps);
      projected.copy(point).project(camera);
      const x = Math.round(((projected.x + 1) * width) / 2),
        y = Math.round(((projected.y + 1) * height) / 2);
      let visible = false;
      for (let dy = -1; dy <= 1 && !visible; dy++)
        for (let dx = -1; dx <= 1 && !visible; dx++) {
          const px = x + dx,
            py = y + dy;
          if (px >= 0 && px < width && py >= 0 && py < height)
            visible =
              (projected.z + 1) / 2 <= pixels[(py * width + px) * 4] + 0.00018;
        }
      if (visible && !start) start = point.clone();
      if (start && (!visible || i === steps)) {
        const end = visible
          ? point
          : point.clone().lerpVectors(a, b, Math.max(0, i - 1) / steps);
        emit(start, end);
        start = null;
      }
    }
  }
  // Join adjoining pieces so rounded windows and contours draw as continuous paths.
  const adjacent = new Map();
  segments.forEach((ends, index) =>
    ends.forEach((key) => {
      if (!adjacent.has(key)) adjacent.set(key, []);
      adjacent.get(key).push(index);
    }),
  );
  const used = new Set();
  const paths = [];
  const trace = (start, first) => {
    let at = start,
      index = first,
      path = `M${start}`;
    while (!used.has(index)) {
      used.add(index);
      const ends = segments[index];
      at = ends[0] === at ? ends[1] : ends[0];
      path += `L${at}`;
      const next = adjacent.get(at);
      if (next.length !== 2) break;
      index = next.find((candidate) => !used.has(candidate));
      if (index === undefined) break;
    }
    paths.push(path);
  };
  for (const [key, links] of adjacent) {
    if (links.length !== 2)
      for (const index of links) if (!used.has(index)) trace(key, index);
  }
  segments.forEach(([start], index) => {
    if (!used.has(index)) trace(start, index);
  });
  return paths;
}
