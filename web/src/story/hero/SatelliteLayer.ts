import * as THREE from "three";
import type { Box } from "../data/geo";

// The satellite drawn into map space and revealed by a watercolour wash: domain-warped fbm thresholded
// against distance from the storm centre, with a darker "wet edge" at the front. The source is Meteosat
// infrared (grey levels: 0 = off the disk, brighter = colder cloud tops), either the 12:00Z still or the
// 24-hour loop, graded here into the story's night palette.

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
uniform float uFade;    // dips to 0 while the loop wraps around
uniform float uTime;
uniform vec3 uNight;    // display-space colours (no colour management in this pass)
uniform vec3 uSea;
uniform vec3 uCloud;

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
  float g = texture2D(uSat, suv).r;
  // Feather the frame edges; grey 0 is space beyond the disk (no data).
  float inside = smoothstep(0.0, 0.16, suv.x) * smoothstep(1.0, 0.88, suv.x) * smoothstep(0.0, 0.15, suv.y) * smoothstep(1.0, 0.86, suv.y);
  inside *= smoothstep(0.02, 0.05, g);

  // Grade: warm sea and land sink into the navy, cold cloud tops lift to a cool white.
  float c = pow(smoothstep(0.2, 0.93, g), 1.12);
  vec3 graded = mix(uSea, uCloud, c);
  graded += (uCloud - uSea) * 0.08 * smoothstep(0.85, 1.0, g);

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

  vec3 col = mix(uNight, graded, mask * inside * uFade);
  col *= 1.0 - wetEdge * 0.38;
  col += vec3(0.05, 0.07, 0.09) * wetEdge * (1.0 - n);

  // Vignette, and a legibility shade on the lower left where the headline sits.
  float vig = smoothstep(1.25, 0.35, length((vUv - vec2(0.5, 0.52)) * vec2(1.0, 1.25)));
  float shade = smoothstep(0.65, 0.0, vUv.x) * smoothstep(0.75, 0.0, vUv.y);
  col = mix(uNight, col, mix(0.62, 1.0, vig));
  col = mix(col, uNight, shade * 0.38);
  gl_FragColor = vec4(col, 1.0);
}`;

const rgb = (hex: string) => {
  const n = parseInt(hex.slice(1), 16);
  return new THREE.Vector3(((n >> 16) & 255) / 255, ((n >> 8) & 255) / 255, (n & 255) / 255);
};

/** A full-screen quad: one texture, one draw call, rendered only while the hero is on screen. */
export class SatelliteLayer {
  readonly ready: Promise<void>;
  private readonly renderer: THREE.WebGLRenderer;
  private readonly scene = new THREE.Scene();
  private readonly camera = new THREE.OrthographicCamera(-1, 1, 1, -1, 0, 1);
  private readonly material: THREE.ShaderMaterial;
  private still: THREE.Texture | null = null;
  private video: THREE.VideoTexture | null = null;
  private last = "";
  /** Counts the loop's decoded frames, so the layer redraws when the picture changes and not every tick. */
  private frames = 0;
  private w = 1;
  private h = 1;
  private ratio = 0;
  private everyTick = false;

  constructor(opts: { canvas: HTMLCanvasElement; image: string; satBox: Box; origin: [number, number]; night: string }) {
    this.renderer = new THREE.WebGLRenderer({ canvas: opts.canvas, antialias: false, alpha: false, powerPreference: "high-performance" });
    this.material = new THREE.ShaderMaterial({
      vertexShader: vert,
      fragmentShader: frag,
      uniforms: {
        uSat: { value: null },
        uSatBox: { value: new THREE.Vector4(...opts.satBox) },
        uView: { value: new THREE.Vector4(0, 0, 1, 1) },
        uOrigin: { value: new THREE.Vector2(...opts.origin) },
        uReveal: { value: 0 },
        uFade: { value: 1 },
        uTime: { value: 0 },
        uNight: { value: rgb(opts.night) },
        uSea: { value: rgb("#101a2a") },
        uCloud: { value: rgb("#eef2f7") },
      },
    });
    this.scene.add(new THREE.Mesh(new THREE.PlaneGeometry(2, 2), this.material));
    this.ready = new Promise((resolve, reject) => {
      new THREE.TextureLoader().load(
        opts.image,
        (tex) => {
          tex.colorSpace = THREE.NoColorSpace;
          tex.minFilter = THREE.LinearMipmapLinearFilter;
          tex.anisotropy = this.renderer.capabilities.getMaxAnisotropy();
          tex.flipY = false;
          this.still = tex;
          if (!this.video) this.material.uniforms.uSat.value = tex;
          this.last = "";
          resolve();
        },
        undefined,
        reject,
      );
    });
  }

  /** Swap the still for the loop once it has frames (the still is the loop's 12:00Z frame, so nothing jumps). */
  useVideo(el: HTMLVideoElement) {
    if (this.video) return;
    const tex = new THREE.VideoTexture(el);
    tex.colorSpace = THREE.NoColorSpace;
    tex.minFilter = THREE.LinearFilter;
    tex.magFilter = THREE.LinearFilter;
    tex.generateMipmaps = false;
    tex.flipY = false;
    this.video = tex;
    this.material.uniforms.uSat.value = tex;
    // count decoded frames where the browser says when they land; elsewhere redraw every tick
    if (typeof el.requestVideoFrameCallback !== "function") {
      this.everyTick = true;
      return;
    }
    const count = () => {
      this.frames++;
      if (this.video) el.requestVideoFrameCallback(count);
    };
    el.requestVideoFrameCallback(count);
  }

  setSize(w: number, h: number) {
    this.w = w;
    this.h = h;
    this.ratio = 0;
    this.last = "";
  }

  /**
   * Full retina (up to 2×) once the picture is up; 1× while the wash is moving, when every pixel runs three
   * octave stacks of noise for an edge that is soft anyway (a quarter of the fragments at 2×).
   */
  private fit(washing: boolean) {
    const ratio = washing ? 1 : Math.min(window.devicePixelRatio || 1, 2);
    if (ratio === this.ratio) return;
    this.ratio = ratio;
    this.renderer.setPixelRatio(ratio);
    this.renderer.setSize(this.w, this.h, false);
    this.last = "";
  }

  set reveal(v: number) {
    this.material.uniforms.uReveal.value = v;
  }

  set fade(v: number) {
    this.material.uniforms.uFade.value = v;
  }

  /**
   * Draws only when something on it changed: the view, the wash (whose edge drifts while it runs), the loop's
   * frame or the fade. Before the image arrives this paints the night ground (an empty sampler reads 0 = no data).
   * Returns false while nothing is revealed: the canvas is then plain night and can stay hidden.
   */
  render(view: Box, time: number): boolean {
    const u = this.material.uniforms;
    const reveal = u.uReveal.value as number;
    if (reveal <= 0.0005) return false;
    const washing = reveal < 0.999;
    this.fit(washing);
    const key = `${view.map((n) => n.toFixed(4)).join(",")}|${washing || this.everyTick ? time : reveal}|${u.uFade.value}|${this.frames}|${u.uSat.value ? 1 : 0}`;
    if (key === this.last) return true;
    this.last = key;
    u.uView.value.set(...view);
    u.uTime.value = time;
    this.renderer.render(this.scene, this.camera);
    return true;
  }

  /** Forget the last frame (after a resize the drawing buffer is cleared). */
  invalidate() {
    this.last = "";
  }

  dispose() {
    this.still?.dispose();
    this.video?.dispose();
    this.material.dispose();
    this.renderer.dispose();
  }
}
