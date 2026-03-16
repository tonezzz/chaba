"use strict";

const APP_NAME = "mcp-google-sheets";
const APP_VERSION = "0.0.1";

const GOOGLE_AUTH_URL = "https://accounts.google.com/o/oauth2/v2/auth";
const GOOGLE_TOKEN_URL = "https://oauth2.googleapis.com/token";
const GOOGLE_SHEETS_API_BASE = "https://sheets.googleapis.com/v4";

function _envOrEmpty(v) {
  const s = String(v || "").trim();
  // 1mcp config substitution can leave literal placeholders like "${GOOGLE_CLIENT_ID}".
  if (/^\$\{[^}]+\}$/.test(s)) return "";
  return s;
}

const DEFAULT_SHARED_TOKEN_PATH = "/root/.config/1mcp/google.tokens.json";
const TOKEN_PATH = (process.env.GOOGLE_SHEETS_TOKEN_PATH || DEFAULT_SHARED_TOKEN_PATH).trim();
const CLIENT_ID = _envOrEmpty(process.env.GOOGLE_SHEETS_CLIENT_ID) || _envOrEmpty(process.env.GOOGLE_CLIENT_ID);
const CLIENT_SECRET = _envOrEmpty(process.env.GOOGLE_SHEETS_CLIENT_SECRET) || _envOrEmpty(process.env.GOOGLE_CLIENT_SECRET);
const DEFAULT_SCOPES_SHARED = [
  "https://www.googleapis.com/auth/spreadsheets.readonly",
  "https://www.googleapis.com/auth/calendar",
  "https://www.googleapis.com/auth/tasks",
].join(" ");
const DEFAULT_SCOPES = TOKEN_PATH === DEFAULT_SHARED_TOKEN_PATH
  ? DEFAULT_SCOPES_SHARED
  : "https://www.googleapis.com/auth/spreadsheets.readonly";
const SCOPES = String(process.env.GOOGLE_SHEETS_SCOPES || DEFAULT_SCOPES)
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
  process.stdout.write(body + "\n");
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
    throw new Error("missing_google_sheets_client_id");
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

async function sheetsPutJson(pathname, query, bodyObj) {
  const token = await getValidAccessToken();
  const url = new URL(GOOGLE_SHEETS_API_BASE + pathname);
  for (const [k, v] of Object.entries(query || {})) {
    if (v === undefined || v === null) continue;
    url.searchParams.set(k, String(v));
  }

  const r = await fetch(url.toString(), {
    method: "PUT",
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

async function sheetsPostJson(pathname, query, bodyObj) {
  const token = await getValidAccessToken();
  const url = new URL(GOOGLE_SHEETS_API_BASE + pathname);
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
      hint: "Run: node /app/mcp-servers/mcp-google-sheets/server.js auth",
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
      hint: "Re-run auth: node /app/mcp-servers/mcp-google-sheets/server.js auth",
    };
    throw e;
  }

  const refreshed = await refreshAccessToken(refresh);
  const merged = { ...tokens, ...refreshed };
  writeTokens(merged);
  return merged.access_token;
}

async function sheetsGet(pathname, query) {
  const token = await getValidAccessToken();
  const url = new URL(GOOGLE_SHEETS_API_BASE + pathname);
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

  process.stderr.write("\n== Google Sheets OAuth (Auth Code) ==\n");
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
    name: "google_sheets_ping",
    description: "Ping the server.",
    inputSchema: {
      type: "object",
      properties: {
        message: { type: "string" },
      },
    },
  },
  {
    name: "google_sheets_add_sheet",
    description: "Create a new sheet tab in a spreadsheet (requires write OAuth scope).",
    inputSchema: {
      type: "object",
      properties: {
        spreadsheet_id: { type: "string", description: "Spreadsheet ID" },
        title: { type: "string", description: "New sheet title (tab name)" },
        index: { type: "integer", description: "Optional sheet index (0-based)" },
      },
      required: ["spreadsheet_id", "title"],
    },
  },
  {
    name: "google_sheets_auth_status",
    description: "Report whether OAuth tokens exist and whether access token is valid.",
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
    name: "google_sheets_values_get",
    description: "Read values from a spreadsheet range (requires OAuth tokens).",
    inputSchema: {
      type: "object",
      properties: {
        spreadsheet_id: { type: "string", description: "Spreadsheet ID" },
        range: { type: "string", description: "A1 range like Sheet1!A1:C10" },
        major_dimension: { type: "string", description: "ROWS or COLUMNS" },
        value_render_option: { type: "string", description: "FORMATTED_VALUE or UNFORMATTED_VALUE" },
        date_time_render_option: { type: "string", description: "SERIAL_NUMBER or FORMATTED_STRING" },
      },
      required: ["spreadsheet_id", "range"],
    },
  },
  {
    name: "google_sheets_get_spreadsheet",
    description: "Fetch spreadsheet metadata (sheet titles, ids) to help build valid ranges.",
    inputSchema: {
      type: "object",
      properties: {
        spreadsheet_id: { type: "string", description: "Spreadsheet ID" },
      },
      required: ["spreadsheet_id"],
    },
  },
  {
    name: "google_sheets_values_append",
    description: "Append rows to a spreadsheet range (requires write OAuth scope).",
    inputSchema: {
      type: "object",
      properties: {
        spreadsheet_id: { type: "string", description: "Spreadsheet ID" },
        range: { type: "string", description: "A1 range like Sheet1!A1:C" },
        values: {
          type: "array",
          description: "Rows to append (array of arrays).",
          items: { type: "array", items: {} },
        },
        value_input_option: { type: "string", description: "RAW or USER_ENTERED" },
        insert_data_option: { type: "string", description: "INSERT_ROWS or OVERWRITE" },
      },
      required: ["spreadsheet_id", "range", "values"],
    },
  },
  {
    name: "google_sheets_values_update",
    description: "Update values in a spreadsheet range (in-place) (requires write OAuth scope).",
    inputSchema: {
      type: "object",
      properties: {
        spreadsheet_id: { type: "string", description: "Spreadsheet ID" },
        range: { type: "string", description: "A1 range like Sheet1!A1:C10" },
        values: {
          type: "array",
          description: "2D array of values to write (array of arrays).",
          items: { type: "array", items: {} },
        },
        value_input_option: { type: "string", description: "RAW or USER_ENTERED" },
        major_dimension: { type: "string", description: "ROWS or COLUMNS" },
      },
      required: ["spreadsheet_id", "range", "values"],
    },
  },
];

