"use strict";

const APP_NAME = "mcp-google-calendar";
const APP_VERSION = "0.0.1";

const GOOGLE_AUTH_URL = "https://accounts.google.com/o/oauth2/v2/auth";
const GOOGLE_TOKEN_URL = "https://oauth2.googleapis.com/token";
const GOOGLE_CALENDAR_API_BASE = "https://www.googleapis.com/calendar/v3";

const DEFAULT_REDIRECT_URI = "http://127.0.0.1:53682/oauth2callback";
const JARVIS_CALENDAR_NAME = String(process.env.GOOGLE_CALENDAR_JARVIS_CALENDAR_NAME || "Jarvis Reminders").trim();

const DEFAULT_SHARED_TOKEN_PATH = "/root/.config/1mcp/google.tokens.json";
const TOKEN_PATH = (process.env.GOOGLE_CALENDAR_TOKEN_PATH || DEFAULT_SHARED_TOKEN_PATH).trim();
const CLIENT_ID = String(
  process.env.GOOGLE_CALENDAR_CLIENT_ID || process.env.GOOGLE_TASKS_CLIENT_ID || process.env.GOOGLE_CLIENT_ID || ""
).trim();
const CLIENT_SECRET = String(
  process.env.GOOGLE_CALENDAR_CLIENT_SECRET || process.env.GOOGLE_TASKS_CLIENT_SECRET || process.env.GOOGLE_CLIENT_SECRET || ""
).trim();
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

function _authUrl() {
  requireClientId();
  const url = new URL(GOOGLE_AUTH_URL);
  url.searchParams.set("client_id", CLIENT_ID);
  url.searchParams.set("redirect_uri", REDIRECT_URI);
  url.searchParams.set("response_type", "code");
  url.searchParams.set("access_type", "offline");
  url.searchParams.set("prompt", "consent");
  url.searchParams.set("scope", SCOPES.join(" "));
  return url.toString();
}

function _extractCodeFromUserInput(raw) {
  const s = String(raw || "").trim();
  if (!s) return "";
  if (/^[A-Za-z0-9_\-]+$/.test(s) && s.length > 10) return s;
  try {
    const u = new URL(s);
    const code = u.searchParams.get("code");
    if (code) return code;
  } catch {
    // ignore
  }
  const m = /\bcode=([^&\s]+)/.exec(s);
  return m ? decodeURIComponent(m[1]) : "";
}

async function runAuthCodeFlowCopyPaste() {
  requireClientId();
  ensureTokenDir();

  process.stderr.write("\nGOOGLE CALENDAR AUTH\n");
  process.stderr.write("1) Open this URL in your browser:\n" + _authUrl() + "\n\n");
  process.stderr.write(
    "2) Complete consent, then copy either the full redirect URL (http://127.0.0.1:53682/oauth2callback?code=...) or the `code` value.\n\n"
  );
  process.stderr.write("Paste here and press Enter:\n");

  const input = await new Promise((resolve) => {
    let buf = "";
    process.stdin.setEncoding("utf8");
    process.stdin.on("data", (chunk) => {
      buf += String(chunk);
      if (buf.includes("\n")) {
        resolve(buf.trim());
      }
    });
  });

  const code = _extractCodeFromUserInput(input);
  if (!code) {
    throw new Error("missing_auth_code");
  }

  const tok = await httpForm(GOOGLE_TOKEN_URL, {
    code,
    client_id: CLIENT_ID,
    client_secret: CLIENT_SECRET || undefined,
    redirect_uri: REDIRECT_URI,
    grant_type: "authorization_code",
  });

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
}

