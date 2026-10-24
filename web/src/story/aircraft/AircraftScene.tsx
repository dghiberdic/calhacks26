/* oxlint-disable react/immutability -- three.js objects (uniforms, the camera, the fans) are mutated per frame by design. */
import { Suspense, useEffect, useMemo, useRef, useState, type RefObject } from "react";
import { Canvas, useFrame, useThree } from "@react-three/fiber";
import { ContactShadows, Environment, Lightformer, PerformanceMonitor, useGLTF } from "@react-three/drei";
import * as THREE from "three";
import { asset } from "../data/assets";

/**
 * EI-NSB in real time. Each surface is either blueprint (white edges on cyanotype) or ink (the PBR
 * livery), split by a sweep plane that travels nose → tail. The camera starts as a near-orthographic
 * port elevation that matches the SVG drawing, then dollies and walks around the nose to the
 * starboard side, where the engine-2 pump is leaking. Once it gets there the aircraft stands on a wet
 * apron, the camera keeps drifting a little, the fans windmill and the pump drips.
 *
 * Model space (Blender export): x = metres aft of the nose, y = up, z = port (+) / starboard (−).
 */

/** Scroll-driven: show (canvas visible), sweep (ink), orbit (camera), lines (blueprint edges), leak (label). */
export type AircraftProgress = { sweep: number; orbit: number; lines: number; leak: number; show: number };

const MODEL = asset("a321.glb");
const LINE = new THREE.Color("#e8f0fa");
const SWEEP_MIN = -2;
const SWEEP_MAX = 47;
/** The engine-2 (starboard) driven pump: lower outboard side of the right nacelle. */
const LEAK_AT = new THREE.Vector3(17.6, 1.55, -6.85);
/** End of the walk-around: front-starboard three-quarter view (radians, 0 = port side, −π/2 = head-on). */
const AZ_END = -(Math.PI - 0.8);

type Uniforms = { uSweep: { value: number }; uLines: { value: number } };

function patchInk(mat: THREE.Material, u: Uniforms) {
  // the blueprint edges lie exactly on these surfaces: push the surfaces back so the lines never z-fight
  mat.polygonOffset = true;
  mat.polygonOffsetFactor = 1;
  mat.polygonOffsetUnits = 1;
  mat.onBeforeCompile = (shader) => {
    shader.uniforms.uSweep = u.uSweep;
    shader.vertexShader = shader.vertexShader
      .replace("#include <common>", "#include <common>\nvarying vec3 vWorldPosInk;")
      .replace("#include <worldpos_vertex>", "#include <worldpos_vertex>\nvWorldPosInk = (modelMatrix * vec4(transformed, 1.0)).xyz;");
    shader.fragmentShader = shader.fragmentShader
      .replace("#include <common>", "#include <common>\nvarying vec3 vWorldPosInk;\nuniform float uSweep;")
      .replace("void main() {", "void main() {\n  if (vWorldPosInk.x > uSweep) discard;");
  };
  mat.needsUpdate = true;
}

