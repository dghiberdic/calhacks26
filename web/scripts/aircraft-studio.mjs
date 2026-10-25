// Asset authoring only. Open /scripts/aircraft-studio.html on the Vite dev server.
import * as T from "three";
import { GLTFLoader } from "three/addons/loaders/GLTFLoader.js";
import { GLTFExporter } from "three/addons/exporters/GLTFExporter.js";
import { applyStormCheckLivery } from "./aircraft-livery.mjs";
import { aircraftEdges, projectSketch } from "./aircraft-sketches.mjs";
import { OrbitControls } from "three/addons/controls/OrbitControls.js";
import { RoomEnvironment } from "three/addons/environments/RoomEnvironment.js";

const scene = new T.Scene();
scene.background = new T.Color("#080e17");
scene.fog = new T.Fog("#080e17", 100, 220);
const renderer = new T.WebGLRenderer({
  antialias: true,
  preserveDrawingBuffer: true,
});
renderer.setPixelRatio(Math.min(devicePixelRatio, 2));
renderer.toneMapping = T.AgXToneMapping;
renderer.toneMappingExposure = 1.15;
renderer.shadowMap.enabled = true;
renderer.shadowMap.type = T.PCFSoftShadowMap;
document.body.append(renderer.domElement);
const camera = new T.PerspectiveCamera(33, innerWidth / innerHeight, 0.1, 300);
const controls = new OrbitControls(camera, renderer.domElement);
controls.enableDamping = true;
const pmrem = new T.PMREMGenerator(renderer);
const environment = new RoomEnvironment();
scene.environment = pmrem.fromScene(environment, 0.04).texture;
scene.environmentIntensity = 0.65;
environment.dispose();
pmrem.dispose();
scene.add(new T.HemisphereLight("#ecf4ff", "#283847", 1.4));
const key = new T.DirectionalLight("#fff5e9", 3);
key.position.set(-15, 45, 25);
key.castShadow = true;
key.shadow.mapSize.set(2048, 2048);
Object.assign(key.shadow.camera, {
  left: -45,
  right: 45,
  top: 40,
  bottom: -40,
  near: 1,
  far: 130,
});
key.shadow.normalBias = 0.045;
key.target.position.set(20, 0, 0);
scene.add(key, key.target);
const fill = new T.DirectionalLight("#9fc1ff", 1.2);
fill.position.set(40, 15, -25);
scene.add(fill);
const ground = new T.Mesh(
  new T.PlaneGeometry(400, 400),
  new T.MeshStandardMaterial({
    color: "#050a10",
    roughness: 0.9,
    metalness: 0,
  }),
);
ground.rotation.x = -Math.PI / 2;
ground.position.y = -0.015;
ground.receiveShadow = true;
scene.add(ground);
const { scene: aircraft } = await new GLTFLoader().loadAsync(
  "/story/idg-a320neo/aircraft.glb?v=2",
);
applyStormCheckLivery(aircraft);
aircraft.traverse((o) => {
  if (o.isMesh) {
    o.castShadow = true;
    o.receiveShadow = true;
  }
});

scene.add(aircraft);
const views = {
  poster: { position: [-24, 11, 45], target: [18.5, 4.1, 0], fov: 28 },
  side: { position: [18.8, 7, 65], target: [18.8, 5.3, 0], fov: 38 },
  nose: { position: [-8, 7.5, 13], target: [2.5, 4.4, 0], fov: 35 },
  engine: { position: [6, 4, 11], target: [12.8, 2.5, 5.75], fov: 38 },
};
function view(name) {
  document.querySelector("#sketch").hidden = true;
  const v = views[name];
  camera.position.fromArray(v.position);
  controls.target.fromArray(v.target);
  camera.fov = v.fov;
  camera.updateProjectionMatrix();
  controls.update();
  document.querySelector("output").textContent =
    `${name} · drag to orbit, scroll to zoom`;
}
function resize() {
  renderer.setSize(innerWidth, innerHeight);
  camera.aspect = innerWidth / innerHeight;
  camera.updateProjectionMatrix();
}
addEventListener("resize", resize);
resize();
view("poster");
document
  .querySelectorAll("[data-view]")
  .forEach((button) => (button.onclick = () => view(button.dataset.view)));
