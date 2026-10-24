// Headless screenshots of any page at several sizes and scroll depths, plus every console error.
// Uses the Chrome you already have over the DevTools protocol: no Puppeteer, no browser download.
//
//   node scripts/shoot.mjs                                   # landing, desktop + phone, 8 depths
//   node scripts/shoot.mjs --url http://localhost:5173/questions --at 0
//   node scripts/shoot.mjs --sizes 1440x900,390x844,375x667 --at 0,0.3,0.6 --out shots
//   --hold 5000 (after the load event, before the first shot) · --settle 2200 (after each scroll)
//   --dpr 2 (retina) · --format jpeg (smaller frames; use it with --dpr 2 on WebGL pages)
//
// Needs Node 22+ (global WebSocket). CHROME=/path/to/chrome overrides the macOS default.
// Exits 1 if the page threw, so it can gate a change.
import { spawn } from "node:child_process";
import { mkdirSync, mkdtempSync, rmSync, writeFileSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";

const arg = (name, fallback) => {
  const i = process.argv.indexOf(`--${name}`);
  return i > 0 ? process.argv[i + 1] : fallback;
};
const url = arg("url", "http://localhost:5173/");
const sizes = arg("sizes", "1440x900,390x844").split(",").map((s) => s.split("x").map(Number));
const depths = arg("at", "0,0.14,0.28,0.42,0.56,0.7,0.84,1").split(",").map(Number);
const out = arg("out", "shots");
const settle = Number(arg("settle", "2200"));
const hold = Number(arg("hold", "5000"));
const dpr = Number(arg("dpr", "1"));
// PNG by default; --format jpeg (quality 88) keeps a DPR 2 WebGL frame small enough for the DevTools socket.
const format = arg("format", "png") === "jpeg" ? "jpeg" : "png";
const chrome = process.env.CHROME ?? "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome";
if (typeof WebSocket === "undefined") throw new Error("Node 22+ is needed (global WebSocket).");

const port = 9400 + Math.floor(Math.random() * 400);
const profile = mkdtempSync(join(tmpdir(), "shoot-"));
const browser = spawn(chrome, [`--remote-debugging-port=${port}`, `--user-data-dir=${profile}`, "--headless=new", "--hide-scrollbars", "--mute-audio", "--no-first-run", "--enable-unsafe-swiftshader", "--use-angle=swiftshader", "about:blank"], { stdio: "ignore" });
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
const problems = [];
let threw = false;
let onLoad = () => {};
ws.onmessage = ({ data }) => {
  const msg = JSON.parse(data);
  if (msg.id) return pending.get(msg.id)?.(msg.result ?? msg.error);
  if (msg.method === "Page.loadEventFired") onLoad();
  if (msg.method === "Runtime.exceptionThrown") {
    threw = true;
    problems.push(`exception: ${msg.params.exceptionDetails.exception?.description ?? msg.params.exceptionDetails.text}`);
  }
  if (msg.method === "Runtime.consoleAPICalled" && msg.params.type === "error") problems.push(`console.error: ${msg.params.args.map((a) => a.value ?? a.description).join(" ")}`);
};
const send = (method, params = {}) => new Promise((r) => pending.set(++id, r) && ws.send(JSON.stringify({ id, method, params })));
const evaluate = async (expression) => (await send("Runtime.evaluate", { expression, awaitPromise: true, returnByValue: true }))?.result?.value;

await send("Runtime.enable");
await send("Page.enable");
// A tab opened over DevTools starts in the background, where Chrome pauses requestAnimationFrame: animations
// would freeze half-played and the shots would lie. Foreground it and keep it focused.
await send("Page.bringToFront");
await send("Emulation.setFocusEmulationEnabled", { enabled: true });
mkdirSync(out, { recursive: true });
const slug = new URL(url).pathname.replace(/\W+/g, "-").replace(/^-|-$/g, "") || "home";

for (const [w, h] of sizes) {
  await send("Emulation.setDeviceMetricsOverride", { width: w, height: h, deviceScaleFactor: dpr, mobile: w < 768 });
  // A cold dev server (fresh profile, files just edited) can take well over 6 s to load every module, so wait
  // for the load event, then hold long enough for the opening animations (Storm Run's settles at ~4.2 s).
  const loaded = new Promise((r) => (onLoad = r));
  await send("Page.navigate", { url });
  await Promise.race([loaded, wait(30000)]);
  await wait(hold);
  for (const at of depths) {
    // Native scroll: Lenis and ScrollTrigger follow it, scrubbed timelines catch up during the settle.
    await evaluate(`window.scrollTo(0, (document.documentElement.scrollHeight - innerHeight) * ${at})`);
    await wait(settle);
    const shot = await send("Page.captureScreenshot", format === "jpeg" ? { format, quality: 88 } : { format });
    const file = join(out, `${slug}-${w}x${h}${dpr !== 1 ? `@${dpr}x` : ""}-${String(Math.round(at * 100)).padStart(3, "0")}.${format === "jpeg" ? "jpg" : "png"}`);
    writeFileSync(file, Buffer.from(shot.data, "base64"));
    console.log(file);
  }
}

console.log(problems.length ? `\n${problems.length} problem(s):\n${[...new Set(problems)].join("\n")}` : "\nNo console errors.");
ws.close();
browser.kill();
await Promise.race([new Promise((r) => browser.once("exit", r)), wait(3000)]); // Chrome flushes its profile on the way out
try {
  rmSync(profile, { recursive: true, force: true, maxRetries: 5, retryDelay: 200 });
} catch {
  // a leftover temp profile is harmless
}
process.exit(threw ? 1 : 0);
