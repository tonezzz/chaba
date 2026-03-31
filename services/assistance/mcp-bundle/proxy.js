const http = require("http");
const { spawn } = require("child_process");

const PROXY_PORT = Number(process.env.ONE_MCP_PORT || process.env.PORT || 3050);
const PROXY_HOST = String(process.env.ONE_MCP_HOST || "0.0.0.0");
const UPSTREAM_PORT = Number(process.env.ONE_MCP_UPSTREAM_PORT || 3052);
const UPSTREAM_HOST = "127.0.0.1";
const JSON_LIMIT = String(process.env.ONE_MCP_PROXY_JSON_LIMIT || "5mb");

function parseLimitToBytes(limit) {
  const s = String(limit || "").trim().toLowerCase();
  const m = /^(\d+)(b|kb|mb)?$/.exec(s);
  if (!m) return 5 * 1024 * 1024;
  const n = Number(m[1]);
  const unit = m[2] || "b";
  if (!Number.isFinite(n) || n <= 0) return 5 * 1024 * 1024;
  if (unit === "kb") return n * 1024;
  if (unit === "mb") return n * 1024 * 1024;
  return n;
}

const JSON_LIMIT_BYTES = parseLimitToBytes(JSON_LIMIT);

function sendJson(res, status, obj) {
  const txt = JSON.stringify(obj);
  res.statusCode = status;
  res.setHeader("content-type", "application/json");
  res.end(txt);
}

function startUpstream() {
  const env = {
    ...process.env,
    // 1mcp (base image) commonly uses PORT; the legacy compose override used ONE_MCP_PORT.
    // Set both to ensure the upstream actually binds to the expected port.
    PORT: String(UPSTREAM_PORT),
    ONE_MCP_PORT: String(UPSTREAM_PORT),
    // Upstream should only be reachable from within the container.
    ONE_MCP_HOST: "127.0.0.1",
  };
  const child = spawn(
    "node",
    [
      "/usr/src/app/index.js",
      "serve",
      "--transport",
      "http",
      "--host",
      "127.0.0.1",
      "--port",
      String(UPSTREAM_PORT),
    ],
    { env, stdio: "inherit" }
  );
  child.on("exit", (code) => {
    process.stderr.write(`upstream 1mcp exited code=${code}\n`);
    process.exit(code || 1);
  });
  return child;
}

async function waitHealthy(timeoutMs = 20000) {
  const start = Date.now();
  while (Date.now() - start < timeoutMs) {
    try {
      const r = await fetch(`http://${UPSTREAM_HOST}:${UPSTREAM_PORT}/health`);
      if (r.ok) return true;
    } catch {}
    await new Promise((r) => setTimeout(r, 250));
  }
  return false;
}

function readBody(req) {
  return new Promise((resolve, reject) => {
    let size = 0;
    const chunks = [];
    req.on("data", (c) => {
      const b = Buffer.isBuffer(c) ? c : Buffer.from(String(c), "utf8");
      size += b.length;
      if (size > JSON_LIMIT_BYTES) {
        const err = new Error("request entity too large");
        err.code = "entity.too.large";
        reject(err);
        req.destroy();
        return;
      }
      chunks.push(b);
    });
    req.on("end", () => resolve(Buffer.concat(chunks)));
    req.on("error", reject);
  });
}

async function main() {
  startUpstream();
  const ok = await waitHealthy();
  if (!ok) {
    process.stderr.write("upstream healthcheck failed\n");
  }

  const server = http.createServer(async (req, res) => {
    try {
      const u = new URL(req.url || "/", "http://127.0.0.1");

      if (req.method === "GET" && u.pathname === "/health") {
        const r = await fetch(`http://${UPSTREAM_HOST}:${UPSTREAM_PORT}/health`);
        const txt = await r.text();
        res.statusCode = r.status;
        const ct = r.headers.get("content-type");
        if (ct) res.setHeader("content-type", ct);
        res.end(txt);
        return;
      }

      if (req.method === "POST" && u.pathname === "/mcp") {
        const bodyBuf = await readBody(req);
        let parsed = {};
        if (bodyBuf.length) {
          try {
            parsed = JSON.parse(bodyBuf.toString("utf8"));
          } catch {
            sendJson(res, 400, { ok: false, error: "invalid_json" });
            return;
          }
        }

        const url = `http://${UPSTREAM_HOST}:${UPSTREAM_PORT}/mcp${u.search || ""}`;
        const r = await fetch(url, {
          method: "POST",
          headers: {
            "content-type": "application/json",
            accept: String(req.headers.accept || "application/json, text/event-stream"),
            "mcp-session-id": String(req.headers["mcp-session-id"] || ""),
          },
          body: JSON.stringify(parsed || {}),
        });

        res.statusCode = r.status;
        const ct = r.headers.get("content-type");
        if (ct) res.setHeader("content-type", ct);
        const sid = r.headers.get("mcp-session-id");
        if (sid) res.setHeader("mcp-session-id", sid);
        const out = Buffer.from(await r.arrayBuffer());
        res.end(out);
        return;
      }

      sendJson(res, 404, { ok: false, error: "not_found" });
    } catch (e) {
      if (e && e.code === "entity.too.large") {
        sendJson(res, 413, { ok: false, error: "entity.too.large", limit: JSON_LIMIT_BYTES });
        return;
      }
      sendJson(res, 502, { ok: false, error: String(e && e.message ? e.message : e) });
    }
  });

  server.listen(PROXY_PORT, PROXY_HOST, () => {
    process.stdout.write(
      `mcp proxy listening on http://${PROXY_HOST}:${PROXY_PORT} (json limit ${JSON_LIMIT}), upstream :${UPSTREAM_PORT}\n`
    );
  });
}

main().catch((e) => {
  process.stderr.write(`proxy startup error: ${String(e && e.message ? e.message : e)}\n`);
  process.exit(1);
});
