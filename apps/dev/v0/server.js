const http = require("http");
const fs = require("fs");
const path = require("path");
const { spawn } = require("child_process");
const { randomUUID } = require("crypto");
const WebSocket = require("ws");

const PORT = process.env.PORT || 8005;
const DATA_DIR = path.join(__dirname, "data");
const HISTORY_FILE = path.join(DATA_DIR, "history.ndjson");
const FEEDBACK_FILE = path.join(DATA_DIR, "feedback.ndjson");

fs.mkdirSync(DATA_DIR, { recursive: true });

let playground = { providers: [], categories: [], scores: {} };
try {
  playground = JSON.parse(fs.readFileSync(path.join(__dirname, "playground.json"), "utf8"));
} catch (err) {
  console.error("failed to load playground.json:", err.message);
}

function categorize(prompt) {
  const text = String(prompt).toLowerCase();
  const matched = [];
  for (const cat of playground.categories || []) {
    const hits = (cat.terms || []).filter((term) => text.includes(term.toLowerCase()));
    if (hits.length > 0) {
      matched.push({ id: cat.id, name: cat.name, hits: hits.length });
    }
  }
  matched.sort((a, b) => b.hits - a.hits);
  return matched.map((m) => m.id);
}

function getLeaderboard(category) {
  const scores = playground.scores || {};
  if (category) {
    const map = scores[category] || {};
    const rankings = Object.entries(map)
      .map(([key, score]) => {
        const [providerId, modelId] = key.split("/");
        const provider = (playground.providers || []).find((p) => p.id === providerId);
        const model = provider ? provider.models.find((m) => m.id === modelId) : null;
        return {
          key,
          provider: providerId,
          model: modelId,
          providerName: provider ? provider.name : providerId,
          modelName: model ? model.name : modelId,
          score,
        };
      })
      .sort((a, b) => b.score - a.score);
    return { category, rankings };
  }

  const result = {};
  for (const cat of Object.keys(scores)) {
    result[cat] = getLeaderboard(cat).rankings.slice(0, 3);
  }
  return { categories: result };
}

function readNdjson(file) {
  if (!fs.existsSync(file)) return [];
  return fs
    .readFileSync(file, "utf8")
    .split("\n")
    .filter(Boolean)
    .map((line) => {
      try {
        return JSON.parse(line);
      } catch (e) {
        return null;
      }
    })
    .filter(Boolean);
}

function appendNdjson(file, obj) {
  fs.appendFileSync(file, JSON.stringify(obj) + "\n");
}

const server = http.createServer((req, res) => {
  const parsed = new URL(req.url, "http://localhost");
  const pathname = parsed.pathname;
  const method = req.method;
  const sendJson = (code, obj) => {
    res.writeHead(code, { "Content-Type": "application/json" });
    res.end(JSON.stringify(obj));
  };
  const sendText = (code, text, type = "text/plain") => {
    res.writeHead(code, { "Content-Type": type });
    res.end(text);
  };
  const readBody = (cb) => {
    let body = "";
    req.on("data", (chunk) => {
      body += chunk;
    });
    req.on("end", () => {
      try {
        cb(JSON.parse(body || "{}"));
      } catch (e) {
        sendJson(400, { error: "bad json" });
      }
    });
  };

  if (pathname === "/" || pathname === "/index.html") {
    const file = path.join(__dirname, "index.html");
    fs.readFile(file, (err, data) => {
      if (err) {
        res.writeHead(500);
        res.end("failed to load index.html");
      } else {
        res.writeHead(200, { "Content-Type": "text/html" });
        res.end(data);
      }
    });
    return;
  }

  if (pathname === "/health") {
    sendJson(200, { ok: true });
    return;
  }

  if (pathname === "/api/providers") {
    sendJson(200, { providers: playground.providers });
    return;
  }

  if (pathname === "/api/categories") {
    sendJson(200, { categories: playground.categories });
    return;
  }

  if (pathname === "/api/categorize") {
    const prompt = parsed.searchParams.get("prompt") || "";
    const categories = categorize(prompt);
    sendJson(200, { prompt, categories });
    return;
  }

  if (pathname === "/api/leaderboard") {
    const category = parsed.searchParams.get("category") || null;
    sendJson(200, getLeaderboard(category));
    return;
  }

  if (pathname === "/api/feedback" && method === "POST") {
    readBody((body) => {
      const fb = {
        id: randomUUID(),
        runId: body.runId,
        rating: body.rating,
        comment: body.comment || "",
        timestamp: Date.now(),
      };
      appendNdjson(FEEDBACK_FILE, fb);
      sendJson(200, { ok: true });
    });
    return;
  }

  if (pathname === "/api/history/export" && method === "GET") {
    const runs = readNdjson(HISTORY_FILE).slice(-100);
    const feedback = readNdjson(FEEDBACK_FILE);
    const fbMap = new Map();
    for (const f of feedback) fbMap.set(f.runId, f);

    const md = ["# AI Playground run history\n"];
    for (const r of runs) {
      const f = fbMap.get(r.id);
      md.push(`## ${r.id}`);
      md.push(`- **Time:** ${new Date(r.startedAt).toISOString()}`);
      md.push(`- **Provider/Model:** ${r.provider} / ${r.model}`);
      md.push(`- **Categories:** ${(r.categories || []).join(", ")}`);
      md.push(`- **Status:** ${r.status}`);
      md.push(`- **Exit code:** ${r.exitCode}`);
      md.push(`- **Prompt:** ${r.prompt}`);
      if (f) md.push(`- **Feedback:** ${f.rating} — ${f.comment || ""}`);
      md.push(
        `- **Output preview:** ${r.output ? r.output.slice(0, 300).replace(/\n/g, " ") : ""}`
      );
      md.push("");
    }
    sendText(200, md.join("\n"), "text/markdown");
    return;
  }

  res.writeHead(404);
  res.end("not found");
});