function Model({ progress }: { progress: RefObject<AircraftProgress> }) {
  const { scene } = useGLTF(MODEL, false, false);
  const uniforms = useMemo<Uniforms>(() => ({ uSweep: { value: SWEEP_MIN }, uLines: { value: 1 } }), []);

  const { root, edges, ghost, jobs } = useMemo(() => {
    const root = scene.clone(true);
    const edges = new THREE.Group();
    const ghost = new THREE.Group();
    const lineMat = new THREE.ShaderMaterial({
      transparent: true,
      depthWrite: false,
      uniforms: { uSweep: uniforms.uSweep, uLines: uniforms.uLines, uColor: { value: LINE } },
      vertexShader: /* glsl */ `
        varying vec3 vW;
        void main() { vec4 w = modelMatrix * vec4(position, 1.0); vW = w.xyz; gl_Position = projectionMatrix * viewMatrix * w; }`,
      fragmentShader: /* glsl */ `
        uniform float uSweep; uniform float uLines; uniform vec3 uColor; varying vec3 vW;
        void main() {
          float d = vW.x - uSweep;
          if (d < 0.0) discard;
          float edge = 1.0 - smoothstep(0.0, 1.6, d);
          gl_FragColor = vec4(mix(uColor, vec3(0.62, 0.83, 1.0), edge), (0.85 + edge * 0.15) * uLines);
        }`,
    });
    const ghostMat = new THREE.ShaderMaterial({
      transparent: true,
      depthWrite: true,
      polygonOffset: true,
      polygonOffsetFactor: 1,
      polygonOffsetUnits: 1,
      uniforms: { uSweep: uniforms.uSweep, uLines: uniforms.uLines },
      vertexShader: /* glsl */ `
        varying vec3 vW; varying vec3 vN;
        void main() { vec4 w = modelMatrix * vec4(position, 1.0); vW = w.xyz; vN = normalize(mat3(modelMatrix) * normal); gl_Position = projectionMatrix * viewMatrix * w; }`,
      fragmentShader: /* glsl */ `
        uniform float uSweep; uniform float uLines; varying vec3 vW; varying vec3 vN;
        void main() {
          if (vW.x < uSweep) discard;
          float rim = pow(1.0 - abs(vN.z), 2.0);
          gl_FragColor = vec4(mix(vec3(0.067, 0.208, 0.353), vec3(0.19, 0.40, 0.62), rim), (0.22 + rim * 0.25) * uLines);
        }`,
    });

    // EdgesGeometry over ~117k triangles is too slow for one frame: each mesh's edges are a job for idle time.
    const jobs: (() => void)[] = [];
    root.updateMatrixWorld(true);
    root.traverse((o) => {
      const mesh = o as THREE.Mesh;
      if (!mesh.isMesh) return;
      if (Array.isArray(mesh.material)) {
        mesh.material = mesh.material.map((m) => {
          const c = m.clone();
          patchInk(c, uniforms);
          return c;
        });
      } else {
        const c = mesh.material.clone();
        patchInk(c, uniforms);
        mesh.material = c;
      }
      let built = false;
      jobs.push(() => {
        if (built) return;
        built = true;
        const seg = new THREE.LineSegments(new THREE.EdgesGeometry(mesh.geometry, 28), lineMat);
        seg.applyMatrix4(mesh.matrixWorld);
        seg.renderOrder = 2;
        edges.add(seg);
      });
      const g = new THREE.Mesh(mesh.geometry, ghostMat);
      g.applyMatrix4(mesh.matrixWorld);
      g.renderOrder = 1;
      ghost.add(g);
    });
    return { root, edges, ghost, jobs };
  }, [scene, uniforms]);

  const invalidate = useThree((s) => s.invalidate);
  useEffect(() => {
    const idle = window.requestIdleCallback ?? ((cb: IdleRequestCallback) => window.setTimeout(() => cb({ didTimeout: true, timeRemaining: () => 0 }), 32));
    const cancelIdle = window.cancelIdleCallback ?? window.clearTimeout;
    let i = 0;
    let handle = 0;
    const step = (deadline: IdleDeadline) => {
      do jobs[i++]();
      while (i < jobs.length && deadline.timeRemaining() > 6);
      invalidate();
      if (i < jobs.length) handle = idle(step, { timeout: 400 });
    };
    handle = idle(step, { timeout: 400 });
    return () => cancelIdle(handle);
  }, [jobs, invalidate]);

  const fans = useMemo(() => ["engine_1_fan", "engine_2_fan"].map((n) => root.getObjectByName(n)).filter((o): o is THREE.Object3D => !!o), [root]);

  useFrame((_, dt) => {
    const p = progress.current;
    if (!p) return;
    uniforms.uSweep.value = SWEEP_MIN + (SWEEP_MAX - SWEEP_MIN) * p.sweep;
    uniforms.uLines.value = p.lines;
    // a grounded engine windmills slowly in the wind
    for (const f of fans) f.rotation.x += dt * 0.9;
  });

  return (
    <group>
      <primitive object={root} />
      <primitive object={ghost} />
      <primitive object={edges} />
    </group>
  );
}