async function calendarRequest(method, pathname, bodyObj, query) {
  const token = await getValidAccessToken();
  const url = new URL(GOOGLE_CALENDAR_API_BASE + pathname);
  for (const [k, v] of Object.entries(query || {})) {
    if (v === undefined || v === null) continue;
    url.searchParams.set(k, String(v));
  }

  const headers = {
    authorization: "Bearer " + String(token),
    accept: "application/json",
  };
  let body = undefined;
  if (bodyObj !== undefined) {
    headers["content-type"] = "application/json";
    body = JSON.stringify(bodyObj || {});
  }

  const r = await fetch(url.toString(), {
    method,
    headers,
    body,
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

async function listCalendars() {
  return await calendarRequest("GET", "/users/me/calendarList", undefined, { maxResults: 250 });
}

async function findJarvisCalendar() {
  const data = await listCalendars();
  const items = Array.isArray(data.items) ? data.items : [];
  const name = JARVIS_CALENDAR_NAME;
  for (const it of items) {
    if (!it || typeof it !== "object") continue;
    const summary = typeof it.summary === "string" ? it.summary : "";
    if (summary.trim() === name) {
      const id = typeof it.id === "string" ? it.id : "";
      if (id) return { ok: true, calendar_id: id, created: false, item: it };
    }
  }
  return { ok: true, calendar_id: "", created: false, item: null };
}

async function ensureJarvisCalendar() {
  const found = await findJarvisCalendar();
  if (found.calendar_id) return found;

  const created = await calendarRequest("POST", "/calendars", { summary: JARVIS_CALENDAR_NAME });
  const cid = created && typeof created.id === "string" ? created.id : "";
  if (!cid) {
    const e = new Error("calendar_create_failed");
    e.details = created;
    throw e;
  }
  return { ok: true, calendar_id: cid, created: true, item: created };
}

const TOOLS = [
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
  {
    name: "google_calendar_ensure_jarvis_calendar",
    description: "Find or create the dedicated Jarvis Reminders calendar.",
    inputSchema: { type: "object", properties: {} },
  },
  {
    name: "google_calendar_list_events",
    description: "List events in the Jarvis Reminders calendar.",
    inputSchema: {
      type: "object",
      properties: {
        time_min: { type: "string", description: "RFC3339 inclusive lower bound (optional)." },
        time_max: { type: "string", description: "RFC3339 exclusive upper bound (optional)." },
        q: { type: "string", description: "Free text search (optional)." },
        max_results: { type: "integer", description: "Max results (1-250)." },
        single_events: { type: "boolean", description: "Expand recurring events into instances." },
        order_by: { type: "string", description: "Order by (startTime|updated)." },
      },
    },
  },
  {
    name: "google_calendar_create_event",
    description: "Create an event in the Jarvis Reminders calendar (supports recurrence + reminders).",
    inputSchema: {
      type: "object",
      properties: {
        summary: { type: "string", description: "Event summary/title." },
        description: { type: "string", description: "Optional description." },
        start: { type: "string", description: "RFC3339 start datetime (or YYYY-MM-DD for all-day)." },
        end: { type: "string", description: "RFC3339 end datetime (or YYYY-MM-DD for all-day)." },
        timezone: { type: "string", description: "IANA timezone (e.g. Asia/Bangkok)." },
        reminders_minutes: { type: "array", items: { type: "integer" }, description: "Popup reminder offsets in minutes." },
        rrule: { type: "string", description: "Optional RRULE string (without 'RRULE:')." },
      },
      required: ["summary", "start", "end"],
    },
  },
  {
    name: "google_calendar_update_event",
    description: "Update an event in the Jarvis Reminders calendar.",
    inputSchema: {
      type: "object",
      properties: {
        event_id: { type: "string", description: "Event ID." },
        summary: { type: "string", description: "Optional new summary/title." },
        description: { type: "string", description: "Optional new description." },
        start: { type: "string", description: "Optional new start (RFC3339 or YYYY-MM-DD)." },
        end: { type: "string", description: "Optional new end (RFC3339 or YYYY-MM-DD)." },
        timezone: { type: "string", description: "IANA timezone (optional)." },
        reminders_minutes: { type: "array", items: { type: "integer" }, description: "Optional new popup reminder offsets in minutes." },
        rrule: { type: "string", description: "Optional RRULE string (without 'RRULE:')." },
      },
      required: ["event_id"],
    },
  },
  {
    name: "google_calendar_delete_event",
    description: "Delete an event in the Jarvis Reminders calendar.",
    inputSchema: {
      type: "object",
      properties: {
        event_id: { type: "string", description: "Event ID." },
      },
      required: ["event_id"],
    },
  },
];

function _toEventTime(raw, tz) {
  const s = typeof raw === "string" ? raw.trim() : "";
  if (!s) return null;
  // all-day date
  if (/^\d{4}-\d{2}-\d{2}$/.test(s)) {
    return { date: s };
  }
  const out = { dateTime: s };
  if (tz && typeof tz === "string" && tz.trim()) {
    out.timeZone = tz.trim();
  }
  return out;
}

function _buildReminders(remindersMinutes) {
  if (!Array.isArray(remindersMinutes) || remindersMinutes.length === 0) return undefined;
  const overrides = [];
  for (const m of remindersMinutes) {
    const n = Number(m);
    if (!Number.isFinite(n)) continue;
    overrides.push({ method: "popup", minutes: Math.max(0, Math.floor(n)) });
  }
  if (!overrides.length) return undefined;
  return { useDefault: false, overrides };
}

async function handleRpc(msg) {
  const jsonrpc = msg && msg.jsonrpc;
  const id = msg && Object.prototype.hasOwnProperty.call(msg, "id") ? msg.id : null;
  const method = msg && msg.method;
  const params = (msg && msg.params) || {};

  // Ignore notifications.
  const hasId = msg && Object.prototype.hasOwnProperty.call(msg, "id");
  if (!hasId) return null;

  if (method === "initialize") {
    const pv = params && typeof params.protocolVersion === "string" ? params.protocolVersion : "2024-11-05";
    return {
      jsonrpc: "2.0",
      id,
      result: {
        protocolVersion: pv,
        capabilities: { tools: {}, resources: {}, prompts: {} },
        serverInfo: { name: APP_NAME, version: APP_VERSION },
      },
    };
  }

  if (method === "initialized") {
    return null;
  }

  if (method === "resources/list") {
    return { jsonrpc: "2.0", id, result: { resources: [] } };
  }

  if (method === "prompts/list") {
    return { jsonrpc: "2.0", id, result: { prompts: [] } };
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
        redirect_uri: REDIRECT_URI,
        jarvis_calendar_name: JARVIS_CALENDAR_NAME,
        auth_hint: "Run: node /app/mcp-servers/mcp-google-calendar/server.js auth",
      };

      if (includeRaw) out.raw_tokens = tokens;

      return {
        jsonrpc: "2.0",
        id,
        result: { content: [{ type: "text", text: JSON.stringify(out) }] },
      };
    }

    if (name === "google_calendar_ensure_jarvis_calendar") {
      const out = await ensureJarvisCalendar();
      return {
        jsonrpc: "2.0",
        id,
        result: { content: [{ type: "text", text: JSON.stringify(out) }] },
      };
    }

    if (name === "google_calendar_list_events") {
      const ensured = await ensureJarvisCalendar();
      const calendarId = ensured.calendar_id;

      const max_raw = args.max_results;
      const maxResults =
        typeof max_raw === "number" && Number.isFinite(max_raw) ? Math.max(1, Math.min(250, Math.floor(max_raw))) : undefined;

      const timeMin = typeof args.time_min === "string" && args.time_min.trim() ? args.time_min.trim() : undefined;
      const timeMax = typeof args.time_max === "string" && args.time_max.trim() ? args.time_max.trim() : undefined;
      const q = typeof args.q === "string" && args.q.trim() ? args.q.trim() : undefined;
      const singleEvents = typeof args.single_events === "boolean" ? args.single_events : true;
      const orderByRaw = typeof args.order_by === "string" ? args.order_by.trim() : "";
      const orderBy = orderByRaw === "updated" ? "updated" : "startTime";

      const data = await calendarRequest(
        "GET",
        "/calendars/" + encodeURIComponent(calendarId) + "/events",
        undefined,
        {
          maxResults,
          timeMin,
          timeMax,
          q,
          singleEvents,
          orderBy,
        }
      );

      return {
        jsonrpc: "2.0",
        id,
        result: { content: [{ type: "text", text: JSON.stringify({ ok: true, calendar_id: calendarId, data }) }] },
      };
    }

    if (name === "google_calendar_create_event") {
      const ensured = await ensureJarvisCalendar();
      const calendarId = ensured.calendar_id;

      const summary = typeof args.summary === "string" ? args.summary.trim() : "";
      if (!summary) {
        return { jsonrpc: "2.0", id, error: { code: -32602, message: "Invalid params", data: { field: "summary" } } };
      }

      const tz = typeof args.timezone === "string" ? args.timezone.trim() : "";
      const start = _toEventTime(args.start, tz);
      const end = _toEventTime(args.end, tz);
      if (!start || !end) {
        return { jsonrpc: "2.0", id, error: { code: -32602, message: "Invalid params", data: { field: "start/end" } } };
      }

      const body = {
        summary,
        start,
        end,
      };
      if (typeof args.description === "string" && args.description.trim()) body.description = args.description;

      const reminders = _buildReminders(args.reminders_minutes);
      if (reminders) body.reminders = reminders;

      const rrule = typeof args.rrule === "string" ? args.rrule.trim() : "";
      if (rrule) body.recurrence = [rrule.startsWith("RRULE:") ? rrule : "RRULE:" + rrule];

      body.extendedProperties = { private: { jarvis_managed: "true" } };

      const data = await calendarRequest(
        "POST",
        "/calendars/" + encodeURIComponent(calendarId) + "/events",
        body,
        { sendUpdates: "none" }
      );

      return {
        jsonrpc: "2.0",
        id,
        result: { content: [{ type: "text", text: JSON.stringify({ ok: true, calendar_id: calendarId, data }) }] },
      };
    }

    if (name === "google_calendar_update_event") {
      const ensured = await ensureJarvisCalendar();
      const calendarId = ensured.calendar_id;

      const eventId = typeof args.event_id === "string" ? args.event_id.trim() : "";
      if (!eventId) {
        return { jsonrpc: "2.0", id, error: { code: -32602, message: "Invalid params", data: { field: "event_id" } } };
      }

      const existing = await calendarRequest(
        "GET",
        "/calendars/" + encodeURIComponent(calendarId) + "/events/" + encodeURIComponent(eventId)
      );

      const body = { ...existing };

      if (typeof args.summary === "string") body.summary = args.summary;
      if (typeof args.description === "string") body.description = args.description;

      const tz = typeof args.timezone === "string" ? args.timezone.trim() : "";
      const start = args.start !== undefined ? _toEventTime(args.start, tz) : null;
      const end = args.end !== undefined ? _toEventTime(args.end, tz) : null;
      if (start) body.start = start;
      if (end) body.end = end;

      if (args.reminders_minutes !== undefined) {
        const reminders = _buildReminders(args.reminders_minutes);
        if (reminders) body.reminders = reminders;
        else body.reminders = { useDefault: true };
      }

      if (args.rrule !== undefined) {
        const rrule = typeof args.rrule === "string" ? args.rrule.trim() : "";
        if (rrule) body.recurrence = [rrule.startsWith("RRULE:") ? rrule : "RRULE:" + rrule];
        else body.recurrence = [];
      }

      body.extendedProperties = body.extendedProperties || {};
      body.extendedProperties.private = body.extendedProperties.private || {};
      body.extendedProperties.private.jarvis_managed = "true";

      const data = await calendarRequest(
        "PUT",
        "/calendars/" + encodeURIComponent(calendarId) + "/events/" + encodeURIComponent(eventId),
        body,
        { sendUpdates: "none" }
      );

      return {
        jsonrpc: "2.0",
        id,
        result: { content: [{ type: "text", text: JSON.stringify({ ok: true, calendar_id: calendarId, event_id: eventId, data }) }] },
      };
    }

    if (name === "google_calendar_delete_event") {
      const ensured = await ensureJarvisCalendar();
      const calendarId = ensured.calendar_id;

      const eventId = typeof args.event_id === "string" ? args.event_id.trim() : "";
      if (!eventId) {
        return { jsonrpc: "2.0", id, error: { code: -32602, message: "Invalid params", data: { field: "event_id" } } };
      }

      const data = await calendarRequest(
        "DELETE",
        "/calendars/" + encodeURIComponent(calendarId) + "/events/" + encodeURIComponent(eventId)
      );

      return {
        jsonrpc: "2.0",
        id,
        result: { content: [{ type: "text", text: JSON.stringify({ ok: true, calendar_id: calendarId, event_id: eventId, data }) }] },
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
      data: { method, jsonrpc },
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
      process.stderr.write("mcp-google-calendar error details: " + JSON.stringify(e.details) + "\n");
    }
  } catch {}
  process.stderr.write("mcp-google-calendar startup error: " + String(e && e.message ? e.message : e) + "\n");
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
    if (res) write(res);
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

process.stdin.on("end", () => process.exit(0));
