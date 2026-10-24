import * as THREE from "three";

// Satellite frame drawn into map space, revealed by a watercolour wash: domain-warped fbm
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
uniform sampler2D uSatB;
uniform float uMix;       // 0 → uSat, 1 → uSatB (frame crossfade)
uniform vec4 uSatBox;   // map-space x0, y0, x1, y1 of the image (y0 = north edge)
uniform vec4 uView;     // map-space x0, y0, x1, y1 of the viewport
uniform vec2 uOrigin;   // map-space point the wash bleeds out from
uniform float uReveal;  // 0 → drawing only, 1 → full satellite
uniform float uTime;
uniform float uDim;     // darkens the image under text
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
  vec2 tuv = vec2(suv.x, 1.0 - suv.y);
  vec3 sat = mix(texture2D(uSat, tuv).rgb, texture2D(uSatB, tuv).rgb, uMix);
  // Feather the frame edges and treat swath gaps / polar night (pure black) as no data.
  float inside = smoothstep(0.0, 0.035, suv.x) * smoothstep(1.0, 0.965, suv.x) * smoothstep(0.0, 0.06, suv.y) * smoothstep(1.0, 0.94, suv.y);
  inside *= smoothstep(0.015, 0.07, max(sat.r, max(sat.g, sat.b)));

  // Grade: lift the cloud tops, cool the ocean, keep land muted.
  float lum = dot(sat, vec3(0.299, 0.587, 0.114));
  vec3 graded = mix(vec3(lum), sat, 0.72);
  graded = pow(graded, vec3(1.12));
  graded = mix(graded, graded * vec3(0.86, 0.93, 1.06), 1.0 - smoothstep(0.15, 0.6, lum));
  graded *= 0.92;

  // Wash front: distance from the storm centre, roughened by warped fbm.
  vec2 q = m * 0.11;
  vec2 warp = vec2(fbm(q + uTime * 0.015), fbm(q + vec2(5.2, 1.3) - uTime * 0.012));
  float n = fbm(q * 1.7 + warp * 1.6);
  float d = length((m - uOrigin) * vec2(1.0, 1.15)) / 38.0;
  float field = d * 0.85 + n * 0.55;
  float front = uReveal * 1.55 - 0.05;
  float mask = 1.0 - smoothstep(front - 0.035, front + 0.01, field);
  float wetEdge = smoothstep(front - 0.11, front - 0.02, field) * mask;

  vec3 col = mix(uNight, graded, mask * inside);
  col *= 1.0 - wetEdge * 0.38;
  col += vec3(0.05, 0.07, 0.09) * wetEdge * (1.0 - n);

  // Vignette + legibility dim on the lower-left where the headline sits.
  float vig = smoothstep(1.25, 0.35, length((vUv - vec2(0.5, 0.52)) * vec2(1.0, 1.25)));
  float textShade = smoothstep(0.65, 0.0, vUv.x) * smoothstep(0.75, 0.0, vUv.y);
  col *= mix(0.62, 1.0, vig);
  col *= 1.0 - textShade * uDim;
  gl_FragColor = vec4(col, 1.0);
}`;

export type SatOptions = {
  canvas: HTMLCanvasElement;
  image: string;
  satBox: [number, number, number, number];
  origin: [number, number];
  night?: string;
};

export class SatelliteLayer {
  private renderer: THREE.WebGLRenderer;
  private scene = new THREE.Scene();
  private camera = new THREE.OrthographicCamera(-1, 1, 1, -1, 0, 1);
  private material: THREE.ShaderMaterial;
  private texture: THREE.Texture | null = null;
  ready: Promise<void>;
  setOrigin(x: number, y: number) {
    this.material.uniforms.uOrigin.value.set(x, y);
  }

  constructor(opts: SatOptions) {
    this.renderer = new THREE.WebGLRenderer({ canvas: opts.canvas, antialias: false, alpha: false, powerPreference: "high-performance" });
    this.renderer.setPixelRatio(Math.min(window.devicePixelRatio, 1.75));
    this.material = new THREE.ShaderMaterial({
      vertexShader: vert,
      fragmentShader: frag,
      uniforms: {
        uSat: { value: null },
        uSatB: { value: null },
        uMix: { value: 0 },
        uSatBox: { value: new THREE.Vector4(...opts.satBox) },
        uView: { value: new THREE.Vector4(0, 0, 1, 1) },
        uOrigin: { value: new THREE.Vector2(...opts.origin) },
        uReveal: { value: 0 },
        uTime: { value: 0 },
        uDim: { value: 0.35 },
        uNight: { value: new THREE.Color(opts.night ?? "#0b0e13") },
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
          this.texture = tex;
          this.material.uniforms.uSat.value = tex;
          this.material.uniforms.uSatB.value = tex;
          resolve();
        },
        undefined,
        reject,
      );
    });
  }

  private cache = new Map<string, THREE.Texture>();
  private loading = new Set<string>();

  /** Lazily upload a frame; returns it once ready (null until then). */
  frame(url: string): THREE.Texture | null {
    const hit = this.cache.get(url);
    if (hit) return hit;
    if (!this.loading.has(url)) {
      this.loading.add(url);
      new THREE.TextureLoader().load(url, (tex) => {
        tex.colorSpace = THREE.SRGBColorSpace;
        tex.minFilter = THREE.LinearFilter;
        tex.generateMipmaps = false;
        this.cache.set(url, tex);
        this.loading.delete(url);
      });
    }
    return null;
  }

  /** Crossfade between two frames (falls back to whatever is loaded). */
  setFrames(a: THREE.Texture | null, b: THREE.Texture | null, mix: number) {
    const u = this.material.uniforms;
    if (a) u.uSat.value = a;
    u.uSatB.value = b ?? a ?? u.uSat.value;
    u.uMix.value = b ? mix : 0;
  }

  setSize(w: number, h: number) {
    this.renderer.setSize(w, h, false);
  }

  set reveal(v: number) {
    this.material.uniforms.uReveal.value = v;
  }
  get reveal() {
    return this.material.uniforms.uReveal.value as number;
  }
  set dim(v: number) {
    this.material.uniforms.uDim.value = v;
  }

  render(view: [number, number, number, number], time: number) {
    this.material.uniforms.uView.value.set(...view);
    this.material.uniforms.uTime.value = time;
    this.renderer.render(this.scene, this.camera);
  }

  dispose() {
    this.cache.forEach((t) => t.dispose());
    this.texture?.dispose();
    this.material.dispose();
    this.renderer.dispose();
  }
}
