"use client";

import { Suspense, useEffect, useMemo, useRef } from "react";
import { Canvas, useFrame, useThree } from "@react-three/fiber";
import { ContactShadows, Environment, Html, Lightformer, useGLTF } from "@react-three/drei";
import * as THREE from "three";

/**
 * EI-NSA in real time. Each surface is either blueprint (white edges on cyanotype) or ink
 * (the PBR livery), split by a sweep plane that travels nose → tail. The camera starts as a
 * near-orthographic side elevation that matches the SVG drawing, then dollies to a 3/4 view.
 *
 * Model space (from Blender): x = metres aft of the nose, y = up, z = port (+) / starboard (−).
 */

export type AircraftProgress = { sweep: number; orbit: number; lines: number; leak: number };

const LINE = new THREE.Color("#e8f0fa");
const SWEEP_MIN = -2;
const SWEEP_MAX = 47;

type Uniforms = { uSweep: { value: number }; uLines: { value: number } };

function patchInk(mat: THREE.Material, u: Uniforms) {
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

function Model({ progress }: { progress: React.RefObject<AircraftProgress> }) {
  const { scene } = useGLTF("/renders/a321.glb");
  const uniforms = useMemo<Uniforms>(() => ({ uSweep: { value: SWEEP_MIN }, uLines: { value: 1 } }), []);

  const { root, edges, ghost } = useMemo(() => {
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
          gl_FragColor = vec4(mix(uColor, vec3(1.0, 0.55, 0.42), edge), (0.85 + edge * 0.15) * uLines);
        }`,
    });
    const ghostMat = new THREE.ShaderMaterial({
      transparent: true,
      depthWrite: true,
      uniforms: { uSweep: uniforms.uSweep, uLines: uniforms.uLines },
      vertexShader: /* glsl */ `
        varying vec3 vW; varying vec3 vN;
        void main() { vec4 w = modelMatrix * vec4(position, 1.0); vW = w.xyz; vN = normalize(mat3(modelMatrix) * normal); gl_Position = projectionMatrix * viewMatrix * w; }`,
      fragmentShader: /* glsl */ `
        uniform float uSweep; uniform float uLines; varying vec3 vW; varying vec3 vN;
        void main() {
          if (vW.x < uSweep) discard;
          float rim = pow(1.0 - abs(vN.z), 2.0);
          gl_FragColor = vec4(mix(vec3(0.075, 0.227, 0.388), vec3(0.20, 0.42, 0.64), rim), (0.22 + rim * 0.25) * uLines);
        }`,
    });

    root.updateMatrixWorld(true);
    root.traverse((o) => {
      const mesh = o as THREE.Mesh;
      if (!mesh.isMesh) return;
      const mats = Array.isArray(mesh.material) ? mesh.material : [mesh.material];
      mats.forEach((m) => {
        const mm = m.clone();
        patchInk(mm, uniforms);
        if (Array.isArray(mesh.material)) mesh.material[mats.indexOf(m)] = mm;
        else mesh.material = mm;
      });
      mesh.castShadow = true;
      // blueprint edges + a cyanotype "ghost" fill behind them
      const eg = new THREE.EdgesGeometry(mesh.geometry, 28);
      const seg = new THREE.LineSegments(eg, lineMat);
      seg.applyMatrix4(mesh.matrixWorld);
      seg.renderOrder = 2;
      edges.add(seg);
      const g = new THREE.Mesh(mesh.geometry, ghostMat);
      g.applyMatrix4(mesh.matrixWorld);
      g.renderOrder = 1;
      ghost.add(g);
    });
    return { root, edges, ghost };
  }, [scene, uniforms]);

  useFrame(() => {
    const p = progress.current;
    if (!p) return;
    uniforms.uSweep.value = SWEEP_MIN + (SWEEP_MAX - SWEEP_MIN) * p.sweep;
    uniforms.uLines.value = p.lines;
  });

  return (
    <group>
      <primitive object={root} />
      <primitive object={ghost} />
      <primitive object={edges} />
    </group>
  );
}

/** Near-orthographic side elevation → perspective 3/4, driven by progress.orbit. */
function CameraRig({ progress }: { progress: React.RefObject<AircraftProgress> }) {
  const { camera, size } = useThree();
  const target = useMemo(() => new THREE.Vector3(), []);
  useFrame(() => {
    const cam = camera as THREE.PerspectiveCamera;
    const o = progress.current?.orbit ?? 0;
    const e = o * o * (3 - 2 * o);
    // start: telephoto far away on the port side, framing x∈[-3, 50] like the SVG viewBox
    const aspect = size.width / size.height;
    const startFov = 4;
    const halfW = 26.5;
    const startDist = halfW / (Math.tan(THREE.MathUtils.degToRad(startFov / 2)) * aspect);
    const fov = THREE.MathUtils.lerp(startFov, 30, e);
    const az = THREE.MathUtils.lerp(0, -0.72, e); // swing toward the nose
    const el = THREE.MathUtils.lerp(0.0, 0.16, e);
    const dist = THREE.MathUtils.lerp(startDist, 80, e);
    target.set(THREE.MathUtils.lerp(23.5, 22.5, e), THREE.MathUtils.lerp(5.6, 4.2, e), THREE.MathUtils.lerp(0, -2, e));
    cam.fov = fov;
    cam.near = 0.5;
    cam.far = startDist + 200;
    cam.position.set(target.x + Math.sin(az) * dist * Math.cos(el), target.y + Math.sin(el) * dist, Math.cos(az) * dist * Math.cos(el));
    cam.lookAt(target);
    cam.updateProjectionMatrix();
  });
  return null;
}

function Leak({ progress }: { progress: React.RefObject<AircraftProgress> }) {
  const ref = useRef<HTMLDivElement>(null);
  useFrame(() => {
    if (ref.current) ref.current.style.opacity = String(progress.current?.leak ?? 0);
  });
  return (
    <Html position={[17.6, 1.6, 6.9]} center zIndexRange={[20, 0]}>
      <div ref={ref} className="pointer-events-none flex items-center gap-2 whitespace-nowrap opacity-0">
        <span className="relative flex h-3 w-3">
          <span className="absolute inline-flex h-full w-full animate-ping rounded-full bg-[#ff7a5c] opacity-60" />
          <span className="relative inline-flex h-3 w-3 rounded-full bg-[#ff7a5c]" />
        </span>
        <span className="rounded bg-[#1d1210]/85 px-2 py-1 font-mono text-[11px] text-[#ffb3a1]">ENG 1 EDP · LEAK 07:55Z</span>
      </div>
    </Html>
  );
}

export function AircraftScene({ progress, className }: { progress: React.RefObject<AircraftProgress>; className?: string }) {
  useEffect(() => {
    useGLTF.preload("/renders/a321.glb");
  }, []);
  return (
    <Canvas
      className={className}
      dpr={[1, 1.75]}
      gl={{ antialias: true, alpha: true, powerPreference: "high-performance", toneMapping: THREE.ACESFilmicToneMapping, outputColorSpace: THREE.SRGBColorSpace }}
      camera={{ fov: 4, position: [23.5, 5.6, 700], near: 0.5, far: 1000 }}
      shadows={false}
    >
      <hemisphereLight args={["#dfe8f2", "#1a1f27", 0.6]} />
      <directionalLight position={[30, 40, 60]} intensity={1.6} color="#fff4e8" />
      <directionalLight position={[-40, 10, -30]} intensity={0.7} color="#9fc0ff" />
      <Environment resolution={256} frames={1}>
        <Lightformer form="rect" intensity={2.2} position={[0, 18, 10]} scale={[60, 6, 1]} color="#ffffff" />
        <Lightformer form="rect" intensity={1.2} position={[-30, 6, 20]} rotation-y={0.9} scale={[30, 10, 1]} color="#cfe0ff" />
        <Lightformer form="rect" intensity={0.8} position={[40, 4, -20]} rotation-y={-2.2} scale={[30, 8, 1]} color="#ffd9c2" />
        <Lightformer form="circle" intensity={3} position={[10, 30, -10]} scale={8} color="#ffffff" />
      </Environment>
      <Suspense fallback={null}>
        <Model progress={progress} />
        <Leak progress={progress} />
        <ContactShadows position={[22, 0.01, 0]} scale={[70, 50]} far={10} blur={2.4} opacity={0.55} resolution={512} color="#000000" />
      </Suspense>
      <CameraRig progress={progress} />
    </Canvas>
  );
}
