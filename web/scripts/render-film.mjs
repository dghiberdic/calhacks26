// Renders /moment to an MP4, frame by frame: no screen recorder, no dropped frames.
// Steps the film's GSAP timeline in headless Chrome, screenshots each frame, then encodes with
// Blender's built-in FFmpeg (or ffmpeg if it's on PATH).
//
//   npm run dev                      # the film's timeline is only exposed in development
//   npm run film                     # → moment.mp4, 1920×1080, 30 fps
//   npm run film -- --fps 60 --out ~/Desktop/stormcheck-moment.mp4
//   npm run film -- --until 2        # just the first two seconds, to check a change quickly
//
// Needs Node 22+ and Chrome. BLENDER=/path/to/Blender or CHROME=/path/to/chrome override the defaults.
import { spawn, spawnSync } from "node:child_process";
import { existsSync, mkdirSync, mkdtempSync, readdirSync, rmSync, writeFileSync } from "node:fs";
import { homedir, tmpdir } from "node:os";
import { join, resolve } from "node:path";

const arg = (name, fallback) => {
  const i = process.argv.indexOf(`--${name}`);
  return i > 0 ? process.argv[i + 1] : fallback;
};
const url = arg("url", "http://localhost:3000/moment");
const fps = Number(arg("fps", "30"));
const out = resolve(arg("out", "moment.mp4"));
const until = Number(arg("until", "Infinity"));
const chrome = process.env.CHROME ?? "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome";
const blender = [process.env.BLENDER, join(homedir(), "Applications/Blender.app/Contents/MacOS/Blender"), "/Applications/Blender.app/Contents/MacOS/Blender"].find((p) => p && existsSync(p));
if (typeof WebSocket === "undefined") throw new Error("Node 22+ is needed (global WebSocket).");

const work = mkdtempSync(join(tmpdir(), "film-"));
const frames = join(work, "frames");
mkdirSync(frames);
const port = 9400 + Math.floor(Math.random() * 400);
const browser = spawn(chrome, [`--remote-debugging-port=${port}`, `--user-data-dir=${join(work, "profile")}`, "--headless=new", "--hide-scrollbars", "--mute-audio", "--no-first-run", "--enable-unsafe-swiftshader", "--use-angle=swiftshader", "about:blank"], { stdio: "ignore" });
const wait = (ms) => new Promise((r) => setTimeout(r, ms));

let target;
for (let i = 0; i < 40 && !target; i++) {
  await wait(250);
  target = await fetch(`http://127.0.0.1:${port}/json/new?about:blank`, { method: "PUT" }).then((r) => r.json()).catch(() => null);
}
if (!target) throw new Error(`Chrome didn't start (${chrome}).`);
const ws = new WebSocket(target.webSocketDebuggerUrl);
await new Promise((r) => (ws.onopen = r));
let id = 0;
const pending = new Map();
ws.onmessage = ({ data }) => {
  const msg = JSON.parse(data);
  if (msg.id) pending.get(msg.id)?.(msg.result ?? msg.error);
};
const send = (method, params = {}) => new Promise((r) => pending.set(++id, r) && ws.send(JSON.stringify({ id, method, params })));
const evaluate = async (expression) => (await send("Runtime.evaluate", { expression, awaitPromise: true, returnByValue: true }))?.result?.value;

await send("Page.enable");
await send("Emulation.setDeviceMetricsOverride", { width: 1920, height: 1080, deviceScaleFactor: 1, mobile: false });
await send("Page.navigate", { url });
await wait(9000); // fonts, the satellite frame
const duration = await evaluate(`(() => { document.querySelector("nextjs-portal")?.remove(); if (!window.__film) return 0; window.__film.pause(); return window.__film.duration(); })()`);
if (!duration) throw new Error(`No film timeline at ${url}. Is \`npm run dev\` running? (window.__film is dev-only.)`);

const total = Math.round(Math.min(duration, until) * fps);
const started = Date.now();
for (let i = 0; i < total; i++) {
  // seek(t, false) fires onUpdate, so the counters paint; two frames let the WebGL layer catch up
  await evaluate(`(async () => { window.__film.seek(${(i / fps).toFixed(5)}, false); await new Promise((r) => requestAnimationFrame(() => requestAnimationFrame(r))); })()`);
  const shot = await send("Page.captureScreenshot", { format: "jpeg", quality: 94 });
  writeFileSync(join(frames, `f_${String(i).padStart(5, "0")}.jpg`), Buffer.from(shot.data, "base64"));
  if (i % fps === 0) process.stdout.write(`\r${i}/${total} frames · ${Math.round((Date.now() - started) / 1000)}s`);
}
console.log(`\r${total}/${total} frames captured.`);
ws.close();
browser.kill();

if (blender) {
  const py = join(work, "encode.py");
  writeFileSync(
    py,
    `import bpy, os
d, out, fps = ${JSON.stringify(frames)}, ${JSON.stringify(out)}, ${fps}
files = sorted(f for f in os.listdir(d) if f.endswith(".jpg"))
sc = bpy.context.scene
strip = sc.sequence_editor_create().strips.new_image(name="film", filepath=os.path.join(d, files[0]), channel=1, frame_start=1)
for f in files[1:]:
    strip.elements.append(f)
sc.frame_start, sc.frame_end = 1, len(files)
sc.render.fps, sc.render.fps_base = fps, 1
sc.render.resolution_x, sc.render.resolution_y, sc.render.resolution_percentage = 1920, 1080, 100
sc.view_settings.view_transform = "Standard"
s = sc.render.image_settings
s.media_type, s.file_format = "VIDEO", "FFMPEG"
ff = sc.render.ffmpeg
ff.format, ff.codec, ff.constant_rate_factor, ff.ffmpeg_preset, ff.gopsize, ff.audio_codec = "MPEG4", "H264", "PERC_LOSSLESS", "GOOD", fps, "NONE"
sc.render.filepath = out
bpy.ops.render.render(animation=True)
`,
  );
  spawnSync(blender, ["-b", "--python", py], { stdio: "ignore" });
} else if (spawnSync("ffmpeg", ["-version"]).status === 0) {
  spawnSync("ffmpeg", ["-y", "-framerate", String(fps), "-i", join(frames, "f_%05d.jpg"), "-c:v", "libx264", "-crf", "16", "-pix_fmt", "yuv420p", out], { stdio: "ignore" });
} else {
  console.log(`No Blender or ffmpeg found; frames are in ${frames}`);
  process.exit(0);
}
if (!existsSync(out)) throw new Error(`Encoding failed; frames are in ${frames}`);
console.log(`${out} (${readdirSync(frames).length} frames, ${fps} fps)`);
rmSync(work, { recursive: true, force: true, maxRetries: 5, retryDelay: 200 });
process.exit(0);
