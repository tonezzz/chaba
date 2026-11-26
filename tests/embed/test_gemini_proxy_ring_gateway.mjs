// Tests for the free-key ring + LiteLLM gateway leg merged into
// gemini-ollama-proxy (card gemini-proxy-live-repo-divergence — the live
// idc03 variant's uncommitted work landed on top of the repo budgets).
// Spawns the real proxy with GEMINI_API_BASE / EMBED_GATEWAY_BASE pointed
// at local stubs.
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

// Stub serves batchEmbedContents (429 for keys containing "bad"), the
// gateway /v1/embeddings shape, and swallows ops-event posts.
function startStub() {
  const calls = { geminiKeys: [], gateway: 0 };
  const srv = createServer((req, res) => {
    let raw = "";
    req.on("data", (c) => (raw += c));
    req.on("end", () => {
      const url = new URL(req.url, "http://x");
      if (url.pathname.includes("batchEmbedContents")) {
        const key = url.searchParams.get("key") || "";
        calls.geminiKeys.push(key);
        if (key.includes("bad")) {
          res.writeHead(429, { "Content-Type": "application/json", "retry-after": "0" });
          return res.end(JSON.stringify({ error: { message: "quota" } }));
        }
        const n = (JSON.parse(raw).requests || []).length || 1;
        res.writeHead(200, { "Content-Type": "application/json" });
        return res.end(JSON.stringify({
          embeddings: Array.from({ length: n }, () => ({
            values: Array.from({ length: DIMS }, () => 0.5),
          })),
        }));
      }
      if (url.pathname === "/v1/embeddings") {
        calls.gateway += 1;
        const body = JSON.parse(raw);
        const n = Array.isArray(body.input) ? body.input.length : 1;
        res.writeHead(200, { "Content-Type": "application/json" });
        return res.end(JSON.stringify({
          data: Array.from({ length: n }, () => ({ embedding: [0.1, 0.2, 0.3, 0.4] })),
        }));
      }
      res.writeHead(200, { "Content-Type": "application/json" });
      res.end("{}");
    });
  });
  return new Promise((resolve) =>
    srv.listen(0, "127.0.0.1", () =>
      resolve({ srv, calls, port: srv.address().port })));
}

function startProxy(port, stub, extra = {}) {
  return new Promise((resolve, reject) => {
    const child = spawn("node", [PROXY], {
      env: {
        ...process.env,
        GEMINI_PROXY_PORT: String(port),
        GEMINI_PROXY_HOST: "127.0.0.1",
        GEMINI_API_KEY: "test-free-key",
        GEMINI_API_BASE: `http://127.0.0.1:${stub.port}`,
        GEMINI_EMBEDDING_DIMENSIONS: String(DIMS),
        MDDB_OPS_URL: `http://127.0.0.1:${stub.port}`,
        FREE_GEMINI_CIRCUIT_MS: "60000",
        GEMINI_PROXY_MAX_RETRIES: "1",
        OPENROUTER_PRIMARY: "0",
        ...extra,
      },
      stdio: ["ignore", "pipe", "pipe"],
    });
    child.stderr.on("data", (d) => process.stderr.write(d));
    const deadline = Date.now() + 8000;
    const poll = async () => {
      try {
        const r = await fetch(`http://127.0.0.1:${port}/health`);
        if (r.ok) return resolve({ child, port });
      } catch { /* not up yet */ }
      if (Date.now() > deadline) return reject(new Error("proxy did not start"));
      setTimeout(poll, 100);
    };
    poll();
  });
}

async function embed(port, body, headers = {}) {
  const r = await fetch(`http://127.0.0.1:${port}/api/embed`, {
    method: "POST",
    headers: { "Content-Type": "application/json", ...headers },
    body: JSON.stringify(body),
  });
  return { status: r.status, body: await r.json() };
}

async function health(port) {
  return (await fetch(`http://127.0.0.1:${port}/health`)).json();
}

test("free-key ring fails over to next key on per-key circuit", async (t) => {
  const stub = await startStub();
  const proxy = await startProxy(12521, stub, {
    GEMINI_API_KEY: "KEY-bad-primary",
    GEMINI_FREE_KEYS_01: "KEY-good-ring",
  });
  t.after(() => { proxy.child.kill(); stub.srv.close(); });

  const r = await embed(proxy.port, { model: "gemini-embedding-2", input: "hi" });
  assert.equal(r.status, 200);
  assert.equal(r.body.provider, "gemini-embedding-2");
  // Both keys were tried in order: bad primary 429'd, ring key served.
  assert.equal(stub.calls.geminiKeys.length, 2);
  assert.ok(stub.calls.geminiKeys[0].includes("bad"));
  assert.ok(stub.calls.geminiKeys[1].includes("good"));
  const h = await health(proxy.port);
  assert.equal(h.circuit.free_keys, 2);
  assert.equal(h.circuit.free_gemini_open, false);
});

test("embed gateway leg serves backup chain when free keys are dead", async (t) => {
  const stub = await startStub();
  const proxy = await startProxy(12522, stub, {
    GEMINI_API_KEY: "KEY-bad-only",
    EMBED_GATEWAY_BASE: `http://127.0.0.1:${stub.port}`,
    EMBED_GATEWAY_KEY: "sk-test",
    EMBED_GATEWAY_MODEL: "embedding",
    LITELLM_KEY: "",
  });
  t.after(() => { proxy.child.kill(); stub.srv.close(); });

  const r = await embed(proxy.port, { model: "gemini-embedding-2", input: "hi" });
  assert.equal(r.status, 200);
  assert.equal(r.body.provider, "litellm:embedding");
  assert.equal(stub.calls.gateway, 1);
  const h = await health(proxy.port);
  assert.equal(h.embed_gateway, "embedding");
  assert.equal(h.provider_mode, "gemini-primary"); // gateway never promotes to primary
});
