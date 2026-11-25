// Probe @github/copilot-sdk: listModels, createSession, sendAndWait.
import { CopilotClient } from "@github/copilot-sdk";

const t0 = Date.now();
const client = new CopilotClient();
try {
  await client.start();
  console.log(`start ok in ${Date.now() - t0}ms`);

  const models = await client.listModels();
  console.log(`listModels -> ${models.length} models`);
  for (const m of models.slice(0, 30)) {
    console.log(`  - ${m.id ?? m.name ?? JSON.stringify(m).slice(0, 120)}`);
  }

  const session = await client.createSession({});
  console.log(`createSession ok id=${session.sessionId ?? "?"}`);

  const t1 = Date.now();
  const resp = await session.sendAndWait("Reply with exactly: SDK OK", 120000);
  console.log(`sendAndWait ok in ${Date.now() - t1}ms`);
  // print a compact view of the response
  const s = JSON.stringify(resp);
  console.log("resp keys:", Object.keys(resp ?? {}));
  const content = resp?.content ?? resp?.message ?? s;
  console.log(String(content).slice(0, 500));
} finally {
  try { await client.disconnect(); } catch (e) { console.log("disconnect err", e.message); }
}
