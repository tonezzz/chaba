// BYOK probe: point a Copilot SDK session at local Ollama (OpenAI-compatible /v1).
import { CopilotClient } from "@github/copilot-sdk";

const model = process.argv[2] || "qwen3:4b";

const client = new CopilotClient();
await client.start();
try {
  const session = await client.createSession({
    model,
    provider: {
      type: "openai",
      wireApi: "completions",
      baseUrl: "http://localhost:11434/v1",
      apiKey: "ollama",
      modelId: model,
      wireModel: model,
    },
  });
  console.log("session:", session.sessionId, "model:", model);

  const t1 = Date.now();
  const resp = await session.sendAndWait("Reply with exactly: BYOK OK", 120000);
  console.log(`turn ${Date.now() - t1}ms`);
  const d = resp?.data ?? {};
  console.log("model:", d.model, "provider:", d.providerId, "content:", JSON.stringify(d.content).slice(0, 200));
  const metrics = await session.rpc.usage.getMetrics().catch(e => ({ err: e.message }));
  console.log("metrics:", JSON.stringify(metrics).slice(0, 800));
  await session.disconnect();
} finally {
  await client.stop().catch(e => console.log("stop err", e));
}
