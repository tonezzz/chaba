#!/usr/bin/env node
// jack-enroll — VCAST-style one-time enrollment + session proxy for the
// isolated Jack OpenCode Podman IDE.
//
// Model (mirrors the ada/vcast redeem flow, minus HA storage):
//   admin mints single-use code -> sha256 stored w/ expiry (never the raw)
//   POST /enroll or GET /redeem/<code> burns it, issues session cookie
//   (Secure/HttpOnly/SameSite) -> every other path is proxied to the
//   OpenCode upstream, upstream basic-auth injected server-side.
// Re-mint with exclusive=true (default) = re-registration: prior sessions
// and pending codes are revoked first. No LiteLLM/MCP/host creds ever
// reach the browser — the cookie is an opaque ticket.

import http from "node:http";
import net from "node:net";
import crypto from "node:crypto";
import fs from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";

const PORT = +(process.env.LISTEN_PORT || 8080);
const UPSTREAM = new URL(process.env.UPSTREAM_URL || "http://127.0.0.1:4096");
const UPSTREAM_USER = process.env.UPSTREAM_USER || "opencode";
const UPSTREAM_PASSWORD =
  process.env.UPSTREAM_PASSWORD || process.env.JACK_UPSTREAM_PASSWORD || "";
const ADMIN_TOKEN = process.env.JACK_ADMIN_TOKEN || "";
const STATE_DIR = process.env.STATE_DIR || "/tmp/jack-enroll-state";
const CODE_TTL_S = +(process.env.CODE_TTL_S || 900); // 15 min
const SESSION_TTL_S = +(process.env.SESSION_TTL_S || 43200); // 12 h
const COOKIE_NAME = process.env.COOKIE_NAME || "jack_ide_sess";
const COOKIE_SECURE = process.env.COOKIE_SECURE !== "0";
const REQUIRE_EDGE_HEADER = process.env.REQUIRE_EDGE_HEADER === "1";
const SCOPE = "jack-ide";

const STATE_FILE = path.join(STATE_DIR, "state.json");
const AUDIT_FILE = path.join(STATE_DIR, "audit.jsonl");
const ENROLL_HTML = fs.readFileSync(
  path.join(path.dirname(fileURLToPath(import.meta.url)), "enroll.html"),
  "utf8"
);

const sha256 = (s) => crypto.createHash("sha256").update(s).digest("hex");
const tok = (bytes = 24) => crypto.randomBytes(bytes).toString("base64url");
const nowS = () => Math.floor(Date.now() / 1000);

// ---- state ---------------------------------------------------------------
let state = { codes: {}, sessions: {} };
try {
  state = JSON.parse(fs.readFileSync(STATE_FILE, "utf8"));
} catch {}

function persist() {
  fs.mkdirSync(STATE_DIR, { recursive: true });
  const tmp = STATE_FILE + ".tmp";
  fs.writeFileSync(tmp, JSON.stringify(state));
  fs.renameSync(tmp, STATE_FILE);
}

function audit(ev, detail = {}) {
  fs.mkdirSync(STATE_DIR, { recursive: true });
  try {
    if (fs.existsSync(AUDIT_FILE) && fs.statSync(AUDIT_FILE).size > 1_000_000)
      fs.renameSync(AUDIT_FILE, AUDIT_FILE + ".1");
  } catch {}
  fs.appendFileSync(
    AUDIT_FILE,
    JSON.stringify({ at: new Date().toISOString(), ev, ...detail }) + "\n"
  );
}

function purgeExpired() {
  const t = nowS();
  for (const [h, c] of Object.entries(state.codes))
    if (c.expires <= t) delete state.codes[h];
  for (const [h, s] of Object.entries(state.sessions))
    if (s.expires <= t) delete state.sessions[h];
}
purgeExpired();
persist();
audit("boot", { scope: SCOPE });

// ---- helpers -------------------------------------------------------------
function humanCode() {
  // unambiguous alphabet, 4x4 groups — typeable, QR-safe in a redeem URL
  const abc = "23456789ABCDEFGHJKMNPQRSTUVWXYZ";
  const raw = [...crypto.randomBytes(16)].map((b) => abc[b % abc.length]).join("");
  return "JCK-" + raw.match(/.{4}/g).join("-");
}

// accept "JCK-XXXX-...", a bare token, or a pasted redeem URL
function normalizeCode(input) {
  if (!input) return "";
  let s = String(input).trim();
  try {
    const u = new URL(s);
    const m = u.pathname.match(/\/redeem\/([^/]+)/);
    if (m) s = m[1];
  } catch {}
  return s.replace(/[\s-]+/g, "").toUpperCase();
}

