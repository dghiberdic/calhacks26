import { fileURLToPath, URL } from "node:url";
import react from "@vitejs/plugin-react";
import tailwindcss from "@tailwindcss/vite";
import { defineConfig, loadEnv } from "vite";

// /api goes to the contract stub (`make stub`, :8001) until the real server lands (`make dev`, :8000):
// API_TARGET=http://localhost:8000 pnpm dev
export default defineConfig(({ mode }) => {
  const env = loadEnv(mode, process.cwd(), "");
  const target = env.API_TARGET || "http://localhost:8001";
  return {
    plugins: [react(), tailwindcss()],
    resolve: { alias: { "@": fileURLToPath(new URL("./src", import.meta.url)) } },
    server: { port: Number(env.PORT) || 5173, proxy: { "/api": { target, changeOrigin: true } } },
    preview: { port: 4173 },
    build: { outDir: "dist", chunkSizeWarningLimit: 1200 },
  };
});
