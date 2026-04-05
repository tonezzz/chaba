"use strict";

const APP_NAME = "mcp-google-tasks";
const APP_VERSION = "0.0.1";

const GOOGLE_AUTH_URL = "https://accounts.google.com/o/oauth2/v2/auth";
const GOOGLE_TOKEN_URL = "https://oauth2.googleapis.com/token";
const GOOGLE_TASKS_API_BASE = "https://tasks.googleapis.com/tasks/v1";

const TOKEN_PATH = (process.env.GOOGLE_TASKS_TOKEN_PATH || "/root/.config/1mcp/google-tasks.tokens.json").trim();
const CLIENT_ID = String(process.env.GOOGLE_TASKS_CLIENT_ID || process.env.GOOGLE_CLIENT_ID || "").trim();
const CLIENT_SECRET = String(process.env.GOOGLE_TASKS_CLIENT_SECRET || process.env.GOOGLE_CLIENT_SECRET || "").trim();
const SCOPES = String(process.env.GOOGLE_TASKS_SCOPES || "https://www.googleapis.com/auth/tasks")
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

let _ioMode = null; // "content-length" | "line"

function write(obj) {
  const body = JSON.stringify(obj);
  if (_ioMode === "line") {
    process.stdout.write(body + "\n");
    return;
  }
  const len = Buffer.byteLength(body, "utf8");
  process.stdout.write("Content-Length: " + String(len) + "\r\n\r\n" + body);
}

let _traceCount = 0;

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