/** Near-orthographic port elevation → perspective three-quarter view of the starboard side. */
function CameraRig({ progress }: { progress: RefObject<AircraftProgress> }) {
  const { camera, size } = useThree();
  const target = useMemo(() => new THREE.Vector3(), []);
  useFrame((state) => {
    const cam = camera as THREE.PerspectiveCamera;
    const o = progress.current?.orbit ?? 0;
    const e = o * o * (3 - 2 * o);
    const aspect = size.width / Math.max(size.height, 1);
    const halfTan = (fovDeg: number) => Math.tan(THREE.MathUtils.degToRad(fovDeg / 2));
    // start: telephoto far out on the port side, framing x ∈ [−3, 50] like the SVG drawing's view box
    const startFov = 4;
    const halfW0 = 26.5;
    const fov = THREE.MathUtils.lerp(startFov, 30, e);
    // Dolly zoom: the framed width eases from the drawing's to the three-quarter view's while the lens
    // widens, so the aircraft holds its size and only the perspective changes. Narrow screens back off.
    const fit = Math.max(1, 1.05 / aspect);
    const halfW = THREE.MathUtils.lerp(halfW0, 72 * fit * halfTan(30) * aspect, e);
    const dist = halfW / (halfTan(fov) * aspect);
    // at the end of the walk-around the camera keeps breathing: a slow sway and a slight rise and fall
    const t = state.clock.elapsedTime;
    const idle = e * e * e;
    const az = THREE.MathUtils.lerp(0, AZ_END, e) + idle * 0.055 * Math.sin(t * 0.21);
    const el = THREE.MathUtils.lerp(0, 0.17, e) + idle * 0.016 * Math.sin(t * 0.13 + 1.2);
    target.set(THREE.MathUtils.lerp(23.5, 21, e), THREE.MathUtils.lerp(5.6, 3.6, e), THREE.MathUtils.lerp(0, -2.5, e));
    cam.fov = fov;
    cam.near = 0.5;
    cam.far = dist + 200;
    cam.position.set(target.x + Math.sin(az) * dist * Math.cos(el), target.y + Math.sin(el) * dist, target.z + Math.cos(az) * dist * Math.cos(el));
    cam.lookAt(target);
    cam.updateProjectionMatrix();
  }, -1);
  return null;
}

/** A soft-edged disc: the apron fades into the night instead of ending. */
function radialAlpha() {
  const c = document.createElement("canvas");
  c.width = c.height = 256;
  const g = c.getContext("2d")!;
  const grad = g.createRadialGradient(128, 128, 0, 128, 128, 128);
  grad.addColorStop(0, "#fff");
  grad.addColorStop(0.3, "#d0d0d0");
  grad.addColorStop(0.7, "#3a3a3a");
  grad.addColorStop(1, "#000");
  g.fillStyle = grad;
  g.fillRect(0, 0, 256, 256);
  const t = new THREE.CanvasTexture(c);
  t.colorSpace = THREE.NoColorSpace;
  return t;
}

const DRIP_TOP = LEAK_AT.y - 0.12;
const DRIPS = 3;
const DRIP_EVERY = 1.35;

/**
 * The wet apron under the aircraft once it is inked: dark, glossy, catching the environment's light. Under
 * the engine-2 pump, Skydrol (violet) drips onto a slowly spreading puddle. Both fade in with the leak label.
 */
