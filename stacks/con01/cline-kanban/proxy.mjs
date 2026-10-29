import http from "node:http";
import {
  getExternalRequestRejection,
  rewriteDownstreamHeaders,
  rewriteUpstreamHeaders,
} from "./proxy-policy.mjs";
import { verifyCloudflareAccessJwt } from "./access-jwt.mjs";

const TAILNET_HOST = "100.72.146.39:3484";
const TAILNET_ORIGIN = "http://100.72.146.39:3484";
const PUBLIC_HOST = process.env.CLINE_PUBLIC_HOST?.trim().toLowerCase() || "";
const PUBLIC_ORIGIN = process.env.CLINE_PUBLIC_ORIGIN?.trim() || "";
const ACCESS_ISSUER = process.env.CLINE_CF_ACCESS_ISSUER?.trim() || "";
const ACCESS_AUDIENCE = process.env.CLINE_CF_ACCESS_AUD?.trim() || "";
const ACCESS_JWKS_URL = process.env.CLINE_CF_ACCESS_JWKS_URL?.trim() || "";
const PUBLIC_ACCESS_ENABLED = Boolean(
  PUBLIC_HOST && PUBLIC_ORIGIN && ACCESS_ISSUER && ACCESS_AUDIENCE && ACCESS_JWKS_URL,
);
const BACKEND_HOST = "cline-kanban";
const BACKEND_PORT = 3485;
const PASSCODE = process.env.CLINE_PROXY_PASSCODE?.trim();
if (!PASSCODE || PASSCODE.length < 24) {
  throw new Error("CLINE_PROXY_PASSCODE is missing or too short");
}
if (PUBLIC_HOST && !PUBLIC_ACCESS_ENABLED) {
  console.error("Cline public route disabled: Cloudflare Access verification is incomplete");
}

const authFailures = new Map();

async function requestRejection(req, upgrade = false) {
  const ip = req.socket.remoteAddress || "unknown";
  const now = Date.now();
  const state = authFailures.get(ip);
  if (state?.lockedUntil > now) return "auth";

  const host = String(req.headers.host || "").toLowerCase();
  const isPublic = PUBLIC_ACCESS_ENABLED && host === PUBLIC_HOST;
  const accessJwtValid = isPublic
    ? await verifyCloudflareAccessJwt(
        req.headers["cf-access-jwt-assertion"],
        {
          issuer: ACCESS_ISSUER,
          audience: ACCESS_AUDIENCE,
          jwksUrl: ACCESS_JWKS_URL,
        },
      )
    : false;
  const reason = getExternalRequestRejection(req.headers, req.method, {
    externalHost: TAILNET_HOST,
    externalOrigin: TAILNET_ORIGIN,
    publicHost: PUBLIC_ACCESS_ENABLED ? PUBLIC_HOST : "",
    publicOrigin: PUBLIC_ORIGIN,
    passcode: PASSCODE,
    accessJwtValid,
    upgrade,
  });
  if (reason === "auth") {
    const current = state && now - state.windowStart < 60_000
      ? state
      : { attempts: 0, windowStart: now, lockedUntil: 0 };
    current.attempts += 1;
    if (current.attempts >= 5) current.lockedUntil = now + 30_000;
    authFailures.set(ip, current);
  } else if (reason === null) {
    authFailures.delete(ip);
  }
  return reason;
}

function responseOrigin(req) {
  return PUBLIC_ACCESS_ENABLED &&
      String(req.headers.host || "").toLowerCase() === PUBLIC_HOST
    ? PUBLIC_ORIGIN
    : TAILNET_ORIGIN;
}

function rejectHttp(res, reason) {
  const unauthorized = reason === "auth";
  const message = unauthorized
    ? "Authentication required."
    : reason === "access"
      ? "Cloudflare Access authentication required."
      : "Host or Origin not allowed.";
  res.writeHead(unauthorized ? 401 : 403, {
    "Content-Type": "application/json; charset=utf-8",
    "Cache-Control": "no-store",
    ...(unauthorized
      ? { "WWW-Authenticate": 'Basic realm="Cline Kanban pilot", charset="UTF-8"' }
      : {}),
  });
  res.end(
    JSON.stringify({
      error: message,
    }),
  );
}

