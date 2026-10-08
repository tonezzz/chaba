// claw-channel — credential-free edge channel for claws (lab card
// lab-cf-kv-claw-channel). Runs on the surf-thailand.com zone under
// /claw/* — an unlisted path on an existing proxied hostname.
//
//   GET    /claw/<agent>          -> KV cmd:<agent>            (no auth)
//   GET    /claw/digest/<name>    -> KV digest:<name>          (no auth)
//   GET    /claw/report/<agent>   -> KV report:<agent>:latest  (no auth)
//   POST   /claw/report/<agent>   -> KV report:<agent>:<ts> + :latest,
//                                    R2 reports/<agent>/<ts>.json (if bound)
//   POST   /claw/cmd/<agent>      -> KV cmd:<agent>
//   POST   /claw/digest/<name>    -> KV digest:<name>
//
// All POSTs require header X-Ingest-Key == env.INGEST_KEY (wrangler
// secret). Anything else -> 404; wrong key -> 403. Never store
// credentials in KV — commands and reports are payloads, not secrets.

const NAME_RE = /^[a-z0-9][a-z0-9-]{0,39}$/;
const MAX_BODY = 1024 * 1024; // KV value limit is 25MiB; keep it sane

const JSON_HEADERS = {
  "content-type": "application/json; charset=utf-8",
  "cache-control": "no-store",
  "x-robots-tag": "noindex, nofollow",
};

function reply(body, status = 200) {
  return new Response(body, { status, headers: JSON_HEADERS });
}

const notFound = () => reply('{"error":"not found"}', 404);

// constant-time string compare (Workers has no node crypto.timingSafeEqual)
function keyOk(a, b) {
  if (!a || !b) return false;
  const x = new TextEncoder().encode(a);
  const y = new TextEncoder().encode(b);
  if (x.length !== y.length) return false;
  let diff = 0;
  for (let i = 0; i < x.length; i++) diff |= x[i] ^ y[i];
  return diff === 0;
}

async function readKV(env, key) {
  const v = await env.CLAW_KV.get(key, "text");
  return v === null ? notFound() : reply(v);
}

async function writeKV(request, env, key, extraPut) {
  if (!keyOk(request.headers.get("X-Ingest-Key"), env.INGEST_KEY))
    return reply('{"error":"forbidden"}', 403);
  const len = Number(request.headers.get("content-length") || 0);
  if (len > MAX_BODY) return reply('{"error":"too large"}', 413);
  const body = await request.text();
  try {
    JSON.parse(body);
  } catch {
    return reply('{"error":"body must be JSON"}', 400);
  }
  await env.CLAW_KV.put(key, body);
  if (extraPut) await extraPut(body);
  return reply(JSON.stringify({ ok: true, key }));
}

export default {
  async fetch(request, env) {
    const seg = new URL(request.url).pathname.split("/").filter(Boolean);
    if (seg[0] === "claw") seg.shift(); // route prefix is transparent
    if (!env.CLAW_KV) return reply('{"error":"kv not bound"}', 503);

    if (request.method === "GET") {
      if (seg.length === 1 && NAME_RE.test(seg[0])) return readKV(env, `cmd:${seg[0]}`);
      if (seg.length === 2 && seg[0] === "digest" && NAME_RE.test(seg[1]))
        return readKV(env, `digest:${seg[1]}`);
      if (seg.length === 2 && seg[0] === "report" && NAME_RE.test(seg[1]))
        return readKV(env, `report:${seg[1]}:latest`);
      return notFound();
    }

    if (request.method === "POST" && seg.length === 2) {
      const [kind, name] = seg;
      if (!NAME_RE.test(name)) return notFound();
      if (kind === "report") {
        const ts = new Date().toISOString();
        return writeKV(request, env, `report:${name}:${ts}`, async (body) => {
          await env.CLAW_KV.put(`report:${name}:latest`, body);
          if (env.CLAW_R2) await env.CLAW_R2.put(`reports/${name}/${ts}.json`, body);
        });
      }
      if (kind === "cmd") return writeKV(request, env, `cmd:${name}`);
      if (kind === "digest") return writeKV(request, env, `digest:${name}`);
    }
    return notFound();
  },
};
