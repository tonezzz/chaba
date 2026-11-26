// BYOK probe: point a Copilot SDK session at our LiteLLM proxy (OpenAI-compatible).
import { CopilotClient } from "@github/copilot-sdk";
import { readFileSync } from "node:fs";

const env = Object.fromEntries(
  readFileSync(process.env.HOME + "/.config/secrets/litellm-chaba.env", "utf8")
    .split("\n").filter(l => l.includes("=") && !l.startsWith("#"))
    .map(l => { const i = l.indexOf("="); return [l.slice(0, i).trim(), l.slice(i + 1).trim()]; })
);
const baseUrl = env.LITELLM_URL; // http://100.102.134.91:4000/v1
const apiKey = env.LITELLM_KEY;
const model = process.argv[2] || "gemini-2.5-flash-lite-free";

const client = new CopilotClient();
await client.start();
try {
  const session = await client.createSession({
    model,
    provider: {
      type: "openai",
      wireApi: "completions",
      baseUrl,
      apiKey,
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
