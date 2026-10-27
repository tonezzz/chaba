import http from "node:http";
import {
  getExternalRequestRejection,
  rewriteDownstreamHeaders,
  rewriteUpstreamHeaders,
} from "./proxy-policy.mjs";

const PUBLIC_HOST = "100.72.146.39:3484";
const BACKEND_HOST = "127.0.0.1";
const BACKEND_PORT = 3485;
const PASSCODE = process.env.CLINE_PROXY_PASSCODE?.trim();
if (!PASSCODE || PASSCODE.length < 24) {
  throw new Error("CLINE_PROXY_PASSCODE is missing or too short");
}

const authFailures = new Map();

function requestRejection(req, upgrade = false) {
  const ip = req.socket.remoteAddress || "unknown";
  const now = Date.now();
  const state = authFailures.get(ip);
  if (state?.lockedUntil > now) return "auth";
  const reason = getExternalRequestRejection(req.headers, req.method, {
    externalHost: PUBLIC_HOST,
    externalOrigin: "http://100.72.146.39:3484",
    passcode: PASSCODE,
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

function rejectHttp(res, reason) {
  const unauthorized = reason === "auth";
  res.writeHead(unauthorized ? 401 : 403, {
    "Content-Type": "application/json; charset=utf-8",
    "Cache-Control": "no-store",
    ...(unauthorized
      ? { "WWW-Authenticate": 'Basic realm="Cline Kanban pilot", charset="UTF-8"' }
      : {}),
  });
  res.end(
    JSON.stringify({
      error: unauthorized
        ? "Authentication required."
        : "Host or Origin not allowed.",
    }),
  );
}

function rejectSocket(socket, reason) {
  const unauthorized = reason === "auth";
  socket.end(
    `HTTP/1.1 ${unauthorized ? "401 Unauthorized" : "403 Forbidden"}\r\n` +
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

const server = http.createServer((req, res) => {
  const rejection = requestRejection(req);
  if (rejection) {
    rejectHttp(res, rejection);
    return;
  }

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
        rewriteDownstreamHeaders(upstreamRes.headers),
      );
      upstreamRes.pipe(res);
    },
  );

  upstream.on("error", () => sendBadGateway(res));
  req.pipe(upstream);
});

server.on("upgrade", (req, clientSocket, head) => {
  const rejection = requestRejection(req, true);
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
});

server.on("clientError", (_error, socket) => rejectSocket(socket, "host"));
server.on("error", (error) => {
  console.error("Cline Kanban proxy failed:", error.message);
  process.exitCode = 1;
});

server.listen(3484, "0.0.0.0", () => {
  console.log(`Cline Kanban authenticated proxy listening on ${PUBLIC_HOST}`);
});

function shutdown() {
  server.close();
}

process.on("SIGINT", shutdown);
process.on("SIGTERM", shutdown);
