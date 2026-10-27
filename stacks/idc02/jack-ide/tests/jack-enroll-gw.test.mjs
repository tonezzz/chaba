// Tests for the jack-enroll gateway (server.mjs) against a stub upstream.
// Covers: one-time use, expiry, replay, re-registration revocation,
// unauthenticated denial, route boundary, cookie flags, WS gating,
// server-side credential injection, edge-header requirement, audit trail.
// Run: node --test stacks/idc02/jack-ide/tests/
import { test, before, after } from "node:test";
import assert from "node:assert/strict";
import http from "node:http";
import net from "node:net";
import { spawn } from "node:child_process";
import fs from "node:fs";
import os from "node:os";
import path from "node:path";
import { fileURLToPath } from "node:url";

const SERVER = path.join(
  path.dirname(fileURLToPath(import.meta.url)),
  "../enroll-gw/server.mjs"
);
const ADMIN = "test-admin-token-0123456789";
const UP_PW = "up-secret-pw";

// ---- stub upstream: records what the gateway forwards --------------------
let upstream, upstreamSeen = [], upstreamPort;
function startUpstream() {
  return new Promise((resolve) => {
    upstream = http.createServer((req, res) => {
      upstreamSeen.push({ url: req.url, headers: req.headers });
      if (req.url === "/global/health")
        return res.writeHead(200, { "content-type": "application/json" }).end('{"healthy":true}');
      if (req.url === "/ws-probe") {
        res.writeHead(200).end("ws-ok");
        return;
      }
      res.writeHead(200, { "content-type": "text/html" }).end("<html>SPA</html>");
    });
    upstream.on("upgrade", (req, sock) => {
      upstreamSeen.push({ url: req.url, upgrade: true, headers: req.headers });
      sock.write(
        "HTTP/1.1 101 Switching Protocols\r\nUpgrade: websocket\r\nConnection: Upgrade\r\n\r\nUPSTREAM-TUNNELED"
      );
    });
    upstream.listen(0, "127.0.0.1", () => {
      upstreamPort = upstream.address().port;
      resolve();
    });
  });
}

// ---- gateway under test ---------------------------------------------------
let gw, gwPort, stateDir;
const ENV = {
  LISTEN_PORT: "0", // patched after listen? child can't report port — use fixed high port
};
function startGw(extra = {}) {
  gwPort = 18000 + Math.floor(Math.random() * 2000);
  stateDir = fs.mkdtempSync(path.join(os.tmpdir(), "jack-enroll-"));
  return new Promise((resolve, reject) => {
    gw = spawn("node", [SERVER], {
      env: {
        ...process.env,
        LISTEN_PORT: String(gwPort),
        UPSTREAM_URL: `http://127.0.0.1:${upstreamPort}`,
        JACK_UPSTREAM_PASSWORD: UP_PW,
        JACK_ADMIN_TOKEN: ADMIN,
        STATE_DIR: stateDir,
        CODE_TTL_S: "900",
        SESSION_TTL_S: "3600",
        REQUIRE_EDGE_HEADER: "0",
        COOKIE_SECURE: "1",
        ...extra,
      },
    });
    gw.stderr.on("data", (d) => process.stderr.write("[gw] " + d));
    const t = setInterval(async () => {
      try {
        const r = await fetch(`http://127.0.0.1:${gwPort}/health`);
        if (r.ok) { clearInterval(t); resolve(); }
      } catch {}
    }, 80);
    setTimeout(() => { clearInterval(t); reject(new Error("gw did not start")); }, 8000);
  });
}

const api = (p, opts = {}) => fetch(`http://127.0.0.1:${gwPort}${p}`, { redirect: "manual", ...opts });
const mint = async (body = {}) =>
  (await api("/admin/codes", {
    method: "POST",
    headers: { "x-admin-token": ADMIN, "content-type": "application/json" },
    body: JSON.stringify(body),
  })).json();
const enroll = async (code, headers = {}) =>
  api("/enroll", {
    method: "POST",
    headers: { "content-type": "application/json", ...headers },
    body: JSON.stringify({ code }),
  });
const cookieOf = (r) => {
  const c = r.headers.get("set-cookie") || "";
  return c.split(";")[0];
};

before(async () => { await startUpstream(); await startGw(); });
after(() => { gw?.kill(); upstream?.close(); fs.rmSync(stateDir, { recursive: true, force: true }); });

test("health is open and reports upstream", async () => {
  const r = await api("/health");
  assert.equal(r.status, 200);
  const d = await r.json();
  assert.equal(d.ok, true);
  assert.equal(d.upstream, "up");
});

test("enroll page renders, contains no secrets", async () => {
  const r = await api("/enroll");
  const html = await r.text();
  assert.equal(r.status, 200);
  assert.match(html, /enroll/i);
  assert.ok(!html.includes(ADMIN) && !html.includes(UP_PW) && !html.includes("LITELLM"));
});