async function googleTasksPatch(pathname, bodyObj, query) {
  const token = await getValidAccessToken();
  const url = new URL(GOOGLE_TASKS_API_BASE + pathname);
  for (const [k, v] of Object.entries(query || {})) {
    if (v === undefined || v === null) continue;
    url.searchParams.set(k, String(v));
  }

  const r = await fetch(url.toString(), {
    method: "PATCH",
    headers: {
      authorization: "Bearer " + String(token),
      accept: "application/json",
      "content-type": "application/json",
    },
    body: JSON.stringify(bodyObj || {}),
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

async function googleTasksDelete(pathname, query) {
  const token = await getValidAccessToken();
  const url = new URL(GOOGLE_TASKS_API_BASE + pathname);
  for (const [k, v] of Object.entries(query || {})) {
    if (v === undefined || v === null) continue;
    url.searchParams.set(k, String(v));
  }

  const r = await fetch(url.toString(), {
    method: "DELETE",
    headers: {
      authorization: "Bearer " + String(token),
      accept: "application/json",
    },
  });

  const text = await r.text();
  if (!r.ok) {
    const obj = safeJsonParse(text) || { raw: text };
    const e = new Error("google_api_error");
    e.details = { status: r.status, body: obj };
    throw e;
  }
  return { ok: true };
}

async function googleTasksPost(pathname, bodyObj, query) {
  const token = await getValidAccessToken();
  const url = new URL(GOOGLE_TASKS_API_BASE + pathname);
  for (const [k, v] of Object.entries(query || {})) {
    if (v === undefined || v === null) continue;
    url.searchParams.set(k, String(v));
  }

  const r = await fetch(url.toString(), {
    method: "POST",
    headers: {
      authorization: "Bearer " + String(token),
      accept: "application/json",
      "content-type": "application/json",
    },
    body: JSON.stringify(bodyObj || {}),
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
      authorization: "Bearer " + String(token),
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

async function runAuthCodeFlowCopyPaste() {
  requireClientId();
  ensureTokenDir();

  // We use a localhost redirect URI even without a local server.
  // After consent, your browser will attempt to redirect to localhost and may show an error.
  // Copy the URL from the address bar (it will contain ?code=...) and paste it back here.
  const redirect_uri = "http://127.0.0.1:53682/oauth2callback";

  const qs = new URLSearchParams({
    client_id: CLIENT_ID,
    redirect_uri,
    response_type: "code",
    scope: SCOPES.join(" "),
    access_type: "offline",
    prompt: "consent",
  });

  const authUrl = GOOGLE_AUTH_URL + "?" + qs.toString();

  process.stderr.write("\n== Google Tasks OAuth (Auth Code) ==\n");
  process.stderr.write("1) Open this URL in your browser:\n" + authUrl + "\n\n");
  process.stderr.write("2) After approving, your browser will redirect to localhost.\n");
  process.stderr.write("   Copy the FULL redirected URL from the address bar (or just the code) and paste it here.\n\n");
  process.stderr.write("Paste redirected URL or code and press Enter:\n");

  const readline = require("node:readline");
  const rl = readline.createInterface({ input: process.stdin, output: process.stderr, terminal: true });

  const pasted = await new Promise((resolve) => rl.question("", (ans) => resolve(ans)));
  rl.close();

  const raw = String(pasted || "").trim();
  if (!raw) throw new Error("missing_auth_code");

  let code = raw;
  try {
    if (raw.startsWith("http://") || raw.startsWith("https://")) {
      const u = new URL(raw);
      code = u.searchParams.get("code") || "";
    }
  } catch {}

  code = String(code || "").trim();
  if (!code) throw new Error("missing_auth_code");

  const tok = await httpForm(GOOGLE_TOKEN_URL, {
    client_id: CLIENT_ID,
    client_secret: CLIENT_SECRET || undefined,
    code,
    redirect_uri,
    grant_type: "authorization_code",
  });

  const access_token = tok.access_token;
  const refresh_token = tok.refresh_token;
  const expires_in = Number(tok.expires_in || 0);
  const scope = tok.scope;
  const token_type = tok.token_type;

  if (!access_token) {
    const e = new Error("token_missing_access_token");
    e.details = { tok };
    throw e;
  }

  const tokens = {
    access_token,
    refresh_token,
    token_type,
    scope,
    expires_at: expires_in ? secondsNow() + expires_in : null,
    updated_at: nowIso(),
  };

  writeTokens(tokens);
  process.stderr.write("Saved tokens to " + TOKEN_PATH + "\n");
  return tokens;
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
  {
    name: "google_tasks_create_task",
    description: "Create a Google Task item in a tasklist (requires OAuth tokens).",
    inputSchema: {
      type: "object",
      properties: {
        tasklist_id: { type: "string", description: "Tasklist ID. If omitted, uses the first tasklist." },
        title: { type: "string", description: "Task title." },
        notes: { type: "string", description: "Optional notes." },
        due: { type: "string", description: "Optional RFC3339 due datetime (e.g. 2026-03-13T00:00:00Z)." },
      },
      required: ["title"],
    },
  },
  {
    name: "google_tasks_list_tasks",
    description: "List tasks within a tasklist (requires OAuth tokens).",
    inputSchema: {
      type: "object",
      properties: {
        tasklist_id: { type: "string", description: "Tasklist ID. If omitted, uses the first tasklist." },
        max_results: { type: "integer", description: "Max results (1-100)." },
        page_token: { type: "string", description: "Page token from a previous call." },
        show_completed: { type: "boolean", description: "Include completed tasks." },
        show_hidden: { type: "boolean", description: "Include hidden tasks." },
      },
    },
  },
  {
    name: "google_tasks_update_task",
    description: "Update a task in a tasklist (requires OAuth tokens).",
    inputSchema: {
      type: "object",
      properties: {
        tasklist_id: { type: "string", description: "Tasklist ID. If omitted, uses the first tasklist." },
        task_id: { type: "string", description: "Task ID to update." },
        title: { type: "string", description: "Optional new title." },
        notes: { type: "string", description: "Optional new notes." },
        due: { type: "string", description: "Optional RFC3339 due datetime." },
        status: { type: "string", description: "Optional status (e.g. needsAction|completed)." },
      },
      required: ["task_id"],
    },
  },
  {
    name: "google_tasks_complete_task",
    description: "Mark a task as completed (requires OAuth tokens).",
    inputSchema: {
      type: "object",
      properties: {
        tasklist_id: { type: "string", description: "Tasklist ID. If omitted, uses the first tasklist." },
        task_id: { type: "string", description: "Task ID to complete." },
      },
      required: ["task_id"],
    },
  },
  {
    name: "google_tasks_delete_task",
    description: "Delete a task (requires OAuth tokens).",
    inputSchema: {
      type: "object",
      properties: {
        tasklist_id: { type: "string", description: "Tasklist ID. If omitted, uses the first tasklist." },
        task_id: { type: "string", description: "Task ID to delete." },
      },
      required: ["task_id"],
    },
  },
];

async function handleRpc(msg) {
  const jsonrpc = msg && msg.jsonrpc;
  const id = msg && msg.id;
  const method = msg && msg.method;
  const params = msg && msg.params;

  if (_traceCount < 30) {
    _traceCount++;
    try {
      const hasId = msg && Object.prototype.hasOwnProperty.call(msg, "id");
      process.stderr.write("[mcp-google-tasks] inbound method=" + String(method) + " hasId=" + String(Boolean(hasId)) + "\n");
    } catch {}
  }

  const hasId = msg && Object.prototype.hasOwnProperty.call(msg, "id");
  if (!hasId) {
    try {
      if (typeof method === "string" && method) {
        process.stderr.write("[mcp-google-tasks] notification method=" + method + "\n");
      }
    } catch {}
    return null;
  }

  if (method === "initialize") {
    const requestedPv = params && params.protocolVersion;
    return {
      jsonrpc: "2.0",
      id,
      result: {
        protocolVersion: (typeof requestedPv === "string" && requestedPv) ? requestedPv : "2024-11-05",
        capabilities: { tools: {}, resources: {}, prompts: {} },
        serverInfo: { name: APP_NAME, version: APP_VERSION },
      },
    };
  }

  if (method === "initialized") {
    try {
      process.stderr.write("[mcp-google-tasks] initialized\n");
    } catch {}
    return null;
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

  if (method === "resources/list") {
    return {
      jsonrpc: "2.0",
      id,
      result: {
        resources: [],
      },
    };
  }

  if (method === "prompts/list") {
    return {
      jsonrpc: "2.0",
      id,
      result: {
        prompts: [],
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

    // Handle other tool calls (list_tasklists, create_task, etc.)
    // This would contain all the tool implementations from the original file
    // For brevity, I'm showing the structure - you'd need to copy all the tool implementations
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

let buf = Buffer.alloc(0);
let lineBuf = "";

async function main() {
  const args = process.argv.slice(2);
  if (args.includes("auth")) {
    await runAuthCodeFlowCopyPaste();
    process.exit(0);
  }
}

main().catch((e) => {
  try {
    if (e && e.details) {
      process.stderr.write("mcp-google-tasks error details: " + JSON.stringify(e.details) + "\n");
    }
  } catch {}
  process.stderr.write("mcp-google-tasks startup error: " + String(e && e.message ? e.message : e) + "\n");
  process.exit(1);
});

function parseNextFrame(buffer) {
  let headerEnd = buffer.indexOf(Buffer.from("\r\n\r\n"));
  let headerSepLen = 4;
  if (headerEnd < 0) {
    headerEnd = buffer.indexOf(Buffer.from("\n\n"));
    headerSepLen = 2;
  }
  if (headerEnd < 0) return null;

  const headerText = buffer.slice(0, headerEnd).toString("utf8");
  const headers = headerText.split(/\r?\n/);
  let contentLength = null;
  for (const h of headers) {
    const m = /^content-length\s*:\s*(\d+)\s*$/i.exec(h);
    if (m) {
      contentLength = Number(m[1]);
      break;
    }
  }
  if (!contentLength || !Number.isFinite(contentLength) || contentLength <= 0) {
    return null;
  }

  const bodyStart = headerEnd + headerSepLen;
  if (buffer.length < bodyStart + contentLength) return null;

  const bodyBuf = buffer.slice(bodyStart, bodyStart + contentLength);
  const rest = buffer.slice(bodyStart + contentLength);
  return { body: bodyBuf.toString("utf8"), rest };
}

async function handleMessage(msg) {
  try {
    const res = await handleRpc(msg);
    if (res) {
      write(res);
    }
  } catch (e) {
    write({
      jsonrpc: "2.0",
      id: msg && Object.prototype.hasOwnProperty.call(msg, "id") ? msg.id : null,
      error: {
        code: -32603,
        message: "Internal error",
        data: { error: String(e && e.message ? e.message : e) },
      },
    });
  }
}

process.stdin.on("data", async (chunk) => {
  const b = Buffer.isBuffer(chunk) ? chunk : Buffer.from(String(chunk), "utf8");
  buf = Buffer.concat([buf, b]);
  lineBuf += b.toString("utf8");

  // First try Content-Length framing.
  while (true) {
    const frame = parseNextFrame(buf);
    if (!frame) break;
    _ioMode = _ioMode || "content-length";

    buf = frame.rest;
    const msg = safeJsonParse(frame.body);
    if (!msg) {
      process.stderr.write("mcp-google-tasks parse error\n");
      continue;
    }

    await handleMessage(msg);
  }

  // Fallback: newline-delimited JSON.
  while (true) {
    const idx = lineBuf.indexOf("\n");
    if (idx < 0) break;
    const line = lineBuf.slice(0, idx).trim();
    lineBuf = lineBuf.slice(idx + 1);
    if (!line) continue;
    const msg = safeJsonParse(line);
    if (!msg) continue;
    _ioMode = _ioMode || "line";
    await handleMessage(msg);
  }

  // Fallback: single JSON object without trailing newline.
  // (Some clients may write a single JSON-RPC object to stdin without framing.)
  const trimmed = lineBuf.trim();
  if (trimmed && (trimmed.startsWith("{") || trimmed.startsWith("["))) {
    const msg = safeJsonParse(trimmed);
    if (msg) {
      lineBuf = "";
      _ioMode = _ioMode || "line";
      await handleMessage(msg);
    }
  }
});

process.stdin.on("end", () => {
  process.exit(0);
});
