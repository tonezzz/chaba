// Tests for the free-lane pacing + bulk budget in gemini-ollama-proxy
// (card embed-free-lane-daily-budget). Spawns the real proxy with
// GEMINI_API_BASE pointed at a local stub — the free leg serves until a
// budget gate refuses, and with no backup legs configured a refused
// request surfaces as 502, which is what these tests assert on.
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

function startGeminiStub() {
  const calls = { count: 0 };
  const srv = createServer((req, res) => {
    let raw = "";
    req.on("data", (c) => (raw += c));
    req.on("end", () => {
      if (!req.url.includes("batchEmbedContents")) { // ops-event posts etc.
        res.writeHead(200, { "Content-Type": "application/json" });
        return res.end("{}");
      }
      calls.count += 1;
      const n = (JSON.parse(raw).requests || []).length || 1;
      res.writeHead(200, { "Content-Type": "application/json" });
      res.end(JSON.stringify({
        embeddings: Array.from({ length: n }, () => ({
          values: Array.from({ length: DIMS }, () => 0.5),
        })),
      }));
    });
  });
  return new Promise((resolve) =>
    srv.listen(0, "127.0.0.1", () =>
      resolve({ srv, calls, port: srv.address().port })));
}

function startProxy(env) {
  return new Promise((resolve, reject) => {
    const stub = env.stub;
    const child = spawn("node", [PROXY], {
      env: {
        ...process.env,
        GEMINI_PROXY_PORT: String(env.port),
        GEMINI_PROXY_HOST: "127.0.0.1",
        GEMINI_API_KEY: "test-free-key",
        GEMINI_API_BASE: `http://127.0.0.1:${stub.port}`,
        GEMINI_EMBEDDING_DIMENSIONS: String(DIMS),
        MDDB_OPS_URL: `http://127.0.0.1:${stub.port}`, // ops events go to stub
        FREE_GEMINI_CIRCUIT_MS: "60000",
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

test("bulk daily budget gates bulk lane; unmarked lane keeps free capacity", async (t) => {
  const stub = await startGeminiStub();
  const proxy = await startProxy({
    port: 12511, stub,
    extra: { FREE_GEMINI_BULK_DAILY_BUDGET: "1" },
  });
  t.after(() => { proxy.child.kill(); stub.srv.close(); });

  // Body-field marker
  let r = await embed(proxy.port, { model: "gemini-embedding-2", input: "doc chunk one", lane: "bulk" });
  assert.equal(r.status, 200);
  assert.equal(r.body.provider, "gemini-embedding-2");

  // Header marker — bulk #2 exceeds budget=1 -> backup chain -> 502 (no backup configured)
  r = await embed(proxy.port, { model: "gemini-embedding-2", input: "doc chunk two" },
    { "x-embed-lane": "bulk" });
  assert.equal(r.status, 502);
  assert.match(r.body.error, /bulk daily budget|no backup embedding provider/);

  // Unmarked request is NOT bulk — still served by the free leg
  r = await embed(proxy.port, { model: "gemini-embedding-2", input: "interactive query" });
  assert.equal(r.status, 200);
  assert.equal(r.body.provider, "gemini-embedding-2");

  const h = await health(proxy.port);
  assert.equal(h.circuit.free_bulk_daily_budget, 1);
  assert.equal(h.circuit.free_bulk_calls_today, 1);
  assert.equal(h.circuit.free_calls_today, 2);
});

test("hourly pace spreads free quota across the day", async (t) => {
  const stub = await startGeminiStub();
  const proxy = await startProxy({
    port: 12512, stub,
    extra: { FREE_GEMINI_HOURLY_BUDGET: "1" },
  });
  t.after(() => { proxy.child.kill(); stub.srv.close(); });

  let r = await embed(proxy.port, { model: "gemini-embedding-2", input: "first" });
  assert.equal(r.status, 200);

  // Second call this hour — free leg paced, no backup -> 502
  r = await embed(proxy.port, { model: "gemini-embedding-2", input: "second" });
  assert.equal(r.status, 502);

  // Budget refusal must NOT have tripped the provider circuit
  const h = await health(proxy.port);
  assert.equal(h.circuit.free_calls_hour, 1);
  assert.equal(h.circuit.free_hourly_budget, 1);
  assert.equal(h.circuit.gemini_open, false);
  assert.equal(h.circuit.free_gemini_open, false);
  assert.equal(stub.calls.count, 1); // only one real Google call
});

test("budgets off by default — free leg serves unlimited", async (t) => {
  const stub = await startGeminiStub();
  const proxy = await startProxy({ port: 12513, stub, extra: {} });
  t.after(() => { proxy.child.kill(); stub.srv.close(); });

  for (let i = 0; i < 3; i++) {
    const r = await embed(proxy.port, { model: "gemini-embedding-2", input: `q${i}` });
    assert.equal(r.status, 200);
  }
  const h = await health(proxy.port);
  assert.equal(h.circuit.free_hourly_budget, null);
  assert.equal(h.circuit.free_bulk_daily_budget, null);
  assert.equal(h.circuit.free_calls_today, 3);
});
