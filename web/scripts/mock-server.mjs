// The in-browser mock world (src/mocks, typed from CONTRACTS.md) served over HTTP on /api, for tools that
// need a real server before the stub or the engine exists: the recorder, curl, http-mode e2e.
//   node --import tsx scripts/mock-server.mjs [--port 8002]
import { createServer } from "node:http";

const arg = (name, fallback) => {
  const i = process.argv.indexOf(`--${name}`);
  return i > 0 ? process.argv[i + 1] : fallback;
};
const port = Number(arg("port", "8002"));
const { createMockFetch, createMockStream } = await import("../src/mocks/index.ts");
const mockFetch = createMockFetch();

createServer(async (req, res) => {
  const url = new URL(req.url ?? "/", `http://localhost:${port}`);
  if (!url.pathname.startsWith("/api")) {
    res.writeHead(404).end();
    return;
  }
  const path = url.pathname.slice(4) + url.search;
  if (path.startsWith("/stream")) {
    res.writeHead(200, { "Content-Type": "text/event-stream", "Cache-Control": "no-cache", Connection: "keep-alive" });
    const last = Number(req.headers["last-event-id"] ?? 0);
    const stop = createMockStream((e) => res.write(`event: trace\nid: ${e.seq}\ndata: ${JSON.stringify(e)}\n\n`), last);
    const beat = setInterval(() => res.write(": heartbeat\n\n"), 15_000);
    req.on("close", () => (stop(), clearInterval(beat)));
    return;
  }
  const chunks = [];
  for await (const c of req) chunks.push(c);
  const body = chunks.length ? Buffer.concat(chunks).toString() : undefined;
  // Same header shape the browser client sends (plain object, "Authorization").
  const headers = { Accept: "application/json", ...(req.headers.authorization ? { Authorization: req.headers.authorization } : {}), ...(body ? { "Content-Type": "application/json" } : {}) };
  const r = await mockFetch(path, { method: req.method, headers, body });
  res.writeHead(r.status, { "Content-Type": "application/json" });
  res.end(await r.text());
}).listen(port, () => console.log(`mock world on http://localhost:${port}/api`));
