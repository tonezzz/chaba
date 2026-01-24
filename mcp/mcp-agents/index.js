const express = require("express");
const cors = require("cors");
const fs = require("fs-extra");
const path = require("path");
const fetch = require("node-fetch");

require("dotenv").config();

const PORT = Number(process.env.PORT || 8046);
const AGENTS_API_BASE = process.env.AGENTS_API_BASE || "http://127.0.0.1:4060/api";
const AGENTS_DEFAULT_USER = process.env.AGENTS_DEFAULT_USER || "default";
const AGENTS_DEFAULT_LIMIT = Number(process.env.AGENTS_DEFAULT_LIMIT || 12);

const DATA_ROOT = process.env.AGENTS_DATA_ROOT || path.join(__dirname, "data", "agents", "users");

const app = express();
app.use(cors());
app.use(express.json({ limit: process.env.JSON_BODY_LIMIT || "2mb" }));

function safeJsonParse(input) {
  if (input == null) return null;
  if (typeof input === "object") return input;
  try {
    return JSON.parse(String(input));
  } catch {
    return null;
  }
}

async function listUserDir(userId) {
  const userDir = path.join(DATA_ROOT, userId);
  const exists = await fs.pathExists(userDir);
  if (!exists) return [];
  const entries = await fs.readdir(userDir);
  const files = entries.filter((n) => n.toLowerCase().endsWith(".json"));
  const withStats = await Promise.all(
    files.map(async (name) => {
      const p = path.join(userDir, name);
      const st = await fs.stat(p);
      return { name, path: p, mtimeMs: st.mtimeMs };
    })
  );
  withStats.sort((a, b) => b.mtimeMs - a.mtimeMs);
  return withStats;
}

async function readJsonFile(filePath) {
  const raw = await fs.readFile(filePath, "utf8");
  return safeJsonParse(raw) ?? { raw };
}

async function toolFetchSessions(args) {
  const userId = (args && args.user_id) || AGENTS_DEFAULT_USER;
  const limit = Number((args && args.limit) || AGENTS_DEFAULT_LIMIT);
  const files = await listUserDir(userId);
  const selected = files.slice(0, Math.max(0, limit));
  const items = await Promise.all(
    selected.map(async (f) => {
      const json = await readJsonFile(f.path);
      return {
        file: f.name,
        mtimeMs: f.mtimeMs,
        session: json,
      };
    })
  );
  return { user_id: userId, count: items.length, items };
}

async function toolFetchArchives(args) {
  const userId = (args && args.user_id) || AGENTS_DEFAULT_USER;
  const limit = Number((args && args.limit) || AGENTS_DEFAULT_LIMIT);
  const files = await listUserDir(userId);
  const selected = files.slice(0, Math.max(0, limit));
  const items = await Promise.all(
    selected.map(async (f) => {
      const json = await readJsonFile(f.path);
      const summary = {
        file: f.name,
        mtimeMs: f.mtimeMs,
      };
      if (json && typeof json === "object") {
        summary.id = json.id || json.session_id || json.run_id || null;
        summary.title = json.title || json.name || null;
        summary.messageCount = Array.isArray(json.messages) ? json.messages.length : null;
        summary.agentCount = Array.isArray(json.agents) ? json.agents.length : null;
      }
      return summary;
    })
  );
  return { user_id: userId, count: items.length, items };
}

async function toolObservabilityProbe(args) {
  const includeRegistry = Boolean(args && args.include_registry);
  const healthUrl = new URL("../api/health", AGENTS_API_BASE.endsWith("/") ? AGENTS_API_BASE : `${AGENTS_API_BASE}/`);
  const result = { agents_api_base: AGENTS_API_BASE, ok: false, health: null, registry: null };

  try {
    const res = await fetch(healthUrl.toString(), { method: "GET", timeout: 5000 });
    const text = await res.text();
    result.health = { status: res.status, body: safeJsonParse(text) ?? text };
    result.ok = res.ok;
  } catch (e) {
    result.health = { error: String(e && e.message ? e.message : e) };
  }

  if (includeRegistry) {
    const registryUrl = new URL("agents/registry", AGENTS_API_BASE.endsWith("/") ? AGENTS_API_BASE : `${AGENTS_API_BASE}/`);
    try {
      const res = await fetch(registryUrl.toString(), { method: "GET", timeout: 5000 });
      const text = await res.text();
      result.registry = { status: res.status, body: safeJsonParse(text) ?? text };
    } catch (e) {
      result.registry = { error: String(e && e.message ? e.message : e) };
    }
  }

  return result;
}

const tools = {
  fetch_sessions: toolFetchSessions,
  fetch_archives: toolFetchArchives,
  observability_probe: toolObservabilityProbe,
};

app.get("/health", async (_req, res) => {
  const healthUrl = new URL("../api/health", AGENTS_API_BASE.endsWith("/") ? AGENTS_API_BASE : `${AGENTS_API_BASE}/`);
  try {
    const r = await fetch(healthUrl.toString(), { method: "GET", timeout: 5000 });
    res.status(r.ok ? 200 : 502).json({ ok: r.ok, agents_api_base: AGENTS_API_BASE, upstream_status: r.status });
  } catch (e) {
    res.status(502).json({ ok: false, agents_api_base: AGENTS_API_BASE, error: String(e && e.message ? e.message : e) });
  }
});

app.get("/.well-known/mcp.json", (_req, res) => {
  res.json({
    name: "mcp-agents",
    version: "0.1.0",
    tools: [
      {
        name: "fetch_sessions",
        description: "Return latest saved runs for a workspace/user id",
        input_schema: {
          type: "object",
          properties: {
            user_id: { type: "string" },
            limit: { type: "number" },
          },
        },
      },
      {
        name: "fetch_archives",
        description: "Return archived sessions (summary)",
        input_schema: {
          type: "object",
          properties: {
            user_id: { type: "string" },
            limit: { type: "number" },
          },
        },
      },
      {
        name: "observability_probe",
        description: "Probe upstream agents API health and optional registry",
        input_schema: {
          type: "object",
          properties: {
            include_registry: { type: "boolean" },
          },
        },
      },
    ],
  });
});

app.post("/invoke", async (req, res) => {
  const tool = req.body && req.body.tool;
  const args = req.body && req.body.args;

  if (!tool || typeof tool !== "string") {
    res.status(400).json({ error: "Missing tool" });
    return;
  }

  const fn = tools[tool];
  if (!fn) {
    res.status(404).json({ error: `Unknown tool: ${tool}` });
    return;
  }

  try {
    const data = await fn(args || {});
    res.json({ ok: true, tool, data });
  } catch (e) {
    res.status(500).json({ ok: false, tool, error: String(e && e.message ? e.message : e) });
  }
});

app.listen(PORT, "0.0.0.0", () => {
  process.stdout.write(`mcp-agents listening on ${PORT}\n`);
});