const wss = new WebSocket.Server({ server, path: "/ws" });

function getProviderCommand(provider, prompt, mode) {
  const p = provider || "devin-stub";
  switch (p) {
    case "devin-stub": {
      const stubArgs = ["-p", "--", prompt];
      if (mode && mode !== "normal") {
        stubArgs.unshift("--permission-mode", mode);
      }
      return {
        cmd: "python3",
        args: [path.join(__dirname, "devin-stub.py"), ...stubArgs],
        env: {},
      };
    }
    case "openai":
      return {
        cmd: "python3",
        args: [path.join(__dirname, "providers", "openai.py"), prompt],
        env: {},
      };
    case "claude":
      return {
        cmd: "python3",
        args: [path.join(__dirname, "providers", "claude.py"), prompt],
        env: {},
      };
    case "ollama":
      return {
        cmd: "python3",
        args: [path.join(__dirname, "providers", "ollama.py"), prompt],
        env: {},
      };
    case "gemini":
      return {
        cmd: "python3",
        args: [path.join(__dirname, "providers", "gemini.py"), prompt],
        env: {},
      };
    default:
      throw new Error(`unknown provider: ${p}`);
  }
}

function stripAnsi(buf) {
  return buf
    .replace(/\x1b\[[0-9;?]*[a-zA-Z]/g, "")
    .replace(/\x1b\][^\x07\x1b]*(?:\x07|\x1b\\)/g, "")
    .replace(/\x1b[\(\)][AB012]/g, "");
}

wss.on("connection", (ws) => {
  let child = null;
  let record = null;

  function send(type, payload) {
    if (ws.readyState === WebSocket.OPEN) {
      ws.send(JSON.stringify({ type, ...payload }));
    }
  }

  function finishRun(status, extra) {
    if (!record) return;
    record.status = status;
    record.finishedAt = Date.now();
    Object.assign(record, extra);
    appendNdjson(HISTORY_FILE, record);
    record = null;
  }

  ws.on("message", (raw) => {
    let msg;
    try {
      msg = JSON.parse(raw);
    } catch (e) {
      send("error", { message: "bad json" });
      return;
    }

    if (msg.type === "cancel" && child) {
      child.kill("SIGTERM");
      child = null;
      finishRun("cancelled", { exitCode: null });
      send("status", { text: "cancelled" });
      return;
    }

    if (msg.type === "prompt" && msg.prompt && !child) {
      const prompt = String(msg.prompt).trim();
      if (!prompt) return;

      record = {
        id: randomUUID(),
        prompt,
        provider: msg.provider || "devin-stub",
        model: msg.model || "",
        mode: msg.mode || "normal",
        categories: msg.categories || [],
        startedAt: Date.now(),
        output: "",
        stderr: "",
      };
      send("status", { text: "running", runId: record.id });

      let command;
      try {
        command = getProviderCommand(msg.provider, prompt, msg.mode);
      } catch (err) {
        const runId = record ? record.id : null;
        finishRun("error", { exitCode: -1, error: err.message });
        send("error", { message: err.message, runId });
        return;
      }

      child = spawn(command.cmd, command.args, {
        env: { ...process.env, NO_COLOR: "1", ...command.env },
        cwd: __dirname,
        detached: false,
      });

      child.stdout.on("data", (data) => {
        const text = stripAnsi(data.toString("utf8"));
        if (record) record.output += text;
        send("out", { text });
      });

      child.stderr.on("data", (data) => {
        const text = stripAnsi(data.toString("utf8"));
        if (record) record.stderr += text;
        send("err", { text });
      });

      child.on("error", (err) => {
        send("err", { text: `spawn error: ${err.message}` });
        const runId = record ? record.id : null;
        finishRun("error", { exitCode: -1, error: err.message });
        send("error", { message: err.message, runId });
        child = null;
      });

      child.on("close", (code) => {
        const runId = record ? record.id : null;
        finishRun("done", { exitCode: code ?? 0 });
        child = null;
        send("done", { code: code ?? 0, runId });
      });
    }
  });

  ws.on("close", () => {
    if (child) {
      child.kill("SIGTERM");
      child = null;
    }
    if (record) {
      finishRun("disconnected", { exitCode: null });
    }
  });
});

server.listen(PORT, () => {
  console.log(`ai-playground running at http://localhost:${PORT}`);
});