function Apron({ progress }: { progress: RefObject<AircraftProgress> }) {
  const alpha = useMemo(() => radialAlpha(), []);
  const ground = useRef<THREE.MeshStandardMaterial>(null);
  const puddle = useRef<THREE.Mesh>(null);
  const puddleMat = useRef<THREE.MeshStandardMaterial>(null);
  const drops = useRef<(THREE.Mesh | null)[]>([]);
  const born = useRef(-1);
  useFrame((state) => {
    const p = progress.current;
    if (!p) return;
    const wet = 1 - p.lines;
    if (ground.current) ground.current.opacity = 0.95 * wet;
    const t = state.clock.elapsedTime;
    if (p.leak > 0.01 && born.current < 0) born.current = t;
    if (p.leak <= 0.01) born.current = -1;
    const since = born.current < 0 ? 0 : t - born.current;
    if (puddle.current && puddleMat.current) {
      const r = 0.25 + 0.95 * (1 - Math.exp(-since / 9));
      puddle.current.scale.set(r * 1.25, r, 1);
      puddleMat.current.opacity = 0.9 * p.leak;
    }
    drops.current.forEach((d, i) => {
      if (!d) return;
      const phase = (t + i * (DRIP_EVERY / DRIPS)) % DRIP_EVERY;
      const y = DRIP_TOP - 4.9 * phase * phase; // free fall
      d.visible = p.leak > 0.5 && y > 0.02;
      d.position.y = Math.max(0.02, y);
      const s = phase < 0.08 ? phase / 0.08 : 1; // a drop forms before it falls
      d.scale.setScalar(s);
    });
  });
  return (
    <group>
      <mesh rotation-x={-Math.PI / 2} position={[21, 0, -3]} renderOrder={0}>
        <circleGeometry args={[34, 96]} />
        <meshStandardMaterial ref={ground} color="#0a111e" roughness={0.42} metalness={0} envMapIntensity={0.6} alphaMap={alpha} transparent opacity={0} depthWrite={false} />
      </mesh>
      <mesh ref={puddle} rotation-x={-Math.PI / 2} position={[LEAK_AT.x + 0.2, 0.015, LEAK_AT.z]} renderOrder={1}>
        <circleGeometry args={[1, 48]} />
        <meshStandardMaterial ref={puddleMat} color="#2a1840" roughness={0.04} metalness={0} envMapIntensity={1.6} transparent opacity={0} depthWrite={false} />
      </mesh>
      {Array.from({ length: DRIPS }, (_, i) => (
        <mesh key={i} ref={(m) => void (drops.current[i] = m)} position={[LEAK_AT.x, DRIP_TOP, LEAK_AT.z + 0.15]} visible={false}>
          <sphereGeometry args={[0.055, 12, 10]} />
          <meshStandardMaterial color="#6d4fa0" roughness={0.05} metalness={0} emissive="#24163a" />
        </mesh>
      ))}
    </group>
  );
}

/** Pins the DOM label to the engine-2 pump: projected through the camera each frame. */
function Leak({ progress, label }: { progress: RefObject<AircraftProgress>; label: RefObject<HTMLDivElement | null> }) {
  const { camera, size } = useThree();
  const v = useMemo(() => new THREE.Vector3(), []);
  useFrame(() => {
    const el = label.current;
    if (!el) return;
    v.copy(LEAK_AT).project(camera);
    const px = ((v.x + 1) / 2) * size.width;
    const py = ((1 - v.y) / 2) * size.height;
    // Reads to the right of the pump; flips to the left if that runs off the canvas; on a canvas too narrow
    // for either, it sits under the pump, kept inside the edges.
    const w = el.offsetWidth;
    const right = px + w <= size.width - 8;
    const left = px - w >= 8;
    el.style.flexDirection = right || !left ? "row" : "row-reverse";
    const x = right ? px - 6 : left ? px - w + 6 : Math.min(Math.max(8, px - 6), size.width - w - 8);
    const y = right || left ? py : py + 18;
    el.style.transform = `translate(${x}px, ${y}px) translate(0, -50%)`;
    el.style.opacity = String(progress.current?.leak ?? 0);
  });
  return null;
}

/**
 * Mounted with the model while the canvas is still invisible: compiles every program (in parallel where
 * KHR_parallel_shader_compile exists) and draws one hidden frame, so the environment map and contact
 * shadow are baked before the handoff instead of stalling its first visible frame.
 */
function Warmup() {
  const { gl, scene, camera, invalidate } = useThree();
  useEffect(() => {
    let live = true;
    gl.compileAsync(scene, camera)
      .then(() => live && invalidate())
      .catch(() => {});
    return () => {
      live = false;
    };
  }, [gl, scene, camera, invalidate]);
  return null;
}

/**
 * With frameloop="demand", a frame is drawn only while the canvas is on screen and not faded out: every
 * frame while the scroll moves the scene or the camera idles at the end, every other frame for the fans.
 */
