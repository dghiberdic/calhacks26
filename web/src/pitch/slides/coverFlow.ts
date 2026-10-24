/**
 * The cover's storm, turning. One full-screen triangle samples the satellite frame twice along a slow
 * counter-clockwise flow around Éowyn's centre (a two-phase flow map: each sample drifts for one cycle and
 * hands over to the other, so the motion never piles up and loops for as long as the cover is up).
 * Only cloud moves: a mask from a heavily blurred mip of the same image keeps land and sea still.
 *
 * Start-up never blocks a frame: the shaders compile in parallel (KHR_parallel_shader_compile, polled each
 * frame), the image decodes off the main thread, and the 4K texture goes up in strips, one per frame.
 * WebGL2 only; anything less, a lost context or a machine that can't hold the frame rate leaves the plain
 * image on screen.
 */

const VERT = `#version 300 es
in vec2 aPos;
out vec2 vUv;
void main() {
  vUv = vec2(aPos.x * 0.5 + 0.5, 0.5 - aPos.y * 0.5);
  gl_Position = vec4(aPos, 0.0, 1.0);
}`;

const FRAG = `#version 300 es
precision highp float;
in vec2 vUv;
out vec4 outColor;
uniform sampler2D uSat;
uniform float uPhase;   // flow time, in cycles
uniform vec2 uCenter;   // storm centre (uv)
uniform float uAspect;  // image width / height
uniform float uR0;      // radius of the fastest flow, in image heights
uniform float uSpin;    // displacement per cycle at uR0, in image heights
uniform vec2 uDrift;    // the whole system's drift per cycle, in image heights (x east, y south)
uniform float uMix;     // 0 = the still image, 1 = full flow

vec2 flowAt(vec2 uv) {
  vec2 p = (uv - uCenter) * vec2(uAspect, 1.0);
  float r = length(p);
  float k = r / uR0;
  float speed = 2.0 * k / (1.0 + k * k);                         // 0 in the eye, 1 at uR0, falling off beyond
  vec2 tangent = r > 1e-5 ? vec2(p.y, -p.x) / r : vec2(0.0);     // counter-clockwise, north up
  float reach = 1.0 - smoothstep(uR0 * 2.2, uR0 * 4.5, r);
  vec2 v = tangent * speed * uSpin * reach + uDrift;
  return v / vec2(uAspect, 1.0);
}

void main() {
  vec3 low = textureLod(uSat, vUv, 6.0).rgb;
  float lum = dot(low, vec3(0.299, 0.587, 0.114));
  float chroma = max(low.r, max(low.g, low.b)) - min(low.r, min(low.g, low.b));
  float cloud = smoothstep(0.34, 0.62, lum) * (1.0 - smoothstep(0.07, 0.18, chroma));
  vec2 f = flowAt(vUv) * cloud * uMix;
  float t0 = fract(uPhase);
  float t1 = fract(uPhase + 0.5);
  vec3 a = texture(uSat, vUv - f * (t0 - 0.5)).rgb;
  vec3 b = texture(uSat, vUv - f * (t1 - 0.5)).rgb;
  outColor = vec4(mix(a, b, abs(t0 - 0.5) * 2.0), 1.0);
}`;

export type FlowOptions = {
  /** Storm centre in the image, 0–1 from the top left. */
  center: [number, number];
  /** Radius of the fastest flow, as a fraction of the image height. */
  r0: number;
  /** Displacement per cycle at r0, as a fraction of the image height. */
  spin: number;
  /** Drift of all cloud per cycle, fractions of the image height (x east, y south). */
  drift: [number, number];
  /** Seconds per flow cycle. */
  cycle: number;
  /** Seconds the flow takes to ease in from the still image. */
  easeIn: number;
};

export type FlowHandlers = {
  /** The first frame with the flow is on the canvas: show it. */
  onStart: () => void;
  /** It stopped for good (lost context, too slow): hide the canvas, the still image is underneath. */
  onFail: () => void;
};

/** Rows of the texture uploaded per frame while starting (8 strips for a 2160-row frame). */
const STRIP_ROWS = 270;

/**
 * Starts the flow on `canvas` from the image at `src` (already in the HTTP cache: the deck preloads it).
 * Returns a stop function, or null when there's no WebGL2.
 */
