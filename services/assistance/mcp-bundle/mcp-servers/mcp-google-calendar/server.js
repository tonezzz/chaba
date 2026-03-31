"use strict";

const APP_NAME = "mcp-google-calendar";
const APP_VERSION = "0.0.1";

const GOOGLE_AUTH_URL = "https://accounts.google.com/o/oauth2/v2/auth";
const GOOGLE_TOKEN_URL = "https://oauth2.googleapis.com/token";
const GOOGLE_CALENDAR_API_BASE = "https://www.googleapis.com/calendar/v3";

function _envOrEmpty(v) {
  const s = String(v || "").trim();
  // 1mcp config substitution can leave literal placeholders like "${GOOGLE_CLIENT_ID}".
  if (/^\$\{[^}]+\}$/.test(s)) return "";
  return s;
}

const DEFAULT_REDIRECT_URI = "http://127.0.0.1:53682/oauth2callback";
const JARVIS_CALENDAR_NAME = String(process.env.GOOGLE_CALENDAR_JARVIS_CALENDAR_NAME || "Jarvis Reminders").trim();

const DEFAULT_SHARED_TOKEN_PATH = "/root/.config/1mcp/google.tokens.json";
const TOKEN_PATH = (process.env.GOOGLE_CALENDAR_TOKEN_PATH || DEFAULT_SHARED_TOKEN_PATH).trim();
const CLIENT_ID =
  _envOrEmpty(process.env.GOOGLE_CALENDAR_CLIENT_ID) ||
  _envOrEmpty(process.env.GOOGLE_TASKS_CLIENT_ID) ||
  _envOrEmpty(process.env.GOOGLE_CLIENT_ID);
const CLIENT_SECRET =
  _envOrEmpty(process.env.GOOGLE_CALENDAR_CLIENT_SECRET) ||
  _envOrEmpty(process.env.GOOGLE_TASKS_CLIENT_SECRET) ||
  _envOrEmpty(process.env.GOOGLE_CLIENT_SECRET);
const REDIRECT_URI = String(process.env.GOOGLE_CALENDAR_REDIRECT_URI || DEFAULT_REDIRECT_URI).trim();
const DEFAULT_SCOPES_SHARED = [
  "https://www.googleapis.com/auth/spreadsheets.readonly",
  "https://www.googleapis.com/auth/calendar",
  "https://www.googleapis.com/auth/tasks",
].join(" ");
const DEFAULT_SCOPES = TOKEN_PATH === DEFAULT_SHARED_TOKEN_PATH
  ? DEFAULT_SCOPES_SHARED
  : "https://www.googleapis.com/auth/calendar";
const SCOPES = String(process.env.GOOGLE_CALENDAR_SCOPES || DEFAULT_SCOPES)
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
    throw new Error("missing_google_calendar_client_id");
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
    redirect_uri: REDIRECT_URI,
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
      hint: "Run: node /app/mcp-servers/mcp-google-calendar/server.js auth",
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
      hint: "Re-run auth: node /app/mcp-servers/mcp-google-calendar/server.js auth",
    };
    throw e;
  }

  const refreshed = await refreshAccessToken(refresh);
  const merged = { ...tokens, ...refreshed };
  writeTokens(merged);
  return merged.access_token;
}

async function calendarGet(pathname, query) {
  const token = await getValidAccessToken();
  const url = new URL(GOOGLE_CALENDAR_API_BASE + pathname);
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

async function ensureJarvisCalendarId() {
  const list = await calendarGet("/users/me/calendarList", { maxResults: 250 });
  const items = Array.isArray(list.items) ? list.items : [];
  const found = items.find((c) => String(c.summary || "").trim() === JARVIS_CALENDAR_NAME);
  if (found && found.id) return String(found.id);
  // If not found, fall back to primary.
  const primary = items.find((c) => c.primary) || items.find((c) => String(c.id || "") === "primary");
  if (primary && primary.id) return String(primary.id);
  return "primary";
}

const TOOLS = [
  {
    name: "google_calendar_ping",
    description: "Minimal connectivity test for the Google Calendar MCP server.",
    inputSchema: {
      type: "object",
      properties: {
        message: { type: "string", description: "Optional message to echo." },
      },
    },
  },
  {
    name: "google_calendar_auth_status",
    description: "Check OAuth token status for Google Calendar (single-account).",
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
];

async function handleRpc(msg) {
  const id = msg && msg.id;
  const method = msg && msg.method;
  const params = msg && msg.params;

  const hasId = msg && Object.prototype.hasOwnProperty.call(msg, "id");
  if (!hasId) return null;

  if (method === "initialize") {
    const requestedPv = params && params.protocolVersion;
    return {
      jsonrpc: "2.0",
      id,
      result: {
        protocolVersion: typeof requestedPv === "string" && requestedPv ? requestedPv : "2024-11-05",
        capabilities: { tools: {}, resources: {}, prompts: {} },
        serverInfo: { name: APP_NAME, version: APP_VERSION },
      },
    };
  }

  if (method === "tools/list") {
    return {
      jsonrpc: "2.0",
      id,
      result: { tools: TOOLS },
    };
  }

  if (method === "tools/call") {
    const name = params && params.name;
    const args = (params && params.arguments) || {};

    if (name === "google_calendar_ping") {
      const message = typeof args.message === "string" ? args.message : "pong";
      const calendar_id = await ensureJarvisCalendarId();
      return {
        jsonrpc: "2.0",
        id,
        result: {
          content: [{ type: "text", text: JSON.stringify({ ok: true, message, server: APP_NAME, version: APP_VERSION, now: nowIso(), calendar_id }) }],
        },
      };
    }

    if (name === "google_calendar_auth_status") {
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
        calendar_name: JARVIS_CALENDAR_NAME,
      };

      if (includeRaw) out.raw_tokens = tokens;

      return {
        jsonrpc: "2.0",
        id,
        result: { content: [{ type: "text", text: JSON.stringify(out) }] },
      };
    }

    return {
      jsonrpc: "2.0",
      id,
      error: { code: -32601, message: "tool_not_found" },
    };
  }

  return {
    jsonrpc: "2.0",
    id,
    error: { code: -32601, message: "method_not_found" },
  };
}

let buf = Buffer.alloc(0);
let lineBuf = "";

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
    if (res) write(res);
  } catch (e) {
    write({
      jsonrpc: "2.0",
      id: msg && Object.prototype.hasOwnProperty.call(msg, "id") ? msg.id : null,
      error: { code: -32603, message: "Internal error", data: { error: String(e && e.message ? e.message : e) } },
    });
  }
}

async function main() {
  process.stdin.on("data", async (chunk) => {
    const b = Buffer.isBuffer(chunk) ? chunk : Buffer.from(String(chunk), "utf8");
    buf = Buffer.concat([buf, b]);
    lineBuf += b.toString("utf8");

    while (true) {
      const frame = parseNextFrame(buf);
      if (!frame) break;
      _ioMode = _ioMode || "content-length";
      buf = frame.rest;
      const msg = safeJsonParse(frame.body);
      if (!msg) continue;
      await handleMessage(msg);
    }

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
  });

  process.stdin.on("end", () => process.exit(0));
}

main().catch((e) => {
  try {
    if (e && e.details) {
      process.stderr.write("mcp-google-calendar error details: " + JSON.stringify(e.details) + "\n");
    }
  } catch {}
  process.stderr.write("mcp-google-calendar startup error: " + String(e && e.message ? e.message : e) + "\n");
  process.exit(1);
});