function Pump({ wrap, progress }: { wrap: RefObject<HTMLDivElement | null>; progress: RefObject<AircraftProgress> }) {
  const invalidate = useThree((s) => s.invalidate);
  useEffect(() => {
    const el = wrap.current;
    if (!el) return;
    let onScreen = false;
    const io = new IntersectionObserver(([e]) => (onScreen = e.isIntersecting));
    io.observe(el);
    let raf = 0;
    let last = "";
    let idle = 0;
    const loop = () => {
      raf = requestAnimationFrame(loop);
      const p = progress.current;
      if (!onScreen || !p || p.show <= 0.001) return;
      const key = `${p.sweep}|${p.orbit}|${p.lines}|${p.leak}|${p.show}`;
      // moving with the scroll, or idling at the end (camera sway, drips): every frame; the fans alone: every other
      if (key !== last || p.orbit > 0.95 || ++idle % 2 === 0) invalidate();
      if (key !== last) idle = 0;
      last = key;
    };
    raf = requestAnimationFrame(loop);
    return () => {
      cancelAnimationFrame(raf);
      io.disconnect();
    };
  }, [wrap, progress, invalidate]);
  return null;
}

export default function AircraftScene({ progress, leak, fallback, className }: { progress: RefObject<AircraftProgress>; leak: { title: string; detail: string }; fallback: string; className?: string }) {
  const wrap = useRef<HTMLDivElement>(null);
  const label = useRef<HTMLDivElement>(null);
  // full retina (2×) unless the GPU can't hold the frame rate, then step down
  const [dpr, setDpr] = useState(2);
  return (
    <div ref={wrap} className={className}>
      <Canvas
        frameloop="demand"
        dpr={[1, dpr]}
        gl={{ antialias: true, alpha: true, powerPreference: "high-performance", toneMapping: THREE.AgXToneMapping, toneMappingExposure: 1.05, outputColorSpace: THREE.SRGBColorSpace }}
        camera={{ fov: 4, position: [23.5, 5.6, 700], near: 0.5, far: 1000 }}
        shadows={false}
        fallback={<img src={fallback} alt="Rendering of EI-NSB on a wet stand at Dublin" className="h-full w-full object-contain" />}
      >
        <hemisphereLight args={["#dfe8f2", "#1a1f27", 0.6]} />
        <directionalLight position={[30, 40, -60]} intensity={1.6} color="#fff4e8" />
        <directionalLight position={[-40, 10, 30]} intensity={0.7} color="#9fc0ff" />
        <Environment resolution={256} frames={1}>
          <Lightformer form="rect" intensity={2.2} position={[0, 18, -10]} scale={[60, 6, 1]} color="#ffffff" />
          <Lightformer form="rect" intensity={1.2} position={[-30, 6, -20]} rotation-y={-0.9} scale={[30, 10, 1]} color="#cfe0ff" />
          <Lightformer form="rect" intensity={0.8} position={[40, 4, 20]} rotation-y={2.2} scale={[30, 8, 1]} color="#ffd9c2" />
          <Lightformer form="circle" intensity={3} position={[10, 30, 10]} scale={8} color="#ffffff" />
        </Environment>
        <PerformanceMonitor onDecline={() => setDpr((d) => Math.max(1, d - 0.5))} />
        <Suspense fallback={null}>
          <Model progress={progress} />
          <Apron progress={progress} />
          <Leak progress={progress} label={label} />
          {/* the aircraft never moves, so its shadow is drawn once */}
          <ContactShadows frames={1} position={[21, 0.01, -3]} scale={[84, 80]} far={10} blur={2.6} opacity={0.55} resolution={1024} color="#000000" />
          <Warmup />
        </Suspense>
        <CameraRig progress={progress} />
        <Pump wrap={wrap} progress={progress} />
      </Canvas>
      <div ref={label} className="pointer-events-none absolute left-0 top-0 flex items-center gap-2 whitespace-nowrap opacity-0" aria-hidden="true">
        <span className="relative flex size-3">
          <span className="absolute inline-flex size-full animate-ping rounded-full bg-notweather opacity-60" />
          <span className="relative inline-flex size-3 rounded-full bg-notweather" />
        </span>
        <span className="rounded-md bg-[#160d10]/90 px-2.5 py-1.5 leading-tight shadow-[0_0_0_1px_rgba(226,69,44,0.35)]">
          <span className="block font-mono text-[11.5px] text-[#ffb3a1]">{leak.title}</span>
          <span className="mt-0.5 block text-[11.5px] text-cloud-300">{leak.detail}</span>
        </span>
      </div>
    </div>
  );
}

useGLTF.preload(MODEL, false, false);