const codeHash = (raw) => sha256(normalizeCode(raw));

function parseCookies(req) {
  const out = {};
  for (const part of String(req.headers.cookie || "").split(";")) {
    const i = part.indexOf("=");
    if (i > 0) out[part.slice(0, i).trim()] = part.slice(i + 1).trim();
  }
  return out;
}

function sessionFor(req) {
  const raw = parseCookies(req)[COOKIE_NAME];
  if (!raw) return null;
  const s = state.sessions[sha256(raw)];
  if (!s) return null;
  if (s.expires <= nowS()) {
    delete state.sessions[sha256(raw)];
    persist();
    audit("session_expired", { sid: s.id });
    return null;
  }
  if (nowS() - (s.last_seen || 0) > 60) {
    s.last_seen = nowS();
    persist();
  }
  return s;
}

function cookieHeader(raw, maxAge) {
  let c = `${COOKIE_NAME}=${raw}; Path=/; HttpOnly; SameSite=Lax; Max-Age=${maxAge}`;
  if (COOKIE_SECURE) c += "; Secure";
  return c;
}

function send(res, code, body, headers = {}) {
  const isObj = typeof body === "object" && body !== null;
  const data = isObj ? JSON.stringify(body) : body;
  res.writeHead(code, {
    "content-type": isObj ? "application/json" : "text/plain; charset=utf-8",
    "cache-control": "no-store",
    ...headers,
  });
  res.end(data);
}

function wantsHtml(req) {
  return (req.method === "GET" || req.method === "HEAD") &&
    /text\/html/.test(req.headers.accept || "");
}

function edgeOk(req) {
  return !REQUIRE_EDGE_HEADER || !!req.headers["tailscale-user-login"];
}

function readBody(req, cap = 8192) {
  return new Promise((resolve, reject) => {
    let n = 0;
    const chunks = [];
    req.on("data", (c) => {
      n += c.length;
      if (n > cap) return reject(new Error("body too large"));
      chunks.push(c);
    });
    req.on("end", () => resolve(Buffer.concat(chunks).toString("utf8")));
    req.on("error", reject);
  });
}

function consumeCode(raw) {
  const h = codeHash(raw);
  const rec = state.codes[h];
  if (!rec) return { error: "invalid_code", status: 401 };
  if (rec.used) return { error: "code_used", status: 410, id: rec.id };
  if (rec.expires <= nowS()) {
    delete state.codes[h];
    persist();
    return { error: "code_expired", status: 410, id: rec.id };
  }
  rec.used = nowS();
  const sid = tok(9);
  const sessRaw = tok(24);
  state.sessions[sha256(sessRaw)] = {
    id: sid,
    scope: SCOPE,
    created: nowS(),
    expires: nowS() + SESSION_TTL_S,
    label: rec.label || "jack",
    last_seen: nowS(),
  };
  persist();
  return { sessRaw, sid, next: rec.next || "/" };
}

// ---- proxy ---------------------------------------------------------------
function proxyHttp(req, res, sess) {
  const headers = { ...req.headers };
  headers.host = UPSTREAM.host;
  headers.authorization =
    "Basic " + Buffer.from(`${UPSTREAM_USER}:${UPSTREAM_PASSWORD}`).toString("base64");
  // never leak session/admin material or edge identity upstream
  delete headers.cookie;
  delete headers["x-admin-token"];
  delete headers["tailscale-user-login"];
  delete headers["tailscale-user-name"];
  delete headers["tailscale-user-profile-pic"];
  headers["x-forwarded-for"] = req.socket.remoteAddress;
  headers["x-jack-session"] = sess.id;

  const preq = http.request(
    {
      host: UPSTREAM.hostname,
      port: UPSTREAM.port,
      path: req.url,
      method: req.method,
      headers,
      timeout: 0,
    },
    (pres) => {
      const rh = { ...pres.headers };
      delete rh["connection"];
      delete rh["keep-alive"];
      delete rh["transfer-encoding"];
      res.writeHead(pres.statusCode, rh);
      pres.pipe(res);
    }
  );
  preq.on("error", (e) => {
    audit("upstream_err", { sid: sess.id, err: e.code || "ERR" });
    if (!res.headersSent) send(res, 502, { error: "upstream_unreachable" });
    else res.destroy();
  });
  req.pipe(preq);
}

