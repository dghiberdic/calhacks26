import { cpSync, existsSync, readFileSync, statSync } from "node:fs";
import { extname, join, normalize } from "node:path";
import { fileURLToPath, URL } from "node:url";
import react from "@vitejs/plugin-react";
import tailwindcss from "@tailwindcss/vite";
import { defineConfig, loadEnv, type Plugin } from "vite";

const RECORDED = fileURLToPath(new URL("../demo/recorded", import.meta.url));

/** Absolute URLs for link previews (og:image needs one): SITE_URL, else Vercel's production host, else localhost. */
function siteUrl(): Plugin {
  const url = (process.env.SITE_URL ?? (process.env.VERCEL_PROJECT_PRODUCTION_URL ? `https://${process.env.VERCEL_PROJECT_PRODUCTION_URL}` : "http://localhost:5173")).replace(/\/$/, "");
  return { name: "site-url", transformIndexHtml: (html) => html.replaceAll("%SITE_URL%", url) };
}

/** demo/recorded/ is served at /recorded/ in dev and copied into dist/ for the recorded build (J9). */
function recordedDemo(mode: string): Plugin {
  return {
    name: "stormcheck-recorded-demo",
    configureServer(server) {
      server.middlewares.use("/recorded", (req, res, next) => {
        const file = normalize(join(RECORDED, decodeURIComponent((req.url ?? "/").split("?")[0])));
        if (!file.startsWith(RECORDED) || !existsSync(file) || !statSync(file).isFile()) return next();
        res.setHeader("Content-Type", extname(file) === ".json" ? "application/json" : "application/octet-stream");
        res.end(readFileSync(file));
      });
    },
    closeBundle() {
      if (mode === "recorded" && existsSync(RECORDED)) cpSync(RECORDED, fileURLToPath(new URL("./dist/recorded", import.meta.url)), { recursive: true });
    },
  };
}

// /api goes to the contract stub (`make stub`, :8001) until the real server lands (`make dev`, :8000):
// API_TARGET=http://localhost:8000 pnpm dev
export default defineConfig(({ mode }) => {
  const env = loadEnv(mode, process.cwd(), "");
  const target = env.API_TARGET || "http://localhost:8001";
  return {
    plugins: [react(), tailwindcss(), recordedDemo(mode), siteUrl()],
    resolve: { alias: { "@": fileURLToPath(new URL("./src", import.meta.url)) } },
    server: { port: Number(env.PORT) || 5173, proxy: { "/api": { target, changeOrigin: true } } },
    preview: { port: 4173 },
    // Crawl every screen for dependencies at startup: otherwise the first visit to a lazy route (three.js on
    // /story, recharts on /close) discovers new deps and reloads the page mid-test.
    optimizeDeps: { entries: ["index.html", "src/**/*.tsx"] },
    build: { outDir: "dist", chunkSizeWarningLimit: 1200 },
  };
});
