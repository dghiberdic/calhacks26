import * as THREE from "three";
import type { Box } from "../data/geo";

// The satellite frame drawn into map space and revealed by a watercolour wash: domain-warped fbm
// thresholded against distance from the storm centre, with a darker "wet edge" at the front.

const vert = /* glsl */ `
varying vec2 vUv;
void main() {
  vUv = uv;
  gl_Position = vec4(position.xy, 0.0, 1.0);
}`;

const frag = /* glsl */ `
precision highp float;
varying vec2 vUv;
uniform sampler2D uSat;
uniform vec4 uSatBox;   // map-space x0, y0, x1, y1 of the image (y0 = north edge)
uniform vec4 uView;     // map-space x0, y0, x1, y1 of the viewport
uniform vec2 uOrigin;   // map-space point the wash bleeds out from
uniform float uReveal;  // 0 → drawing only, 1 → full satellite
uniform float uTime;
uniform vec3 uNight;

float hash(vec2 p) { p = fract(p * vec2(123.34, 456.21)); p += dot(p, p + 45.32); return fract(p.x * p.y); }
float noise(vec2 p) {
  vec2 i = floor(p), f = fract(p);
  float a = hash(i), b = hash(i + vec2(1.0, 0.0)), c = hash(i + vec2(0.0, 1.0)), d = hash(i + vec2(1.0, 1.0));
  vec2 u = f * f * (3.0 - 2.0 * f);
  return mix(mix(a, b, u.x), mix(c, d, u.x), u.y);
}
float fbm(vec2 p) {
  float v = 0.0, a = 0.5;
  for (int i = 0; i < 5; i++) { v += a * noise(p); p = p * 2.03 + vec2(17.1, 9.2); a *= 0.5; }
  return v;
}

void main() {
  vec2 m = vec2(mix(uView.x, uView.z, vUv.x), mix(uView.w, uView.y, vUv.y));
  vec2 suv = (m - uSatBox.xy) / (uSatBox.zw - uSatBox.xy);
  vec3 sat = texture2D(uSat, vec2(suv.x, suv.y)).rgb;
  // Feather the frame edges and treat swath gaps (pure black) as no data.
  float inside = smoothstep(0.0, 0.035, suv.x) * smoothstep(1.0, 0.965, suv.x) * smoothstep(0.0, 0.06, suv.y) * smoothstep(1.0, 0.94, suv.y);
  inside *= smoothstep(0.015, 0.07, max(sat.r, max(sat.g, sat.b)));

  // Grade: lift the cloud tops, cool the ocean toward the night navy, keep land muted.
  float lum = dot(sat, vec3(0.299, 0.587, 0.114));
  vec3 graded = mix(vec3(lum), sat, 0.68);
  graded = pow(graded, vec3(1.12));
  graded = mix(graded, graded * vec3(0.84, 0.92, 1.08), 1.0 - smoothstep(0.15, 0.6, lum));
  graded *= 0.9;

  // Wash front: distance from the storm centre, roughened by warped fbm. Once the wash is complete the
  // noise is skipped (a uniform branch), which is most of the time the hero is on screen.
  float mask = 1.0;
  float wetEdge = 0.0;
  float n = 0.0;
  if (uReveal < 0.999) {
    vec2 q = m * 0.11;
    vec2 warp = vec2(fbm(q + uTime * 0.015), fbm(q + vec2(5.2, 1.3) - uTime * 0.012));
    n = fbm(q * 1.7 + warp * 1.6);
    float d = length((m - uOrigin) * vec2(1.0, 1.15)) / 38.0;
    float field = d * 0.85 + n * 0.55;
    float front = uReveal * 1.55 - 0.05;
    mask = 1.0 - smoothstep(front - 0.035, front + 0.01, field);
    wetEdge = smoothstep(front - 0.11, front - 0.02, field) * mask;
  }

  vec3 col = mix(uNight, graded, mask * inside);
  col *= 1.0 - wetEdge * 0.38;
  col += vec3(0.05, 0.07, 0.09) * wetEdge * (1.0 - n);

  // Vignette, and a legibility shade on the lower left where the headline sits.
  float vig = smoothstep(1.25, 0.35, length((vUv - vec2(0.5, 0.52)) * vec2(1.0, 1.25)));
  float shade = smoothstep(0.65, 0.0, vUv.x) * smoothstep(0.75, 0.0, vUv.y);
  col *= mix(0.6, 1.0, vig);
  col *= 1.0 - shade * 0.35;
  gl_FragColor = vec4(col, 1.0);
}`;

/** A full-screen quad: one texture, one draw call, rendered only when the hero is on screen. */
export class SatelliteLayer {
  readonly ready: Promise<void>;
  private readonly renderer: THREE.WebGLRenderer;
  private readonly scene = new THREE.Scene();
  private readonly camera = new THREE.OrthographicCamera(-1, 1, 1, -1, 0, 1);
  private readonly material: THREE.ShaderMaterial;
  private texture: THREE.Texture | null = null;

  constructor(opts: { canvas: HTMLCanvasElement; image: string; satBox: Box; origin: [number, number]; night: string }) {
    this.renderer = new THREE.WebGLRenderer({ canvas: opts.canvas, antialias: false, alpha: false, powerPreference: "high-performance" });
    // Clouds are soft and the image is already upscaled: 1.25× is indistinguishable and half the fragments of 2×.
    this.renderer.setPixelRatio(Math.min(window.devicePixelRatio || 1, 1.25));
    this.material = new THREE.ShaderMaterial({
      vertexShader: vert,
      fragmentShader: frag,
      uniforms: {
        uSat: { value: null },
        uSatBox: { value: new THREE.Vector4(...opts.satBox) },
        uView: { value: new THREE.Vector4(0, 0, 1, 1) },
        uOrigin: { value: new THREE.Vector2(...opts.origin) },
        uReveal: { value: 0 },
        uTime: { value: 0 },
        uNight: { value: new THREE.Color(opts.night) },
      },
    });
    this.scene.add(new THREE.Mesh(new THREE.PlaneGeometry(2, 2), this.material));
    this.ready = new Promise((resolve, reject) => {
      new THREE.TextureLoader().load(
        opts.image,
        (tex) => {
          tex.colorSpace = THREE.SRGBColorSpace;
          tex.minFilter = THREE.LinearMipmapLinearFilter;
          tex.anisotropy = this.renderer.capabilities.getMaxAnisotropy();
          tex.flipY = false;
          this.texture = tex;
          this.material.uniforms.uSat.value = tex;
          resolve();
        },
        undefined,
        reject,
      );
    });
  }

  setSize(w: number, h: number) {
    this.renderer.setSize(w, h, false);
  }

  set reveal(v: number) {
    this.material.uniforms.uReveal.value = v;
  }

  /** Before the image arrives this paints the night ground and its vignette (an empty sampler reads black = no data). */
  render(view: Box, time: number) {
    this.material.uniforms.uView.value.set(...view);
    this.material.uniforms.uTime.value = time;
    this.renderer.render(this.scene, this.camera);
  }

  dispose() {
    this.texture?.dispose();
    this.material.dispose();
    this.renderer.dispose();
  }
}
