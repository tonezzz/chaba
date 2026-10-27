import http from "node:http";
import { spawn } from "node:child_process";
import {
  isAllowedExternalRequest,
  rewriteDownstreamHeaders,
  rewriteUpstreamHeaders,
} from "./proxy-policy.mjs";

const PUBLIC_HOST = "100.72.146.39:3484";
const BACKEND_HOST = "127.0.0.1";
const BACKEND_PORT = 3485;

function rejectHttp(res) {
  res.writeHead(403, {
    "Content-Type": "application/json; charset=utf-8",
    "Cache-Control": "no-store",
  });
  res.end(JSON.stringify({ error: "Host or Origin not allowed." }));
}

function rejectSocket(socket) {
  socket.end(
    "HTTP/1.1 403 Forbidden\r\nConnection: close\r\nCache-Control: no-store\r\n\r\n",
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

const backend = spawn(
  "kanban",
  ["--host", "0.0.0.0", "--port", String(BACKEND_PORT), "--no-open"],
  { stdio: "inherit", env: process.env },
);

let stopping = false;

const server = http.createServer((req, res) => {
  if (
    !isAllowedExternalRequest(req.headers, req.method, {
      externalHost: PUBLIC_HOST,
      externalOrigin: "http://100.72.146.39:3484",
    })
  ) {
    rejectHttp(res);
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
  if (
    !isAllowedExternalRequest(req.headers, req.method, {
      externalHost: PUBLIC_HOST,
      externalOrigin: "http://100.72.146.39:3484",
      upgrade: true,
    })
  ) {
    rejectSocket(clientSocket);
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

server.on("clientError", (_error, socket) => rejectSocket(socket));
server.on("error", (error) => {
  console.error("Cline Kanban proxy failed:", error.message);
  process.exitCode = 1;
  backend.kill("SIGTERM");
});

backend.on("error", (error) => {
  console.error("Failed to start Cline Kanban:", error.message);
  process.exitCode = 1;
  server.close();
});
backend.on("exit", (code, signal) => {
  if (!stopping) {
    console.error(`Cline Kanban exited (code=${code}, signal=${signal})`);
    process.exitCode = code ?? 1;
    server.close();
  }
});

server.listen(3484, "0.0.0.0", () => {
  console.log(`Cline Kanban strict-origin proxy listening on ${PUBLIC_HOST}`);
});

function shutdown() {
  if (stopping) return;
  stopping = true;
  server.close();
  backend.kill("SIGTERM");
  const timer = setTimeout(() => backend.kill("SIGKILL"), 5000);
  timer.unref();
}

process.on("SIGINT", shutdown);
process.on("SIGTERM", shutdown);
