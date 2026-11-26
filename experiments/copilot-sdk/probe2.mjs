// Credit-consumption probe: run a fixed prompt, then read session usage metrics + quota.
import { CopilotClient } from "@github/copilot-sdk";

const client = new CopilotClient();
await client.start();
try {
  const session = await client.createSession({});
  console.log("session:", session.sessionId);

  const before = await session.rpc.usage.getMetrics().catch(e => ({ err: e.message }));
  console.log("metrics before:", JSON.stringify(before).slice(0, 400));

  const t1 = Date.now();
  const resp = await session.sendAndWait("Reply with exactly: SDK OK", 120000);
  const ms = Date.now() - t1;
  const d = resp?.data ?? {};
  console.log(`turn ok ${ms}ms model=${d.model} provider=${d.providerId} content=${JSON.stringify(d.content).slice(0,80)}`);

  const after = await session.rpc.usage.getMetrics().catch(e => ({ err: e.message }));
  console.log("metrics after:", JSON.stringify(after, null, 1).slice(0, 3000));

  const quota = await session.rpc.quota.get().catch(e => ({ err: e.message }));
  console.log("quota:", JSON.stringify(quota, null, 1).slice(0, 3000));

  await session.disconnect();
} finally {
  await client.stop().catch(e => console.log("stop err", e));
}
