"use strict";

const APP_NAME = "mcp-google-tasks";
const APP_VERSION = "0.0.1";

const GOOGLE_DEVICE_CODE_URL = "https://oauth2.googleapis.com/device/code";
const GOOGLE_TOKEN_URL = "https://oauth2.googleapis.com/token";
const GOOGLE_TASKS_API_BASE = "https://tasks.googleapis.com/tasks/v1";

const DEFAULT_SHARED_TOKEN_PATH = "/root/.config/1mcp/google.tokens.json";
const TOKEN_PATH = (process.env.GOOGLE_TASKS_TOKEN_PATH || DEFAULT_SHARED_TOKEN_PATH).trim();
const CLIENT_ID = String(process.env.GOOGLE_TASKS_CLIENT_ID || process.env.GOOGLE_CLIENT_ID || "").trim();
const CLIENT_SECRET = String(process.env.GOOGLE_TASKS_CLIENT_SECRET || process.env.GOOGLE_CLIENT_SECRET || "").trim();
const DEFAULT_SCOPES_SHARED = [
  "https://www.googleapis.com/auth/spreadsheets.readonly",
  "https://www.googleapis.com/auth/calendar",
  "https://www.googleapis.com/auth/tasks",
].join(" ");
const DEFAULT_SCOPES = TOKEN_PATH === DEFAULT_SHARED_TOKEN_PATH
  ? DEFAULT_SCOPES_SHARED
  : "https://www.googleapis.com/auth/tasks";
const SCOPES = String(process.env.GOOGLE_TASKS_SCOPES || DEFAULT_SCOPES)
  .split(",")
  .map((s) => s.trim())
  .filter(Boolean);

const fs = require("node:fs");
const path = require("node:path");

function safeJsonParse(s) {
  try {
    return JSON.parse(s);
  } catch {
    return null;
  }
}

function write(obj) {
  const body = JSON.stringify(obj);
  const len = Buffer.byteLength(body, "utf8");
  process.stdout.write(`Content-Length: ${len}\r\n\r\n${body}`);
}

function nowIso() {
  return new Date().toISOString();
}

function ensureTokenDir() {
  const dir = path.dirname(TOKEN_PATH);
  fs.mkdirSync(dir, { recursive: true });
}

function readTokens() {
  try {
    if (!fs.existsSync(TOKEN_PATH)) return null;
    const raw = fs.readFileSync(TOKEN_PATH, "utf-8");
    const obj = safeJsonParse(raw);
    if (!obj || typeof obj !== "object") return null;
    return obj;
  } catch {
    return null;
  }
}

function writeTokens(tokens) {
  ensureTokenDir();
  fs.writeFileSync(TOKEN_PATH, JSON.stringify(tokens, null, 2));
}

function requireClientId() {
  if (!CLIENT_ID) {
    throw new Error("missing_google_tasks_client_id");
  }
}

function secondsNow() {
  return Math.floor(Date.now() / 1000);
}

async function httpForm(url, formObj) {
  const body = new URLSearchParams();
  for (const [k, v] of Object.entries(formObj || {})) {
    if (v === undefined || v === null) continue;
    body.set(k, String(v));
  }

  const r = await fetch(url, {
    method: "POST",
    headers: {
      "content-type": "application/x-www-form-urlencoded",
      accept: "application/json",
    },
    body,
  });

  const text = await r.text();
  const obj = safeJsonParse(text) || { raw: text };
  if (!r.ok) {
    const e = new Error("http_error");
    e.details = { url, status: r.status, body: obj };
    throw e;
  }
  return obj;
}

async function refreshAccessToken(refreshToken) {
  requireClientId();
  const payload = {
    client_id: CLIENT_ID,
    grant_type: "refresh_token",
    refresh_token: refreshToken,
  };
  if (CLIENT_SECRET) payload.client_secret = CLIENT_SECRET;

  const res = await httpForm(GOOGLE_TOKEN_URL, payload);
  const access_token = res.access_token;
  const expires_in = Number(res.expires_in || 0);
  if (!access_token || !expires_in) {
    const e = new Error("invalid_refresh_response");
    e.details = res;
    throw e;
  }
  return {
    access_token,
    expires_at: secondsNow() + Math.max(30, expires_in - 10),
  };
}

async function getValidAccessToken() {
  const tokens = readTokens();
  if (!tokens || typeof tokens !== "object") {
    const e = new Error("auth_required");
    e.details = {
      token_path: TOKEN_PATH,
      hint: "Run: node /app/mcp-servers/mcp-google-tasks/server.js auth",
    };
    throw e;
  }

  const access = typeof tokens.access_token === "string" ? tokens.access_token : "";
  const expires_at = Number(tokens.expires_at || 0);
  const refresh = typeof tokens.refresh_token === "string" ? tokens.refresh_token : "";

  if (access && expires_at && expires_at > secondsNow() + 30) {
    return access;
  }

  if (!refresh) {
    const e = new Error("auth_required");
    e.details = {
      token_path: TOKEN_PATH,
      reason: "missing_refresh_token",
      hint: "Re-run auth: node /app/mcp-servers/mcp-google-tasks/server.js auth",
    };
    throw e;
  }

  const refreshed = await refreshAccessToken(refresh);
  const merged = { ...tokens, ...refreshed };
  writeTokens(merged);
  return merged.access_token;
}

