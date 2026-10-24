// The Vercel build (web/vercel.json): the recorded demo once demo/recorded/ has been recorded (J9), the mock
// world until then, so the preview can be deployed at any point. The sidebar says which one a build carries.
import { spawnSync } from "node:child_process";
import { existsSync } from "node:fs";

const recorded = existsSync(new URL("../../demo/recorded/manifest.json", import.meta.url));
console.log(recorded ? "build: demo/recorded/ found → recorded demo" : "build: no demo/recorded/ yet → mock world");
const run = (cmd, args) => spawnSync(cmd, args, { stdio: "inherit" }).status ?? 1;
process.exit(run("pnpm", ["exec", "tsc", "-b"]) || run("pnpm", ["exec", "vite", "build", "--mode", recorded ? "recorded" : "mock"]));
