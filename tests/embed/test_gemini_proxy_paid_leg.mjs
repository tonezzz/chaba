// Tests for the paid-Gemini leg ordering in gemini-ollama-proxy
// (card gemini-proxy-paid-last-resort-leg). Spawns the real proxy with
// GEMINI_API_BASE + OLLAMA_FALLBACK_BASE pointed at local stubs: the free
// key 429s, the paid key serves, and Ollama only sees traffic after the
// paid cap refuses — proving paid sits between free and Ollama.
import assert from "node:assert/strict";
import { createServer } from "node:http";
import { spawn } from "node:child_process";
import test from "node:test";
import { fileURLToPath } from "node:url";
import path from "node:path";

const PROXY = path.join(
  path.dirname(fileURLToPath(import.meta.url)),
  "../../scripts/mddb/gemini-ollama-proxy.mjs"
);
const DIMS = 4;
const FREE_KEY = "test-free-key";
const PAID_KEY = "test-paid-key";

// Gemini stub: paid key -> 200 embeddings, everything else -> 429.
function startGeminiStub() {
  const calls = { free: 0, paid: 0 };
  const srv = createServer((req, res) => {
    let raw = "";
    req.on("data", (c) => (raw += c));
    req.on("end", () => {
      if (!req.url.includes("batchEmbedContents")) {
        res.writeHead(200, { "Content-Type": "application/json" });
        return res.end("{}");
      }
      const key = new URL(req.url, "http://x").searchParams.get("key") || "";
      if (key === PAID_KEY) {
        calls.paid += 1;
        const n = (JSON.parse(raw).requests || []).length || 1;
        res.writeHead(200, { "Content-Type": "application/json" });
        return res.end(JSON.stringify({
          embeddings: Array.from({ length: n }, () => ({
            values: Array.from({ length: DIMS }, () => 0.5),
          })),
        }));
      }
      calls.free += 1;
      res.writeHead(429, { "Content-Type": "application/json", "Retry-After": "1" });
      res.end(JSON.stringify({ error: { message: "quota exceeded (stub)" } }));
    });
  });
  return new Promise((resolve) =>
    srv.listen(0, "127.0.0.1", () =>
      resolve({ srv, calls, port: srv.address().port })));
}

function startOllamaStub() {
  const calls = { count: 0 };
  const srv = createServer((req, res) => {
    let raw = "";
    req.on("data", (c) => (raw += c));
    req.on("end", () => {
      calls.count += 1;
      const n = (JSON.parse(raw).input || []).length || 1;
      res.writeHead(200, { "Content-Type": "application/json" });
      res.end(JSON.stringify({
        embeddings: Array.from({ length: n }, () =>
          Array.from({ length: DIMS }, () => 0.9)),
      }));
    });
  });
  return new Promise((resolve) =>
    srv.listen(0, "127.0.0.1", () =>
      resolve({ srv, calls, port: srv.address().port })));
}

function startProxy(env) {
  return new Promise((resolve, reject) => {
    const child = spawn("node", [PROXY], {
      env: {
        ...process.env,
        GEMINI_PROXY_PORT: String(env.port),
        GEMINI_PROXY_HOST: "127.0.0.1",
        GEMINI_API_KEY: FREE_KEY,
        GEMINI_API_KEY_PAID: PAID_KEY,
        GEMINI_API_BASE: `http://127.0.0.1:${env.gemini.port}`,
        OLLAMA_FALLBACK_BASE: `http://127.0.0.1:${env.ollama.port}`,
        GEMINI_EMBEDDING_DIMENSIONS: String(DIMS),
        GEMINI_PROXY_MAX_RETRIES: "2",
        FREE_GEMINI_CIRCUIT_MS: "60000",
        OLLAMA_CIRCUIT_COOLDOWN_MS: "60000",
        OR_CIRCUIT_COOLDOWN_MS: "60000",
        MDDB_OPS_URL: `http://127.0.0.1:${env.gemini.port}`,
        OPENROUTER_API_KEY: "",
        EMBED_GATEWAY_BASE: "",
        EMBED_GATEWAY_KEY: "",
        LITELLM_KEY: "",
        ...env.extra,
      },
      stdio: ["ignore", "pipe", "pipe"],
    });
    child.stderr.on("data", (d) => process.stderr.write(d));
    const deadline = Date.now() + 8000;
    const poll = async () => {
      try {
        const r = await fetch(`http://127.0.0.1:${env.port}/health`);
        if (r.ok) return resolve({ child, port: env.port });
      } catch { /* not up yet */ }
      if (Date.now() > deadline) return reject(new Error("proxy did not start"));
      setTimeout(poll, 100);
    };
    poll();
  });
}

async function embed(port, input) {
  const r = await fetch(`http://127.0.0.1:${port}/api/embed`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ model: "gemini-embedding-2", input }),
  });
  return { status: r.status, body: await r.json() };
}

test("free 429 -> paid leg serves before Ollama", async (t) => {
  const gemini = await startGeminiStub();
  const ollama = await startOllamaStub();
  const proxy = await startProxy({
    port: 12521, gemini, ollama, extra: {},
  });
  t.after(() => { proxy.child.kill(); gemini.srv.close(); ollama.srv.close(); });

  const r = await embed(proxy.port, "paid leg probe");
  assert.equal(r.status, 200);
  assert.equal(r.body.provider, "gemini-embedding-2-paid");
  assert.equal(r.body.fallback, "gemini-embedding-2-paid");
  assert.equal(ollama.calls.count, 0); // Ollama never saw the request
  assert.ok(gemini.calls.free > 0);    // free key was tried first
  assert.equal(gemini.calls.paid, 1);
});

test("paid daily cap -> Ollama is the literal last resort", async (t) => {
  const gemini = await startGeminiStub();
  const ollama = await startOllamaStub();
  const proxy = await startProxy({
    port: 12522, gemini, ollama,
    extra: { PAID_GEMINI_DAILY_CAP: "1", PAID_GEMINI_HOURLY_CAP: "1" },
  });
  t.after(() => { proxy.child.kill(); gemini.srv.close(); ollama.srv.close(); });

  let r = await embed(proxy.port, "first — paid");
  assert.equal(r.status, 200);
  assert.equal(r.body.provider, "gemini-embedding-2-paid");
  assert.equal(ollama.calls.count, 0);

  // Second request: free circuits open, paid cap spent -> Ollama serves.
  r = await embed(proxy.port, "second — capped out");
  assert.equal(r.status, 200);
  assert.equal(r.body.provider, "nomic-embed-text");
  assert.equal(ollama.calls.count, 1);
  assert.equal(gemini.calls.paid, 1); // no second billed call
});