export function startCoverFlow(canvas: HTMLCanvasElement, src: string, opts: FlowOptions, on: FlowHandlers): (() => void) | null {
  const context = canvas.getContext("webgl2", { alpha: false, antialias: false, depth: false, stencil: false, premultipliedAlpha: true, preserveDrawingBuffer: false, powerPreference: "high-performance" });
  if (!context) return null;
  const gl: WebGL2RenderingContext = context;
  const parallel = gl.getExtension("KHR_parallel_shader_compile") as { COMPLETION_STATUS_KHR: number } | null;

  // Compile and link without asking for the result: with the extension, the GPU process does it in the
  // background and each frame only polls; asking LINK_STATUS early would block the main thread on it.
  const program = gl.createProgram()!;
  for (const [type, source] of [
    [gl.VERTEX_SHADER, VERT],
    [gl.FRAGMENT_SHADER, FRAG],
  ] as const) {
    const s = gl.createShader(type)!;
    gl.shaderSource(s, source);
    gl.compileShader(s);
    gl.attachShader(program, s);
  }
  gl.linkProgram(program);

  let stopped = false;
  let raf = 0;
  let bitmap: ImageBitmap | null = null;
  // The image's size, kept once the bitmap is uploaded and closed.
  let size: { w: number; h: number } | null = null;
  let tex: WebGLTexture | null = null;
  let uploadedRows = 0;
  let buf: WebGLBuffer | null = null;
  let running = false;
  let started = 0;
  let uPhase: WebGLUniformLocation | null = null;
  let uMix: WebGLUniformLocation | null = null;
  let quality = 1;

  // Decoded off the main thread.
  fetch(src)
    .then((r) => r.blob())
    .then((blob) => createImageBitmap(blob))
    .then((b) => {
      if (stopped) b.close();
      else bitmap = b;
    })
    .catch(() => fail());

  const resize = () => {
    if (!size) return;
    const rect = canvas.getBoundingClientRect();
    const dpr = window.devicePixelRatio || 1;
    // As many pixels as the canvas covers on screen, never more than the image has.
    const w = Math.max(2, Math.min(size.w, Math.round(rect.width * dpr * quality)));
    const h = Math.max(2, Math.round((w * size.h) / size.w));
    if (canvas.width !== w || canvas.height !== h) {
      canvas.width = w;
      canvas.height = h;
    }
    gl.viewport(0, 0, canvas.width, canvas.height);
  };

  const linked = () => (parallel ? gl.getProgramParameter(program, parallel.COMPLETION_STATUS_KHR) === true : true);

  /** One step of start-up per frame; true once everything is in place. */
  const prepare = (): boolean => {
    if (!bitmap && !size) return false;
    if (bitmap && !tex) {
      tex = gl.createTexture();
      gl.bindTexture(gl.TEXTURE_2D, tex);
      const levels = Math.floor(Math.log2(Math.max(bitmap.width, bitmap.height))) + 1;
      gl.texStorage2D(gl.TEXTURE_2D, levels, gl.RGBA8, bitmap.width, bitmap.height);
      return false;
    }
    if (bitmap) {
      const rows = Math.min(STRIP_ROWS, bitmap.height - uploadedRows);
      gl.bindTexture(gl.TEXTURE_2D, tex);
      gl.pixelStorei(gl.UNPACK_SKIP_ROWS, uploadedRows);
      gl.texSubImage2D(gl.TEXTURE_2D, 0, 0, uploadedRows, bitmap.width, rows, gl.RGBA, gl.UNSIGNED_BYTE, bitmap);
      gl.pixelStorei(gl.UNPACK_SKIP_ROWS, 0);
      uploadedRows += rows;
      if (uploadedRows >= bitmap.height) {
        // All in: the texture has its own copy.
        size = { w: bitmap.width, h: bitmap.height };
        bitmap.close();
        bitmap = null;
      }
      return false;
    }
    if (!size) return false;
    if (!linked()) return false;
    if (!gl.getProgramParameter(program, gl.LINK_STATUS)) {
      fail();
      return false;
    }
    gl.useProgram(program);
    gl.generateMipmap(gl.TEXTURE_2D);
    gl.texParameteri(gl.TEXTURE_2D, gl.TEXTURE_MIN_FILTER, gl.LINEAR_MIPMAP_LINEAR);
    gl.texParameteri(gl.TEXTURE_2D, gl.TEXTURE_MAG_FILTER, gl.LINEAR);
    gl.texParameteri(gl.TEXTURE_2D, gl.TEXTURE_WRAP_S, gl.CLAMP_TO_EDGE);
    gl.texParameteri(gl.TEXTURE_2D, gl.TEXTURE_WRAP_T, gl.CLAMP_TO_EDGE);
    const aniso = gl.getExtension("EXT_texture_filter_anisotropic");
    if (aniso) gl.texParameterf(gl.TEXTURE_2D, aniso.TEXTURE_MAX_ANISOTROPY_EXT, Math.min(4, gl.getParameter(aniso.MAX_TEXTURE_MAX_ANISOTROPY_EXT)));

    // One triangle that covers the screen.
    buf = gl.createBuffer();
    gl.bindBuffer(gl.ARRAY_BUFFER, buf);
    gl.bufferData(gl.ARRAY_BUFFER, new Float32Array([-1, -1, 3, -1, -1, 3]), gl.STATIC_DRAW);
    const aPos = gl.getAttribLocation(program, "aPos");
    gl.enableVertexAttribArray(aPos);
    gl.vertexAttribPointer(aPos, 2, gl.FLOAT, false, 0, 0);

    const u = (name: string) => gl.getUniformLocation(program, name);
    uPhase = u("uPhase");
    uMix = u("uMix");
    gl.uniform1i(u("uSat"), 0);
    gl.uniform2f(u("uCenter"), opts.center[0], opts.center[1]);
    gl.uniform1f(u("uAspect"), size.w / size.h);
    gl.uniform1f(u("uR0"), opts.r0);
    gl.uniform1f(u("uSpin"), opts.spin);
    gl.uniform2f(u("uDrift"), opts.drift[0], opts.drift[1]);
    resize();
    window.addEventListener("resize", resize);
    return true;
  };

  // Frame-rate guard: a weak GPU (a 4K projector on an old laptop) gets half the pixels; if that still drops
  // frames, the flow stops and the still image stays.
  let last = 0;
  let deltas: number[] = [];
  const guard = (now: number) => {
    if (last) deltas.push(now - last);
    last = now;
    if (deltas.length < 90) return true;
    const median = [...deltas].sort((a, b) => a - b)[45];
    deltas = [];
    if (median <= 24) return true;
    if (quality === 1) {
      quality = 0.5;
      resize();
      return true;
    }
    return false;
  };

  const frame = (now: number) => {
    if (stopped) return;
    raf = requestAnimationFrame(frame);
    if (!running) {
      if (!prepare()) return;
      running = true;
      started = now;
    } else if (!guard(now)) {
      fail();
      return;
    }
    const t = (now - started) / 1000;
    gl.uniform1f(uPhase, t / opts.cycle + 0.5);
    const e = Math.min(1, t / opts.easeIn);
    gl.uniform1f(uMix, e * e * (3 - 2 * e));
    gl.drawArrays(gl.TRIANGLES, 0, 3);
    if (t === 0) on.onStart();
  };
  raf = requestAnimationFrame(frame);

  const onLost = (e: Event) => {
    e.preventDefault();
    fail();
  };
  canvas.addEventListener("webglcontextlost", onLost);

  /** Gives up: the last frame stays while the canvas fades out over the still image, then the GPU is freed. */
  function fail() {
    if (stopped) return;
    stopped = true;
    cancelAnimationFrame(raf);
    on.onFail();
    window.setTimeout(release, 1200);
  }

  /** The cover is leaving: stop and free everything now. */
  function stop() {
    stopped = true;
    cancelAnimationFrame(raf);
    release();
  }

  let released = false;
  function release() {
    if (released) return;
    released = true;
    window.removeEventListener("resize", resize);
    canvas.removeEventListener("webglcontextlost", onLost);
    bitmap?.close();
    bitmap = null;
    if (gl.isContextLost()) return;
    gl.deleteTexture(tex);
    gl.deleteBuffer(buf);
    gl.deleteProgram(program);
    // Hand the GPU memory back now rather than at the next garbage collection.
    gl.getExtension("WEBGL_lose_context")?.loseContext();
  }
  return stop;
}
