#!/usr/bin/env node
// Periodic snapshot of mcp-health status without desktop notifications.
// Spawns mcp-health via the SSH wrapper, calls get_health_status, logs to file,
// and posts to the focus inbox via board-api only when something is failing.
import { spawn } from "child_process";
import { mkdirSync, readFileSync, writeFileSync } from "fs";
import { dirname, join } from "path";
import { fileURLToPath } from "url";

const __dirname = dirname(fileURLToPath(import.meta.url));
// This unit runs on exec-role checkouts where focus-inbox file writes can
// never commit — findings go through board-api POST /inbox instead
// (card exec-checkout-generated-writes-focus-inb-da698a).
const LOG_DIR = "/home/tony/CascadeProjects/chaba/logs";
const LOG_FILE = join(LOG_DIR, "mcp-health-snapshot.log");
const BOARD_API = (process.env.BOARD_API ||
  "https://idc03.taila0626a.ts.net:10000").replace(/\/+$/, "");
const WRAPPER = "/home/tony/.config/devin/mcp-scripts/mcp-health-ssh.sh";
const STATE_FILE = "/home/tony/.local/state/mcp-health-snapshot.json";
const ALERT_REPEAT_MS = 6 * 3600 * 1000;

mkdirSync(LOG_DIR, { recursive: true });
mkdirSync(dirname(STATE_FILE), { recursive: true });

function lastAlertAt() {
  try {
    return JSON.parse(readFileSync(STATE_FILE, "utf8")).at || 0;
  } catch {
    return 0;
  }
}

function markAlerted() {
  try {
    writeFileSync(STATE_FILE, JSON.stringify({ at: Date.now() }));
  } catch (e) {
    log(`state write failed: ${e.message}`);
  }
}

function log(message) {
  const line = `${new Date().toISOString()} ${message}`;
  console.error(line);
  writeFileSync(LOG_FILE, line + "\n", { flag: "a" });
}

function send(proc, msg) {
  proc.stdin.write(JSON.stringify(msg) + "\n");
}

function callTool(proc, id, name, args = {}) {
  send(proc, {
    jsonrpc: "2.0",
    id,
    method: "tools/call",
    params: { name, arguments: args },
  });
}

async function runSnapshot() {
  const proc = spawn(WRAPPER, [], { stdio: ["pipe", "pipe", "pipe"] });
  let buffer = "";
  let requestId = 1;

  const pending = new Map();
  const results = [];

  proc.stdout.on("data", (data) => {
    buffer += data.toString("utf8");
    const lines = buffer.split("\n");
    buffer = lines.pop();
    for (const line of lines) {
      if (!line.trim()) continue;
      try {
        const msg = JSON.parse(line);
        if (msg.id !== undefined && pending.has(msg.id)) {
          const { resolve } = pending.get(msg.id);
          pending.delete(msg.id);
          resolve(msg);
        } else if (msg.method === "ping" && msg.id !== undefined) {
          send(proc, { jsonrpc: "2.0", id: msg.id, result: {} });
        } else if (msg.method) {
          // Ignore server notifications
        }
      } catch (e) {
        log(`JSON parse error: ${e.message}`);
      }
    }
  });

  proc.stderr.on("data", (data) => {
    const txt = data.toString("utf8").trim();
    if (txt) log(`server: ${txt}`);
  });

  const request = (name, args = {}) =>
    new Promise((resolve, reject) => {
      const id = requestId++;
      pending.set(id, { resolve, reject });
      callTool(proc, id, name, args);
      setTimeout(() => {
        if (pending.has(id)) {
          pending.delete(id);
          reject(new Error(`Timeout waiting for ${name}`));
        }
      }, 120000);
    });

  try {
    send(proc, {
      jsonrpc: "2.0",
      id: requestId++,
      method: "initialize",
      params: {
        protocolVersion: "2024-11-05",
        capabilities: {},
        clientInfo: { name: "mcp-health-snapshot", version: "1.0" },
      },
    });

    // Wait briefly for initialize to be acknowledged before making calls
    await new Promise((r) => setTimeout(r, 500));

    const result = await request("get_health_status");
    if (result.error) {
      throw new Error(result.error.message);
    }

    const text = result.result?.content?.[0]?.text;
    if (!text) {
      throw new Error("No text content in response");
    }

    const status = JSON.parse(text);
    const { healthy, degraded, error, unknown, total } = status.summary || {};
    log(
      `summary total=${total} healthy=${healthy} degraded=${degraded} error=${error} unknown=${unknown}`
    );

    const categories = status.services_by_category || {};
    const allServices = Object.values(categories).flat();
    const failing = allServices.filter((s) => s.status !== "healthy" && s.status !== "intentional");

    if (failing.length > 0) {
      log(`failing services: ${failing.map((s) => s.service).join(", ")}`);
      if (Date.now() - lastAlertAt() < ALERT_REPEAT_MS) {
        log("alert suppressed — posted within the last 6h");
      } else {
      const text = failing.map((s) =>
        `- ${s.category} / ${s.service}: ${s.status}` +
        (s.error ? ` - ${s.error}` : "")).join("\n");
      const body = {
        text: `mcp-health snapshot: ${failing.length} service(s) not healthy\n${text}`,
        label: `mcp-health: ${failing.length} failing`,
        priority: "high",
        tags: ["health", "monitoring", "snapshot", "mcp-health"],
        owner: "tony",
        session: "mcp-health-snapshot",
        subtasks: failing.map((s) => ({
          label: `Investigate ${s.service}`, status: "not_started",
        })),
      };
      try {
        const res = await fetch(`${BOARD_API}/inbox`, {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify(body),
          signal: AbortSignal.timeout(20000),
        });
        if (!res.ok) {
          log(`inbox post failed: HTTP ${res.status}`);
        } else {
          markAlerted();
          log("inbox alert posted via board-api");
        }
      } catch (e) {
        log(`inbox post failed: ${e.message}`);
      }
      }
    } else {
      log("all healthy");
    }

    proc.stdin.end();
    // Give the server a moment to exit cleanly, then force kill and exit
    setTimeout(() => {
      if (proc.exitCode === null) {
        log("force killing mcp-health process");
        proc.stdout.removeAllListeners();
        proc.stderr.removeAllListeners();
        proc.stdin.removeAllListeners();
        proc.stdout.destroy();
        proc.stderr.destroy();
        proc.stdin.destroy();
        proc.kill("SIGKILL");
      }
      process.exit(process.exitCode || 0);
    }, 2000);
  } catch (e) {
    log(`snapshot failed: ${e.message}`);
    if (proc.exitCode === null) {
      proc.stdout.removeAllListeners();
      proc.stderr.removeAllListeners();
      proc.stdin.removeAllListeners();
      proc.stdout.destroy();
      proc.stderr.destroy();
      proc.stdin.destroy();
      proc.kill("SIGKILL");
    }
    process.exit(1);
  }
}

runSnapshot();