function proxyUpgrade(req, sock, head, sess) {
  const up = net.connect(+UPSTREAM.port, UPSTREAM.hostname, () => {
    const headers = { ...req.headers };
    headers.host = UPSTREAM.host;
    headers.authorization =
      "Basic " + Buffer.from(`${UPSTREAM_USER}:${UPSTREAM_PASSWORD}`).toString("base64");
    delete headers.cookie;
    delete headers["x-admin-token"];
    const lines = [`${req.method} ${req.url} HTTP/${req.httpVersion}`];
    for (const [k, v] of Object.entries(headers))
      lines.push(`${k}: ${Array.isArray(v) ? v.join(", ") : v}`);
    up.write(lines.join("\r\n") + "\r\n\r\n");
    if (head?.length) up.write(head);
    sock.pipe(up).pipe(sock);
  });
  up.on("error", () => {
    audit("upstream_ws_err", { sid: sess.id });
    sock.destroy();
  });
  audit("ws_open", { sid: sess.id, path: req.url });
}

// ---- routes --------------------------------------------------------------
const server = http.createServer(async (req, res) => {
  const u = new URL(req.url, "http://x");
  const p = u.pathname;
  const ip =
    String(req.headers["x-forwarded-for"] || "").split(",")[0].trim() ||
    req.socket.remoteAddress;

  try {
    if (p === "/health") {
      const up = await fetch(UPSTREAM.origin + "/global/health", {
        headers: {
          authorization:
            "Basic " +
            Buffer.from(`${UPSTREAM_USER}:${UPSTREAM_PASSWORD}`).toString("base64"),
        },
        signal: AbortSignal.timeout(3000),
      }).then((r) => (r.ok ? "up" : `bad:${r.status}`)).catch(() => "down");
      const t = nowS();
      return send(res, 200, {
        ok: true,
        scope: SCOPE,
        uptime_s: t - BOOT,
        sessions_active: Object.values(state.sessions).filter((s) => s.expires > t).length,
        codes_pending: Object.values(state.codes).filter((c) => !c.used && c.expires > t).length,
        upstream: up,
      });
    }

    if (p === "/enroll" && req.method === "GET") {
      if (!edgeOk(req)) return send(res, 403, { error: "edge_auth_required" });
      if (sessionFor(req))
        return send(res, 303, "", { location: "/" }); // already enrolled
      const html = ENROLL_HTML
        .replaceAll("{{ERR}}", u.searchParams.get("e") || "")
        .replaceAll("{{CODE}}", u.searchParams.get("code") || "");
      return send(res, 200, html, { "content-type": "text/html; charset=utf-8" });
    }

    if ((p === "/enroll" && req.method === "POST") || p.startsWith("/redeem/")) {
      if (!edgeOk(req)) return send(res, 403, { error: "edge_auth_required" });
      let raw = p.startsWith("/redeem/") ? decodeURIComponent(p.slice(8)) : "";
      if (req.method === "POST") {
        const body = await readBody(req).catch(() => "");
        const ct = req.headers["content-type"] || "";
        if (ct.includes("json")) raw = JSON.parse(body || "{}").code || "";
        else raw = new URLSearchParams(body).get("code") || "";
      }
      const r = consumeCode(raw);
      if (r.error) {
        audit("enroll_" + r.error, { ip, cid: r.id || codeHash(raw).slice(0, 12) });
        if (wantsHtml(req))
          return send(res, 303, "", { location: `/enroll?e=${r.error}` });
        return send(res, r.status, { error: r.error });
      }
      let next = u.searchParams.get("next") || r.next;
      if (!next.startsWith("/") || next.startsWith("//")) next = "/";
      audit("enroll_ok", { ip, sid: r.sid });
      return send(res, 303, "", {
        location: next,
        "set-cookie": cookieHeader(r.sessRaw, SESSION_TTL_S),
      });
    }

    if (p === "/logout") {
      const raw = parseCookies(req)[COOKIE_NAME];
      const s = raw && state.sessions[sha256(raw)];
      if (s) {
        delete state.sessions[sha256(raw)];
        persist();
        audit("logout", { sid: s.id });
      }
      return send(res, 303, "", {
        location: "/enroll",
        "set-cookie": cookieHeader("gone", 0),
      });
    }

    if (p.startsWith("/admin/")) {
      const given = req.headers["x-admin-token"] || "";
      const ok =
        ADMIN_TOKEN &&
        given.length === ADMIN_TOKEN.length &&
        crypto.timingSafeEqual(Buffer.from(given), Buffer.from(ADMIN_TOKEN));
      if (!ok) {
        audit("admin_denied", { ip, path: p });
        return send(res, 401, { error: "admin_token_required" });
      }
      return await admin(req, res, p, u);
    }

    // everything else: session-gated OpenCode route
    const sess = sessionFor(req);
    if (!sess) {
      if (wantsHtml(req)) {
        const next = encodeURIComponent(req.url);
        return send(res, 303, "", { location: `/enroll?e=session_required&next=${next}` });
      }
      return send(res, 401, { error: "session_required" });
    }
    if (!edgeOk(req)) return send(res, 403, { error: "edge_auth_required" });
    return proxyHttp(req, res, sess);
  } catch (e) {
    audit("error", { path: p, err: String(e).slice(0, 200) });
    if (!res.headersSent) send(res, 500, { error: "internal" });
    else res.destroy();
  }
});