async function googleTasksGet(pathname, query) {
  const token = await getValidAccessToken();
  const url = new URL(GOOGLE_TASKS_API_BASE + pathname);
  for (const [k, v] of Object.entries(query || {})) {
    if (v === undefined || v === null) continue;
    url.searchParams.set(k, String(v));
  }

  const r = await fetch(url.toString(), {
    method: "GET",
    headers: {
      authorization: `Bearer ${token}`,
      accept: "application/json",
    },
  });

  const text = await r.text();
  const obj = safeJsonParse(text) || { raw: text };
  if (!r.ok) {
    const e = new Error("google_api_error");
    e.details = { status: r.status, body: obj };
    throw e;
  }
  return obj;
}

async function runAuthDeviceFlow() {
  requireClientId();
  ensureTokenDir();

  const device = await httpForm(GOOGLE_DEVICE_CODE_URL, {
    client_id: CLIENT_ID,
    scope: SCOPES.join(" "),
  });

  const verification_url = device.verification_url || device.verification_uri;
  const user_code = device.user_code;
  const device_code = device.device_code;
  const interval = Number(device.interval || 5);
  const expires_in = Number(device.expires_in || 600);

  if (!verification_url || !user_code || !device_code) {
    const e = new Error("invalid_device_code_response");
    e.details = device;
    throw e;
  }

  process.stderr.write("\nGOOGLE TASKS AUTH\n");
  process.stderr.write("1) Open: " + String(verification_url) + "\n");
  process.stderr.write("2) Enter code: " + String(user_code) + "\n\n");

  const started = Date.now();
  for (;;) {
    if (Date.now() - started > expires_in * 1000) {
      throw new Error("device_code_expired");
    }

    await new Promise((r) => setTimeout(r, Math.max(1, interval) * 1000));

    let tok;
    try {
      tok = await httpForm(GOOGLE_TOKEN_URL, {
        client_id: CLIENT_ID,
        device_code,
        grant_type: "urn:ietf:params:oauth:grant-type:device_code",
        client_secret: CLIENT_SECRET || undefined,
      });
    } catch (e) {
      const body = e && e.details ? e.details.body : null;
      const err = body && typeof body.error === "string" ? body.error : "";
      if (err === "authorization_pending") continue;
      if (err === "slow_down") continue;
      throw e;
    }

    const access_token = tok.access_token;
    const refresh_token = tok.refresh_token;
    const expiresIn = Number(tok.expires_in || 0);
    if (!access_token || !expiresIn) {
      const e = new Error("invalid_token_response");
      e.details = tok;
      throw e;
    }

    const saved = {
      access_token,
      refresh_token: refresh_token || null,
      expires_at: secondsNow() + Math.max(30, expiresIn - 10),
      scope: tok.scope || SCOPES.join(" "),
      token_type: tok.token_type || "Bearer",
      created_at: secondsNow(),
    };
    writeTokens(saved);

    process.stderr.write("Saved tokens to: " + TOKEN_PATH + "\n");
    return;
  }
}

const TOOLS = [
  {
    name: "google_tasks_ping",
    description: "Minimal connectivity test for the Google Tasks MCP server.",
    inputSchema: {
      type: "object",
      properties: {
        message: { type: "string", description: "Optional message to echo." },
      },
    },
  },
  {
    name: "google_tasks_auth_status",
    description: "Check OAuth token status for Google Tasks (single-account).",
    inputSchema: {
      type: "object",
      properties: {
        include_raw_tokens: {
          type: "boolean",
          description: "If true, include raw token JSON in the response (not recommended).",
        },
      },
    },
  },
  {
    name: "google_tasks_list_tasklists",
    description: "List the user's Google Tasklists (requires OAuth tokens).",
    inputSchema: {
      type: "object",
      properties: {
        max_results: { type: "integer", description: "Max results (1-100)." },
        page_token: { type: "string", description: "Page token from a previous call." },
      },
    },
  },
];

