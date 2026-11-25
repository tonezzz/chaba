// BYOK probe with event tracing: see what the runtime does with a local provider.
import { CopilotClient } from "@github/copilot-sdk";

const baseUrl = process.argv[2] || "http://localhost:11434/v1";
const model = process.argv[3] || "qwen3:8b";
const apiKey = process.argv[4] || "ollama";

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
  console.log("session:", session.sessionId, "model:", model, "base:", baseUrl);

  session.on((ev) => {
    const t = ev.type;
    if (/error|fail|usage|shutdown|model|permission|tool/i.test(t)) {
      console.log("EV", t, JSON.stringify(ev.data ?? ev).slice(0, 400));
    }
  });

  const t1 = Date.now();
  try {
    const resp = await session.sendAndWait("Reply with exactly: BYOK OK", 90000);
    console.log(`turn ${Date.now() - t1}ms`);
    const d = resp?.data ?? {};
    console.log("model:", d.model, "provider:", d.providerId, "content:", JSON.stringify(d.content).slice(0, 200));
  } catch (e) {
    console.log("sendAndWait err after", Date.now() - t1, "ms:", e.message?.slice(0, 500));
  }
  const metrics = await session.rpc.usage.getMetrics().catch(e => ({ err: e.message }));
  console.log("metrics:", JSON.stringify(metrics).slice(0, 600));
  await session.disconnect();
} finally {
  await client.stop().catch(e => console.log("stop err", e));
}
