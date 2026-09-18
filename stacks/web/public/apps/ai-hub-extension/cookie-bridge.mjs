import { createServer } from "http";
import { writeFileSync, mkdirSync, existsSync, readFileSync } from "fs";
import { createHash } from "crypto";
import { dirname } from "path";
import { execSync } from "child_process";
import { homedir } from "os";

const PORT = process.env.PORT || 9876;
const STORAGE =
  process.env.STORAGE || `${homedir()}/.notebooklm/profiles/default/storage_state.json`;
const RSYNC_TARGET = process.env.RSYNC_TARGET || "";
const RESTART_CMD = process.env.RESTART_CMD || "";
const DEBUG_DIR = `${homedir()}/.local/ai-hub/debug`;
const DUMP_DIR = `${homedir()}/.local/ai-hub/page-dumps`;

const AUTH_COOKIE_NAMES = [
  "SID",
  "HSID",
  "SSID",
  "APISID",
  "SAPISID",
  "__Secure-1PSID",
  "__Secure-3PSID",
];

function hasAuthCookies(cookies) {
  return cookies.some((c) => AUTH_COOKIE_NAMES.includes(c.name));
}

function cookieFingerprint(cookies) {
  const canon = cookies
    .map((c) => `${c.name}|${c.domain}|${c.path}|${c.value}|${!!c.secure}`)
    .sort()
    .join("\n");
  return createHash("sha256").update(canon).digest("hex");
}

function handleCookies(req, res) {
  let body = "";
  req.on("data", (chunk) => {
    body += chunk;
  });
  req.on("end", () => {
    try {
      const data = JSON.parse(body);
      if (!Array.isArray(data.cookies)) throw new Error("Expected cookies array");

      const fingerprint = cookieFingerprint(data.cookies);
      try {
        if (existsSync(STORAGE)) {
          const prev = JSON.parse(readFileSync(STORAGE, "utf8"));
          if (Array.isArray(prev.cookies)) {
            if (cookieFingerprint(prev.cookies) === fingerprint) {
              res.writeHead(200);
              res.end("ok (unchanged)");
              return;
            }
            // Refuse to overwrite an authenticated state with an anonymous
            // (logged-out) cookie set — that would destroy recovery options.
            if (hasAuthCookies(prev.cookies) && !hasAuthCookies(data.cookies)) {
              res.writeHead(409);
              res.end("refused: incoming set has no Google auth cookies; keeping existing state");
              return;
            }
            // Refuse to drop DBSC-bound cookies (SID/HSID/APISID) that Chrome
            // can mint via master-token but never export via chrome.cookies.
            const prevNames = new Set(prev.cookies.map((c) => c.name));
            const newNames = new Set(data.cookies.map((c) => c.name));
            const missing = ["SID", "HSID", "APISID"].filter(
              (n) => prevNames.has(n) && !newNames.has(n)
            );
            if (missing.length) {
              res.writeHead(409);
              res.end(
                `refused: incoming set would drop ${missing.join(",")}; keeping existing state`
              );
              return;
            }
          }
        }
      } catch {}

      mkdirSync(dirname(STORAGE), { recursive: true });
      writeFileSync(STORAGE, JSON.stringify(data, null, 2));

      if (RSYNC_TARGET) {
        execSync(`rsync -avz "${STORAGE}" "${RSYNC_TARGET}"`, { stdio: "inherit" });
      }
      if (RESTART_CMD) {
        execSync(RESTART_CMD, { stdio: "inherit" });
      }

      res.writeHead(200);
      res.end("ok (updated)");
    } catch (err) {
      console.error("cookie-bridge save error:", err.message);
      res.writeHead(400);
      res.end(err.message);
    }
  });
}

function handleDebugScreenshot(req, res) {
  let body = "";
  req.on("data", (chunk) => {
    body += chunk;
  });
  req.on("end", () => {
    try {
      const data = JSON.parse(body);
      if (!data.imageData || typeof data.imageData !== "string")
        throw new Error("Expected imageData string");

      const timestamp = new Date().toISOString().replace(/[:.]/g, "-");
      mkdirSync(DEBUG_DIR, { recursive: true });
      const pngPath = `${DEBUG_DIR}/${timestamp}.png`;
      const jsonPath = `${DEBUG_DIR}/${timestamp}.json`;
      const base64 = data.imageData.replace(/^data:image\/png;base64,/, "");
      writeFileSync(pngPath, Buffer.from(base64, "base64"));
      writeFileSync(jsonPath, JSON.stringify(data.debug || {}, null, 2));

      res.writeHead(200);
      res.end(`png: ${pngPath}\njson: ${jsonPath}`);
    } catch (err) {
      res.writeHead(400);
      res.end(err.message);
    }
  });
}

createServer((req, res) => {
  res.setHeader("Access-Control-Allow-Origin", "*");
  res.setHeader("Access-Control-Allow-Methods", "GET, POST, OPTIONS");
  res.setHeader("Access-Control-Allow-Headers", "Content-Type");

  if (req.method === "OPTIONS") {
    res.writeHead(204);
    res.end();
    return;
  }

  if (req.method === "GET" && req.url === "/health") {
    res.writeHead(200);
    res.end("ok");
    return;
  }

  if (req.method === "POST" && req.url === "/cookies") {
    handleCookies(req, res);
    return;
  }

  if (req.method === "POST" && req.url === "/debug-screenshot") {
    handleDebugScreenshot(req, res);
    return;
  }

  if (req.method === "POST" && req.url === "/page-dump") {
    let body = "";
    req.on("data", (chunk) => {
      body += chunk;
    });
    req.on("end", () => {
      try {
        const data = JSON.parse(body);
        if (typeof data.text !== "string" && typeof data.html !== "string") {
          throw new Error("Expected text or html");
        }
        const timestamp = new Date().toISOString().replace(/[:.]/g, "-");
        const slug = String(data.title || data.url || "page")
          .replace(/[^a-z0-9]+/gi, "_")
          .slice(0, 40);
        mkdirSync(DUMP_DIR, { recursive: true });
        const path = `${DUMP_DIR}/${timestamp}_${slug}.json`;
        writeFileSync(
          path,
          JSON.stringify({ receivedAt: new Date().toISOString(), ...data }, null, 2)
        );
        res.writeHead(200);
        res.end(`dump: ${path}`);
      } catch (err) {
        res.writeHead(400);
        res.end(err.message);
      }
    });
    return;
  }

  res.writeHead(404);
  res.end("not found");
}).listen(PORT, () => {
  console.log(`Cookie bridge listening on http://127.0.0.1:${PORT}`);
  console.log(`Storage: ${STORAGE}`);
  if (RSYNC_TARGET) console.log(`Rsync target: ${RSYNC_TARGET}`);
  if (RESTART_CMD) console.log(`Restart: ${RESTART_CMD}`);
  console.log(`Debug dir: ${DEBUG_DIR}`);
});