function rejectSocket(socket, reason) {
  const unauthorized = reason === "auth";
  const status = unauthorized ? 401 : 403;
  const message = unauthorized ? "Unauthorized" : "Forbidden";
  socket.end(
    `HTTP/1.1 ${status} ${message}\r\n` +
      "Connection: close\r\nCache-Control: no-store\r\n" +
      (unauthorized
        ? 'WWW-Authenticate: Basic realm="Cline Kanban pilot", charset="UTF-8"\r\n'
        : "") +
      "\r\n",
  );
}

function sendBadGateway(res) {
  if (res.headersSent) {
    res.destroy();
    return;
  }
  res.writeHead(502, {
    "Content-Type": "application/json; charset=utf-8",
    "Cache-Control": "no-store",
  });
  res.end(JSON.stringify({ error: "Cline Kanban backend unavailable." }));
}

async function proxyHttp(req, res) {
  const rejection = await requestRejection(req);
  if (rejection) {
    rejectHttp(res, rejection);
    return;
  }
  const externalOrigin = responseOrigin(req);

  const upstream = http.request(
    {
      host: BACKEND_HOST,
      port: BACKEND_PORT,
      path: req.url,
      method: req.method,
      headers: rewriteUpstreamHeaders(req.headers),
    },
    (upstreamRes) => {
      res.writeHead(
        upstreamRes.statusCode || 502,
        rewriteDownstreamHeaders(upstreamRes.headers, externalOrigin),
      );
      upstreamRes.pipe(res);
    },
  );

  upstream.on("error", () => sendBadGateway(res));
  req.pipe(upstream);
}

async function proxyUpgrade(req, clientSocket, head) {
  const rejection = await requestRejection(req, true);
  if (rejection) {
    rejectSocket(clientSocket, rejection);
    return;
  }

  const upstream = http.request({
    host: BACKEND_HOST,
    port: BACKEND_PORT,
    path: req.url,
    method: req.method,
    headers: rewriteUpstreamHeaders(req.headers),
  });

  upstream.on("upgrade", (upstreamRes, upstreamSocket, upstreamHead) => {
    const lines = [
      `HTTP/1.1 ${upstreamRes.statusCode} ${upstreamRes.statusMessage}`,
    ];
    for (let i = 0; i < upstreamRes.rawHeaders.length; i += 2) {
      lines.push(`${upstreamRes.rawHeaders[i]}: ${upstreamRes.rawHeaders[i + 1]}`);
    }
    clientSocket.write(`${lines.join("\r\n")}\r\n\r\n`);
    if (upstreamHead.length) clientSocket.write(upstreamHead);
    if (head.length) upstreamSocket.write(head);
    upstreamSocket.pipe(clientSocket);
    clientSocket.pipe(upstreamSocket);
  });

  upstream.on("response", (upstreamRes) => {
    upstreamRes.resume();
    clientSocket.end(
      `HTTP/1.1 ${upstreamRes.statusCode} ${upstreamRes.statusMessage}\r\nConnection: close\r\n\r\n`,
    );
  });
  upstream.on("error", () => rejectSocket(clientSocket));
  upstream.end();
}

const server = http.createServer((req, res) => {
  void proxyHttp(req, res).catch(() => sendBadGateway(res));
});

server.on("upgrade", (req, clientSocket, head) => {
  void proxyUpgrade(req, clientSocket, head).catch(() =>
    rejectSocket(clientSocket, "access"),
  );
});

server.on("clientError", (_error, socket) => rejectSocket(socket, "host"));
server.on("error", (error) => {
  console.error("Cline Kanban proxy failed:", error.message);
  process.exitCode = 1;
});

server.listen(3484, "0.0.0.0", () => {
  const routes = [`Tailnet ${TAILNET_HOST}`];
  if (PUBLIC_ACCESS_ENABLED) routes.push(`Access ${PUBLIC_HOST}`);
  console.log(`Cline Kanban authenticated proxy listening: ${routes.join(", ")}`);
});

function shutdown() {
  server.close();
}

process.on("SIGINT", shutdown);
process.on("SIGTERM", shutdown);
