// Mock upstreams for merged proxy probe.
// Gemini batchEmbedContents: 429 for keys containing "bad", 200 otherwise.
// Gateway /v1/embeddings: 200 with N embeddings.
import { createServer } from "node:http";

const PORT = parseInt(process.env.MOCK_PORT || "18999", 10);
const hits = { gemini: [], gateway: [] };

const server = createServer((req, res) => {
  let raw = "";
  req.on("data", (c) => (raw += c));
  req.on("end", () => {
    const url = new URL(req.url, "http://x");
    if (url.pathname.includes("batchEmbedContents")) {
      const key = url.searchParams.get("key") || "";
      hits.gemini.push(key.slice(-4));
      if (key.includes("bad")) {
        res.writeHead(429, { "Content-Type": "application/json", "retry-after": "0" });
        res.end(JSON.stringify({ error: { message: "quota" } }));
        return;
      }
      const body = JSON.parse(raw);
      const n = body.requests.length;
      res.writeHead(200, { "Content-Type": "application/json" });
      res.end(JSON.stringify({
        embeddings: Array.from({ length: n }, (_, i) => ({
          values: [0.1 * (i + 1), 0.2, 0.3],
        })),
      }));
      return;
    }
    if (url.pathname === "/v1/embeddings") {
      hits.gateway.push(req.headers.authorization || "");
      const body = JSON.parse(raw);
      const n = Array.isArray(body.input) ? body.input.length : 1;
      res.writeHead(200, { "Content-Type": "application/json" });
      res.end(JSON.stringify({
        data: Array.from({ length: n }, (_, i) => ({ embedding: [0.9, 0.8, 0.7] })),
      }));
      return;
    }
    res.writeHead(404); res.end("nope");
  });
});
server.listen(PORT, "127.0.0.1", () => console.log(`mock on ${PORT}`));