renderer.setAnimationLoop(() => {
  controls.update();
  renderer.render(scene, camera);
});
function download(blob, name) {
  const a = document.createElement("a");
  a.href = URL.createObjectURL(blob);
  a.download = name;
  a.click();
  setTimeout(() => URL.revokeObjectURL(a.href), 1000);
}
const sideBounds = [-3, -13.4, 45, 15.6];
const topBounds = [-2, -19.4, 42, 38.8];
const sideCamera = new T.OrthographicCamera(-22.5, 22.5, 7.8, -7.8, 0.1, 200);
sideCamera.position.set(19.5, 5.6, 100);
sideCamera.lookAt(19.5, 5.6, 0);
const topCamera = new T.OrthographicCamera(-21, 21, 19.4, -19.4, 0.1, 200);
topCamera.position.set(19, 100, 0);
topCamera.up.set(0, 0, -1);
topCamera.lookAt(19, 0, 0);
let edges, sketches;
function getSketches() {
  edges ??= aircraftEdges(aircraft);
  sketches ??= {
    side: projectSketch(
      aircraft,
      edges,
      renderer,
      sideCamera,
      2250,
      780,
      sideBounds,
    ),
    top: projectSketch(
      aircraft,
      edges,
      renderer,
      topCamera,
      1680,
      1552,
      topBounds,
    ),
  };
  return sketches;
}
document.querySelectorAll("[data-sketch]").forEach((button) => {
  button.onclick = () => {
    const name = button.dataset.sketch;
    const bounds = name === "side" ? sideBounds : topBounds;
    const paths = getSketches()[name];
    const panel = document.querySelector("#sketch");
    panel.innerHTML = `<svg viewBox="${bounds.join(" ")}">${paths.map((d) => `<path d="${d}"/>`).join("")}</svg>`;
    panel.hidden = false;
    document.querySelector("output").textContent =
      `${name} sketch · projected directly from the StormCheck aircraft`;
  };
});

// One bundle carries the branded model, every drawing, both stills and their shared dimensions.
document.querySelector("#save").onclick = async () => {
  const button = document.querySelector("#save");
  button.disabled = true;
  try {
    view("poster");
    const pixelRatio = renderer.getPixelRatio();
    renderer.setPixelRatio(1);
    camera.aspect = 16 / 9;
    camera.updateProjectionMatrix();
    const images = {};
    for (const width of [1280, 2560]) {
      renderer.setSize(width, (width * 9) / 16, false);
      renderer.render(scene, camera);
      images[width] = renderer.domElement.toDataURL("image/webp", 0.92);
    }
    const sketches = getSketches();
    const lines = projectSketch(
      aircraft,
      edges,
      renderer,
      camera,
      2560,
      1440,
      [0, 0, 2560, 1440],
      3,
    );
    renderer.setPixelRatio(pixelRatio);
    resize();
    const exported = await new GLTFExporter().parseAsync(aircraft, {
      binary: true,
    });
    const model = await new Promise((resolve) => {
      const reader = new FileReader();
      reader.onload = () => resolve(reader.result);
      reader.readAsDataURL(new Blob([exported], { type: "model/gltf-binary" }));
    });
    const dimensions = new T.Box3()
      .setFromObject(aircraft)
      .getSize(new T.Vector3());
    download(
      new Blob(
        [
          JSON.stringify({
            model,
            images,
            lines,
            sketches,
            geometry: {
              length: dimensions.x,
              height: dimensions.y,
              span: dimensions.z,
            },
            views: { side: sideBounds, top: topBounds },
          }),
        ],
        { type: "application/json" },
      ),
      "stormcheck-aircraft-assets.json",
    );
    document.querySelector("output").textContent =
      "Saved model, both sketches, stills and shared measurements";
  } finally {
    button.disabled = false;
  }
};