async function admin(req, res, p, u) {
  if (req.method === "POST" && p === "/admin/codes") {
    const body = JSON.parse((await readBody(req).catch(() => "{}")) || "{}");
    const exclusive = body.exclusive !== false; // re-registration default
    if (exclusive) {
      for (const [h, c] of Object.entries(state.codes)) if (!c.used) delete state.codes[h];
      state.sessions = {};
    }
    const code = humanCode();
    const ttl = body.ttl_s
      ? Math.min(Math.max(+body.ttl_s, 30), 86400)
      : CODE_TTL_S;
    const id = tok(8);
    state.codes[codeHash(code)] = {
      id,
      created: nowS(),
      expires: nowS() + ttl,
      label: body.label || "jack",
      next: body.next || "/",
      used: 0,
    };
    persist();
    audit(exclusive ? "mint_reregister" : "mint", { cid: id, ttl });
    return send(res, 200, {
      code,
      redeem_path: `/redeem/${code}`,
      expires_in: ttl,
      code_id: id,
      exclusive,
    });
  }
  if (req.method === "POST" && p === "/admin/revoke") {
    const body = JSON.parse((await readBody(req).catch(() => "{}")) || "{}");
    let n = 0;
    if (body.all) {
      n = Object.keys(state.sessions).length;
      state.sessions = {};
    } else if (body.session_id) {
      for (const [h, s] of Object.entries(state.sessions))
        if (s.id === body.session_id) {
          delete state.sessions[h];
          n++;
        }
    }
    persist();
    audit("revoke", { n, sid: body.session_id || "all" });
    return send(res, 200, { revoked: n });
  }
  if (req.method === "POST" && p === "/admin/reset") {
    state = { codes: {}, sessions: {} };
    persist();
    audit("reset", {});
    return send(res, 200, { reset: true });
  }
  if (req.method === "GET" && p === "/admin/status") {
    const t = nowS();
    return send(res, 200, {
      sessions: Object.values(state.sessions).map((s) => ({
        id: s.id,
        created: s.created,
        expires: s.expires,
        ttl_left: Math.max(0, s.expires - t),
        last_seen: s.last_seen,
        label: s.label,
      })),
      codes: Object.values(state.codes).map((c) => ({
        id: c.id,
        created: c.created,
        expires: c.expires,
        ttl_left: Math.max(0, c.expires - t),
        used: !!c.used,
        label: c.label,
      })),
    });
  }
  if (req.method === "GET" && p === "/admin/audit") {
    const n = Math.min(+(u.searchParams.get("n") || 200), 2000);
    let lines = [];
    try {
      lines = fs.readFileSync(AUDIT_FILE, "utf8").trim().split("\n").slice(-n);
    } catch {}
    return send(res, 200, { lines: lines.map((l) => JSON.parse(l)) });
  }
  return send(res, 404, { error: "unknown_admin_route" });
}

server.on("upgrade", (req, sock, head) => {
  const sess = sessionFor(req);
  if (!sess || !edgeOk(req)) {
    audit("ws_denied", { path: req.url });
    sock.write("HTTP/1.1 401 Unauthorized\r\nConnection: close\r\n\r\n");
    return sock.destroy();
  }
  proxyUpgrade(req, sock, head, sess);
});

const BOOT = nowS();
server.requestTimeout = 0; // SSE/event streams stay open
server.listen(PORT, () => {
  console.log(`jack-enroll listening :${PORT} upstream=${UPSTREAM.origin} scope=${SCOPE}`);
});