test("unauthenticated proxy request is denied (401 api / 303 html)", async () => {
  const r1 = await api("/global/config");
  assert.equal(r1.status, 401);
  const r2 = await api("/", { headers: { accept: "text/html" } });
  assert.equal(r2.status, 303);
  assert.match(r2.headers.get("location"), /^\/enroll\?e=session_required/);
});

test("admin routes require token", async () => {
  for (const p of ["/admin/status", "/admin/audit"]) {
    assert.equal((await api(p)).status, 401);
  }
  assert.equal(
    (await api("/admin/codes", { method: "POST", headers: { "content-type": "application/json" }, body: "{}" })).status,
    401
  );
});

test("invalid code rejected; forged code rejected", async () => {
  assert.equal((await enroll("JCK-0000-0000-0000-0000")).status, 401);
  assert.equal((await enroll("../../../../etc/passwd")).status, 401);
});

test("enroll: valid code -> 303 + scoped cookie flags; one-time use", async () => {
  const m = await mint();
  assert.match(m.code, /^JCK-/);
  const r = await enroll(m.code);
  assert.equal(r.status, 303);
  assert.equal(r.headers.get("location"), "/");
  const sc = r.headers.get("set-cookie");
  assert.match(sc, /jack_ide_sess=/);
  assert.match(sc, /HttpOnly/);
  assert.match(sc, /SameSite=Lax/);
  assert.match(sc, /Secure/);
  assert.match(sc, /Path=\//);
  // replay — same code burned
  const r2 = await enroll(m.code);
  assert.equal(r2.status, 410);
  assert.equal((await r2.json()).error, "code_used");
  // session works on the OpenCode route
  const r3 = await api("/", { headers: { cookie: cookieOf(r), accept: "text/html" } });
  assert.equal(r3.status, 200);
  assert.match(await r3.text(), /SPA/);
});

test("redeem URL path also enrolls (VCAST-style deep link)", async () => {
  const m = await mint({ exclusive: false });
  const r = await api(m.redeem_path, { headers: { accept: "text/html" } });
  assert.equal(r.status, 303);
  assert.match(r.headers.get("set-cookie"), /jack_ide_sess=/);
});

test("pasted full redeem URL is accepted", async () => {
  const m = await mint({ exclusive: false });
  const r = await enroll(`https://idc02.taila0626a.ts.net:8448${m.redeem_path}`);
  assert.equal(r.status, 303);
});

test("short TTLs: expired code and expired session are rejected", async () => {
  // dedicated gateway instance with 1s TTLs (mint floor is 30s, so drive
  // expiry through the state file's own clock: ttl_s=30 then edit is fragile;
  // instead use CODE_TTL_S=2 default and wait it out).
  const port2 = 18000 + Math.floor(Math.random() * 2000);
  const dir2 = fs.mkdtempSync(path.join(os.tmpdir(), "jack-enroll-ttl-"));
  const gw2 = spawn("node", [SERVER], {
    env: {
      ...process.env,
      LISTEN_PORT: String(port2),
      UPSTREAM_URL: `http://127.0.0.1:${upstreamPort}`,
      JACK_UPSTREAM_PASSWORD: UP_PW,
      JACK_ADMIN_TOKEN: ADMIN,
      STATE_DIR: dir2,
      CODE_TTL_S: "2",
      SESSION_TTL_S: "2",
    },
  });
  try {
    await new Promise((res, rej) => {
      const t = setInterval(async () => {
        try { if ((await fetch(`http://127.0.0.1:${port2}/health`)).ok) { clearInterval(t); res(); } } catch {}
      }, 80);
      setTimeout(() => rej(new Error("gw2 no start")), 8000);
    });
    const api2 = (p, o = {}) => fetch(`http://127.0.0.1:${port2}${p}`, { redirect: "manual", ...o });
    const mint2 = async (b = {}) =>
      (await api2("/admin/codes", {
        method: "POST",
        headers: { "x-admin-token": ADMIN, "content-type": "application/json" },
        body: JSON.stringify(b),
      })).json();

    // expired code -> 410 code_expired
    const m = await mint2();
    await new Promise((r) => setTimeout(r, 2100));
    const r1 = await api2("/enroll", {
      method: "POST",
      headers: { "content-type": "application/json" },
      body: JSON.stringify({ code: m.code }),
    });
    assert.equal(r1.status, 410);
    assert.equal((await r1.json()).error, "code_expired");

    // expired session -> 401
    const m2 = await mint2({ exclusive: false });
    const r2 = await api2("/enroll", {
      method: "POST",
      headers: { "content-type": "application/json" },
      body: JSON.stringify({ code: m2.code }),
    });
    const cookie = (r2.headers.get("set-cookie") || "").split(";")[0];
    assert.equal((await api2("/", { headers: { cookie } })).status, 200);
    await new Promise((r) => setTimeout(r, 2100));
    assert.equal((await api2("/", { headers: { cookie } })).status, 401);
  } finally {
    gw2.kill();
    fs.rmSync(dir2, { recursive: true, force: true });
  }
});

test("re-registration: new mint revokes prior session", async () => {
  const m1 = await mint();
  const r1 = await enroll(m1.code);
  const cookie = cookieOf(r1);
  assert.equal((await api("/", { headers: { cookie } })).status, 200);
  await mint(); // exclusive default -> re-registration
  const r2 = await api("/", { headers: { cookie } });
  assert.equal(r2.status, 401); // prior Jack session invalidated
});

test("revoke-all kills sessions; reset clears everything", async () => {
  const m = await mint();
  const cookie = cookieOf(await enroll(m.code));
  await api("/admin/revoke", {
    method: "POST",
    headers: { "x-admin-token": ADMIN, "content-type": "application/json" },
    body: '{"all":true}',
  });
  assert.equal((await api("/", { headers: { cookie } })).status, 401);
  const m2 = await mint({ exclusive: false });
  await api("/admin/reset", {
    method: "POST",
    headers: { "x-admin-token": ADMIN },
  });
  const st = await (await api("/admin/status", { headers: { "x-admin-token": ADMIN } })).json();
  assert.equal(st.sessions.length, 0);
  assert.equal(st.codes.length, 0);
  assert.equal((await enroll(m2.code)).status, 401);
});

test("logout revokes the session", async () => {
  const m = await mint();
  const cookie = cookieOf(await enroll(m.code));
  assert.equal((await api("/", { headers: { cookie } })).status, 200);
  const lo = await api("/logout", { headers: { cookie } });
  assert.equal(lo.status, 303);
  assert.equal((await api("/", { headers: { cookie } })).status, 401);
});

test("upstream gets server-side auth, never the session cookie or admin token", async () => {
  const m = await mint();
  const cookie = cookieOf(await enroll(m.code));
  upstreamSeen = [];
  await api("/config", { headers: { cookie, "x-admin-token": ADMIN } });
  const seen = upstreamSeen.find((s) => s.url === "/config");
  assert.equal(seen.headers.authorization, "Basic " + Buffer.from(`opencode:${UP_PW}`).toString("base64"));
  assert.equal(seen.headers.cookie, undefined);
  assert.equal(seen.headers["x-admin-token"], undefined);
});

test("response does not leak upstream credentials", async () => {
  const m = await mint();
  const r = await enroll(m.code);
  const cookie = cookieOf(r);
  assert.ok(!cookie.includes(UP_PW));
  const body = await (await api("/", { headers: { cookie } })).text();
  assert.ok(!body.includes(UP_PW) && !body.includes(ADMIN));
});

test("websocket upgrade denied without session, tunneled with session", async () => {
  const wsReq = (cookie) =>
    new Promise((resolve) => {
      const s = net.connect(gwPort, "127.0.0.1", () => {
        const cookieHdr = cookie ? `Cookie: ${cookie}\r\n` : "";
        s.write(
          `GET /ws-probe HTTP/1.1\r\nHost: x\r\nUpgrade: websocket\r\nConnection: Upgrade\r\n${cookieHdr}\r\n`
        );
      });
      let buf = "";
      s.on("data", (d) => { buf += d.toString(); if (buf.includes("\r\n\r\n") || buf.includes("TUNNELED")) { s.destroy(); resolve(buf); } });
      s.on("error", () => resolve(buf));
      setTimeout(() => { s.destroy(); resolve(buf); }, 3000);
    });
  const denied = await wsReq(null);
  assert.match(denied, /401/);
  const m = await mint();
  const cookie = cookieOf(await enroll(m.code));
  const ok = await wsReq(cookie);
  assert.match(ok, /101 Switching Protocols/);
  assert.match(ok, /UPSTREAM-TUNNELED/);
});

test("state file stores only hashes (no raw codes/sessions)", async () => {
  const m = await mint({ exclusive: false });
  await enroll(m.code);
  const raw = fs.readFileSync(path.join(stateDir, "state.json"), "utf8");
  assert.ok(!raw.includes(m.code)); // raw JCK- code never persisted
  assert.ok(!raw.includes(m.code.replaceAll("-", "")));
  assert.ok(!raw.includes("sk-"));
});

test("audit trail records the lifecycle", async () => {
  const r = await api("/admin/audit?n=500", { headers: { "x-admin-token": ADMIN } });
  const events = (await r.json()).lines.map((l) => l.ev);
  for (const ev of ["boot", "mint", "enroll_ok", "enroll_code_used", "revoke", "reset", "ws_open"])
    assert.ok(events.includes(ev), `missing audit event ${ev}`);
});
