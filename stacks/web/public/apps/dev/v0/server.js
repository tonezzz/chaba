const http = require("http");
const fs = require("fs");
const path = require("path");
const { spawn } = require("child_process");
const WebSocket = require("ws");

const PORT = process.env.PORT || 8005;

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

const server = http.createServer((req, res) => {
  const parsed = new URL(req.url, "http://localhost");
  const pathname = parsed.pathname;
  const sendJson = (code, obj) => {
    res.writeHead(code, { "Content-Type": "application/json" });
    res.end(JSON.stringify(obj));
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

  function send(type, payload) {
    if (ws.readyState === WebSocket.OPEN) {
      ws.send(JSON.stringify({ type, ...payload }));
    }
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
      send("status", { text: "cancelled" });
      return;
    }

    if (msg.type === "prompt" && msg.prompt && !child) {
      const prompt = String(msg.prompt).trim();
      if (!prompt) return;

      send("status", { text: "running" });

      let command;
      try {
        command = getProviderCommand(msg.provider, prompt, msg.mode);
      } catch (err) {
        send("error", { message: err.message });
        return;
      }

      child = spawn(command.cmd, command.args, {
        env: { ...process.env, NO_COLOR: "1", ...command.env },
        cwd: __dirname,
        detached: false,
      });

      child.stdout.on("data", (data) => {
        send("out", { text: stripAnsi(data.toString("utf8")) });
      });

      child.stderr.on("data", (data) => {
        send("err", { text: stripAnsi(data.toString("utf8")) });
      });

      child.on("error", (err) => {
        send("err", { text: `spawn error: ${err.message}` });
        child = null;
      });

      child.on("close", (code) => {
        child = null;
        send("done", { code: code ?? 0 });
      });
    }
  });

  ws.on("close", () => {
    if (child) {
      child.kill("SIGTERM");
      child = null;
    }
  });
});

server.listen(PORT, () => {
  console.log(`ai-playground running at http://localhost:${PORT}`);
});