async function handleRpc(msg) {
  const id = msg && Object.prototype.hasOwnProperty.call(msg, "id") ? msg.id : null;
  const method = msg && msg.method;
  const params = (msg && msg.params) || {};

  if (method === "initialize") {
    return {
      jsonrpc: "2.0",
      id,
      result: {
        protocolVersion: "2024-11-05",
        capabilities: { tools: {} },
        serverInfo: { name: APP_NAME, version: APP_VERSION },
      },
    };
  }

  if (method === "tools/list") {
    return {
      jsonrpc: "2.0",
      id,
      result: {
        tools: TOOLS,
      },
    };
  }

  if (method === "tools/call") {
    const name = params && params.name;
    const args = (params && params.arguments) || {};

    if (name === "google_tasks_ping") {
      const message = typeof args.message === "string" ? args.message : "pong";
      return {
        jsonrpc: "2.0",
        id,
        result: {
          content: [
            {
              type: "text",
              text: JSON.stringify({ ok: true, message, server: APP_NAME, version: APP_VERSION, now: nowIso() }),
            },
          ],
        },
      };
    }

    if (name === "google_tasks_auth_status") {
      const includeRaw = Boolean(args.include_raw_tokens);
      const tokens = readTokens();
      const now = secondsNow();
      const access_token = tokens && typeof tokens.access_token === "string" ? tokens.access_token : null;
      const refresh_token = tokens && typeof tokens.refresh_token === "string" ? tokens.refresh_token : null;
      const expires_at = tokens && tokens.expires_at ? Number(tokens.expires_at) : null;
      const scope = tokens && typeof tokens.scope === "string" ? tokens.scope : SCOPES.join(" ");

      const out = {
        ok: true,
        token_path: TOKEN_PATH,
        has_token_file: Boolean(tokens),
        has_access_token: Boolean(access_token),
        has_refresh_token: Boolean(refresh_token),
        expires_at: expires_at,
        expires_in_seconds: expires_at ? Math.max(0, expires_at - now) : null,
        is_access_token_valid: expires_at ? expires_at > now + 30 : false,
        scopes: String(scope)
          .split(/\s+/)
          .map((s) => s.trim())
          .filter(Boolean),
        client_id_present: Boolean(CLIENT_ID),
        auth_hint: "Run: node /app/mcp-servers/mcp-google-tasks/server.js auth",
      };

      if (includeRaw) {
        out.raw_tokens = tokens;
      }

      return {
        jsonrpc: "2.0",
        id,
        result: {
          content: [{ type: "text", text: JSON.stringify(out) }],
        },
      };
    }

    if (name === "google_tasks_list_tasklists") {
      const max_results_raw = args.max_results;
      const page_token_raw = args.page_token;
      const maxResults =
        typeof max_results_raw === "number" && Number.isFinite(max_results_raw)
          ? Math.max(1, Math.min(100, Math.floor(max_results_raw)))
          : undefined;
      const pageToken = typeof page_token_raw === "string" && page_token_raw.trim() ? page_token_raw.trim() : undefined;

      const data = await googleTasksGet("/users/@me/lists", {
        maxResults,
        pageToken,
      });

      return {
        jsonrpc: "2.0",
        id,
        result: {
          content: [{ type: "text", text: JSON.stringify({ ok: true, data }) }],
        },
      };
    }

    return {
      jsonrpc: "2.0",
      id,
      error: {
        code: -32601,
        message: "Tool not found",
        data: { name },
      },
    };
  }

  return {
    jsonrpc: "2.0",
    id,
    error: {
      code: -32601,
      message: "Method not found",
      data: { method },
    },
  };
}

let buf = "";
process.stdin.setEncoding("utf8");

async function main() {
  const args = process.argv.slice(2);
  if (args.includes("auth")) {
    await runAuthDeviceFlow();
    process.exit(0);
  }
}

main().catch((e) => {
  process.stderr.write("mcp-google-tasks startup error: " + String(e && e.message ? e.message : e) + "\n");
  process.exit(1);
});

function parseNextFrame(buffer) {
  const headerEnd = buffer.indexOf("\r\n\r\n");
  if (headerEnd < 0) return null;

  const headerText = buffer.slice(0, headerEnd);
  const headers = headerText.split("\r\n");
  let contentLength = null;
  for (const h of headers) {
    const m = /^content-length\s*:\s*(\d+)\s*$/i.exec(h);
    if (m) {
      contentLength = Number(m[1]);
      break;
    }
  }
  if (!contentLength || !Number.isFinite(contentLength) || contentLength <= 0) {
    return { error: "missing_or_invalid_content_length" };
  }

  const bodyStart = headerEnd + 4;
  if (buffer.length < bodyStart + contentLength) return null;

  const body = buffer.slice(bodyStart, bodyStart + contentLength);
  const rest = buffer.slice(bodyStart + contentLength);
  return { body, rest };
}

process.stdin.on("data", async (chunk) => {
  buf += chunk;
  for (;;) {
    const frame = parseNextFrame(buf);
    if (!frame) return;
    if (frame.error) {
      // Can't reliably respond without an id; log and drop buffer.
      process.stderr.write("mcp-google-tasks framing error: " + String(frame.error) + "\n");
      buf = "";
      return;
    }

    buf = frame.rest;
    const msg = safeJsonParse(frame.body);
    if (!msg) {
      // Can't reliably respond without an id; ignore.
      process.stderr.write("mcp-google-tasks parse error\n");
      continue;
    }

    try {
      const res = await handleRpc(msg);
      write(res);
    } catch (e) {
      write({
        jsonrpc: "2.0",
        id: msg.id ?? null,
        error: {
          code: -32603,
          message: "Internal error",
          data: { error: String(e && e.message ? e.message : e) },
        },
      });
    }
  }
});

process.stdin.on("end", () => {
  process.exit(0);
});