async function handleRpc(msg) {
  const hasId = msg && Object.prototype.hasOwnProperty.call(msg, "id");
  const id = hasId ? msg.id : null;
  const method = msg && msg.method;
  const params = (msg && msg.params) || {};

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

  if (method === "initialized") {
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

    if (name === "google_sheets_ping") {
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

    if (name === "google_sheets_add_sheet") {
      const spreadsheetId = typeof args.spreadsheet_id === "string" ? args.spreadsheet_id.trim() : "";
      const title = typeof args.title === "string" ? args.title.trim() : "";
      if (!spreadsheetId) throw new Error("missing_spreadsheet_id");
      if (!title) throw new Error("missing_title");

      const index = Number.isFinite(args.index) ? Number(args.index) : null;
      const addSheet = {
        properties: {
          title,
        },
      };
      if (index !== null) {
        addSheet.properties.index = index;
      }

      const data = await sheetsPostJson(
        "/spreadsheets/" + encodeURIComponent(spreadsheetId) + ":batchUpdate",
        {},
        {
          requests: [{ addSheet }],
        }
      );

      return {
        jsonrpc: "2.0",
        id,
        result: {
          content: [{ type: "text", text: JSON.stringify({ ok: true, data }) }],
        },
      };
    }

    if (name === "google_sheets_values_append") {
      const spreadsheetId = typeof args.spreadsheet_id === "string" ? args.spreadsheet_id.trim() : "";
      const range = typeof args.range === "string" ? args.range.trim() : "";
      if (!spreadsheetId) throw new Error("missing_spreadsheet_id");
      if (!range) throw new Error("missing_range");

      const values = Array.isArray(args.values) ? args.values : null;
      if (!values || !values.length) throw new Error("missing_values");

      const valueInputOption = typeof args.value_input_option === "string" ? args.value_input_option.trim() : "";
      const insertDataOption = typeof args.insert_data_option === "string" ? args.insert_data_option.trim() : "";

      const data = await sheetsPostJson(
        "/spreadsheets/" + encodeURIComponent(spreadsheetId) + "/values/" + encodeURIComponent(range) + ":append",
        {
          valueInputOption: valueInputOption || "USER_ENTERED",
          insertDataOption: insertDataOption || "INSERT_ROWS",
        },
        {
          majorDimension: "ROWS",
          values,
        }
      );

      return {
        jsonrpc: "2.0",
        id,
        result: {
          content: [{ type: "text", text: JSON.stringify({ ok: true, data }) }],
        },
      };
    }

    if (name === "google_sheets_values_update") {
      const spreadsheetId = typeof args.spreadsheet_id === "string" ? args.spreadsheet_id.trim() : "";
      const range = typeof args.range === "string" ? args.range.trim() : "";
      if (!spreadsheetId) throw new Error("missing_spreadsheet_id");
      if (!range) throw new Error("missing_range");

      const values = Array.isArray(args.values) ? args.values : null;
      if (!values) throw new Error("missing_values");

      const valueInputOption = typeof args.value_input_option === "string" ? args.value_input_option.trim() : "";
      const majorDimension = typeof args.major_dimension === "string" ? args.major_dimension.trim() : "";

      const body = {
        values,
      };
      if (majorDimension) body.majorDimension = majorDimension;

      const data = await sheetsPutJson(
        "/spreadsheets/" + encodeURIComponent(spreadsheetId) + "/values/" + encodeURIComponent(range),
        {
          valueInputOption: valueInputOption || "USER_ENTERED",
        },
        body
      );

      return {
        jsonrpc: "2.0",
        id,
        result: {
          content: [{ type: "text", text: JSON.stringify({ ok: true, data }) }],
        },
      };
    }

    if (name === "google_sheets_auth_status") {
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
        auth_hint: "Run: node /app/mcp-servers/mcp-google-sheets/server.js auth",
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

    if (name === "google_sheets_values_get") {
      const spreadsheetId = typeof args.spreadsheet_id === "string" ? args.spreadsheet_id.trim() : "";
      const range = typeof args.range === "string" ? args.range.trim() : "";
      if (!spreadsheetId) throw new Error("missing_spreadsheet_id");
      if (!range) throw new Error("missing_range");

      const majorDimension = typeof args.major_dimension === "string" ? args.major_dimension.trim() : "";
      const valueRenderOption = typeof args.value_render_option === "string" ? args.value_render_option.trim() : "";
      const dateTimeRenderOption = typeof args.date_time_render_option === "string" ? args.date_time_render_option.trim() : "";

      const data = await sheetsGet(
        "/spreadsheets/" + encodeURIComponent(spreadsheetId) + "/values/" + encodeURIComponent(range),
        {
          majorDimension: majorDimension || undefined,
          valueRenderOption: valueRenderOption || undefined,
          dateTimeRenderOption: dateTimeRenderOption || undefined,
        }
      );

      return {
        jsonrpc: "2.0",
        id,
        result: {
          content: [{ type: "text", text: JSON.stringify({ ok: true, data }) }],
        },
      };
    }

    if (name === "google_sheets_get_spreadsheet") {
      const spreadsheetId = typeof args.spreadsheet_id === "string" ? args.spreadsheet_id.trim() : "";
      if (!spreadsheetId) throw new Error("missing_spreadsheet_id");

      const data = await sheetsGet(
        "/spreadsheets/" + encodeURIComponent(spreadsheetId),
        {
          fields: "spreadsheetId,properties.title,sheets.properties(sheetId,title,index)",
        }
      );

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

let buf = Buffer.alloc(0);
let lineBuf = "";

let _pending = Promise.resolve();
function _enqueueHandle(msg) {
  _pending = _pending
    .then(() => handleMessage(msg))
    .catch(() => {
      // keep draining
    });
}

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

  const start = headerEnd + headerSepLen;
  if (buffer.length < start + contentLength) return null;
  const bodyBuf = buffer.slice(start, start + contentLength);
  const rest = buffer.slice(start + contentLength);
  return { body: bodyBuf.toString("utf8"), rest };
}

async function handleMessage(msg) {
  try {
    const res = await handleRpc(msg);
    if (res) {
      write(res);
    }
  } catch (e) {
    let details = null;
    try {
      details = e && typeof e === "object" && e.details ? e.details : null;
    } catch {
      details = null;
    }
    write({
      jsonrpc: "2.0",
      id: msg && Object.prototype.hasOwnProperty.call(msg, "id") ? msg.id : null,
      error: {
        code: -32603,
        message: "Internal error",
        data: { error: String(e && e.message ? e.message : e), details },
      },
    });
  }
}

process.stdin.on("data", (chunk) => {
  const b = Buffer.isBuffer(chunk) ? chunk : Buffer.from(String(chunk), "utf8");
  buf = Buffer.concat([buf, b]);
  lineBuf += b.toString("utf8");

  while (true) {
    const parsed = parseNextFrame(buf);
    if (!parsed) break;
    const { body, rest } = parsed;
    buf = rest;
    const msg = safeJsonParse(body);
    if (!msg) {
      process.stderr.write("mcp-google-sheets parse error\n");
      continue;
    }
    _enqueueHandle(msg);
  }

  while (true) {
    const idx = lineBuf.indexOf("\n");
    if (idx < 0) break;
    const line = lineBuf.slice(0, idx).trim();
    lineBuf = lineBuf.slice(idx + 1);
    if (!line) continue;
    const msg = safeJsonParse(line);
    if (!msg) continue;
    _enqueueHandle(msg);
  }
});

process.stdin.on("end", () => {
  _pending.finally(() => process.exit(0));
});

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
      process.stderr.write("mcp-google-sheets error details: " + JSON.stringify(e.details) + "\n");
    }
  } catch {}
  process.stderr.write("mcp-google-sheets startup error: " + String(e && e.message ? e.message : e) + "\n");
  process.exit(1);
});
