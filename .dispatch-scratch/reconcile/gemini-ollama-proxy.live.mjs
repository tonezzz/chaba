#!/usr/bin/env node
import { createServer } from "node:http";

const PORT = parseInt(process.env.GEMINI_PROXY_PORT || "11435", 10);
const HOST = process.env.GEMINI_PROXY_HOST || "0.0.0.0";
const GEMINI_API_KEY = process.env.GEMINI_API_KEY;
// Paid-tier Gemini key — same models, same vector space as the free key,
// billed per call. Engaged only after the free leg exhausts retries and
// BEFORE the Ollama fallback (different vector space): during a free-quota
// outage this keeps vectors index-safe at bounded spend. gemini-keys.env
// carries it; unset = leg skipped.
const GEMINI_API_KEY_PAID = process.env.GEMINI_API_KEY_PAID || "";
const GEMINI_EMBEDDING_MODEL = process.env.GEMINI_EMBEDDING_MODEL || "gemini-embedding-2";
// Fallback model is OFF by default — gemini-embedding-001 and -2 are
// DIFFERENT vector spaces (measured cos ≈ 0.00), so cross-model retry
// would write wrong-space vectors into the index. Set only if you know
// the fallback shares the same space.
const GEMINI_EMBEDDING_FALLBACK_MODEL =
  process.env.GEMINI_EMBEDDING_FALLBACK_MODEL || null;
const DEFAULT_DIMENSIONS = parseInt(process.env.GEMINI_EMBEDDING_DIMENSIONS || "768", 10);
const OLLAMA_FALLBACK_BASE = (process.env.OLLAMA_FALLBACK_BASE || "").replace(/\/$/, "");
const OLLAMA_FALLBACK_MODEL = process.env.OLLAMA_FALLBACK_MODEL || "nomic-embed-text";
// OpenRouter middle tier: mirrors google/* embedding models through an
// OpenAI-compatible /embeddings endpoint. Same underlying model = same
// vector space, so a Gemini-quota outage degrades to OR without breaking
// recall. Only engaged when OPENROUTER_API_KEY is set.
const OPENROUTER_API_KEY = process.env.OPENROUTER_API_KEY || "";
const OPENROUTER_BASE = (process.env.OPENROUTER_BASE || "https://openrouter.ai/api/v1").replace(/\/$/, "");
const OPENROUTER_PREFIX = process.env.OPENROUTER_MODEL_PREFIX || "google/";
const OPENROUTER_PROVIDER = process.env.OPENROUTER_PROVIDER || "Google";
// When OPENROUTER_API_KEY is set and OPENROUTER_PRIMARY != "0", OpenRouter
// is the primary embedding provider — Gemini direct is only the same-space
// backup and OR errors are fatal to the caller (fail closed). Set
// OPENROUTER_PRIMARY=0 to run free Gemini first and pay for OR only during
// a Gemini outage — same vector space either way (see embed-bench), so the
// flip is index-safe. Gemini and Ollama embed in different vector spaces;
// a silent fallback write would corrupt the index.
const OPENROUTER_PRIMARY = (process.env.OPENROUTER_PRIMARY ?? "1") !== "0";
// LiteLLM gateway embed leg (card or-direct-bypass-leak-audit): when
// EMBED_GATEWAY_BASE is set, the OR backup leg rides the gateway's
// OpenAI-compatible /v1/embeddings (model EMBED_GATEWAY_MODEL, default
// "embedding" -> openrouter/google/gemini-embedding-2 upstream) instead
// of holding a raw OR key — spend stays attributed inside LiteLLM.
// Gateway mode is backup-only: OPENROUTER_PRIMARY never promotes it to
// primary (that path still requires a raw OPENROUTER_API_KEY).
const EMBED_GATEWAY_BASE = (process.env.EMBED_GATEWAY_BASE || "").replace(/\/$/, "");
const EMBED_GATEWAY_KEY = process.env.EMBED_GATEWAY_KEY || process.env.LITELLM_KEY || "";
const EMBED_GATEWAY_MODEL = process.env.EMBED_GATEWAY_MODEL || "embedding";
const EMBED_VIA_GATEWAY = !!(EMBED_GATEWAY_BASE && EMBED_GATEWAY_KEY);
const OR_LEG_CONFIGURED = EMBED_VIA_GATEWAY || !!OPENROUTER_API_KEY;
const MAX_RPM = parseInt(process.env.GEMINI_PROXY_MAX_RPM || "100", 10);
const BATCH_SIZE = parseInt(process.env.GEMINI_PROXY_BATCH_SIZE || "100", 10);
const MAX_RETRIES = parseInt(process.env.GEMINI_PROXY_MAX_RETRIES || "5", 10);
const CIRCUIT_COOLDOWN_MS = parseInt(process.env.OLLAMA_CIRCUIT_COOLDOWN_MS || "300000", 10);
// When Gemini exhausts retries (quota outage), open the circuit: route
// straight to the Ollama fallback for a cooldown instead of paying the
// retry+backoff cost on every request.
let geminiCircuitOpenUntil = 0;
// Same idea for the OR-primary path: once OR fails, skip the dead hop
// and serve direct Gemini (verified same vector space — see embed-bench)
// for a cooldown window instead of paying one doomed OR call per embed.
const OR_CIRCUIT_COOLDOWN_MS = parseInt(process.env.OR_CIRCUIT_COOLDOWN_MS || "300000", 10);
let orCircuitOpenUntil = 0;
let lastBackupProvider = null;
// Spend firewall (2026-11-12: an exhausted Gemini leg + open OR cap let a
// retry storm burn $3.80 overnight — 39k billed OR calls in 20h). When
// OR_FALLBACK_DAILY_CAP > 0, at most that many OR batches may be billed per
// UTC day; beyond it the OR leg is skipped exactly like an open circuit so
// the caller hard-fails instead of silently draining a key limit.
const OR_FALLBACK_DAILY_CAP = parseInt(process.env.OR_FALLBACK_DAILY_CAP || "0", 10);
let orCallsToday = 0;
let orCallsDay = new Date().toISOString().slice(0, 10);
function orDailyCapHit() {
  const today = new Date().toISOString().slice(0, 10);
  if (today !== orCallsDay) { orCallsDay = today; orCallsToday = 0; }
  return OR_FALLBACK_DAILY_CAP > 0 && orCallsToday >= OR_FALLBACK_DAILY_CAP;
}
// Paid-Gemini spend firewall (2026-11-17, card
// idc03-gemini-ollama-proxy-paid-fallback): the paid leg was designed for
// short outage windows, but with the free key quota-dead ~1k/day against
// ~58k requests and the OR cap burning out mid-day it became the de-facto
// primary — ~39k billed calls/day (~$3.80/day). PAID_GEMINI_HOURLY_CAP
// trickles service through a sustained outage; PAID_GEMINI_DAILY_CAP is
// the absolute bound. Cap-hit skips the paid leg exactly like the OR cap
// — the caller hard-fails (mddb marks the doc's embedding failed, which
// is retryable on recovery) instead of draining the key. 0 = uncapped.
const PAID_GEMINI_DAILY_CAP = parseInt(process.env.PAID_GEMINI_DAILY_CAP || "0", 10);
const PAID_GEMINI_HOURLY_CAP = parseInt(process.env.PAID_GEMINI_HOURLY_CAP || "0", 10);
let paidCallsToday = 0;
let paidCallsDay = new Date().toISOString().slice(0, 10);
let paidCallsThisHour = 0;
let paidCallsHour = new Date().toISOString().slice(0, 13);
function paidCapHit() {
  const now = new Date().toISOString();
  const today = now.slice(0, 10);
  if (today !== paidCallsDay) { paidCallsDay = today; paidCallsToday = 0; }
  const hour = now.slice(0, 13);
  if (hour !== paidCallsHour) { paidCallsHour = hour; paidCallsThisHour = 0; }
  if (PAID_GEMINI_DAILY_CAP > 0 && paidCallsToday >= PAID_GEMINI_DAILY_CAP)
    return `daily-cap ${PAID_GEMINI_DAILY_CAP} hit`;
  if (PAID_GEMINI_HOURLY_CAP > 0 && paidCallsThisHour >= PAID_GEMINI_HOURLY_CAP)
    return `hourly-cap ${PAID_GEMINI_HOURLY_CAP} hit`;
  return null;
}
function paidCallBilled() {
  paidCallsToday += 1;
  paidCallsThisHour += 1;
}
// Free-key quota breaker (ADA-0138, 2026-11-16): the free GEMINI_API_KEY
// sat quota-exhausted for days — every request paid up to MAX_RETRIES
// doomed calls in BOTH the primary leg and the backup chain's
// direct-Gemini leg (~35k 429s/day) and the retry/backoff latency pushed
// memory_search past its 8s budget. Once the free leg fails with retries
// spent, skip it for FREE_GEMINI_CIRCUIT_MS and let the paid leg (same
// model, same vector space) serve directly; cooldown expiry is the
// half-open probe — the next request retries free and re-opens on
// failure. Paid legs are deliberately NOT routed through this wrapper.
const FREE_GEMINI_CIRCUIT_MS = parseInt(process.env.FREE_GEMINI_CIRCUIT_MS || "600000", 10);
// Free-key ring (2026-11-18): GEMINI_API_KEY is the primary free leg;
// GEMINI_FREE_KEYS adds comma-separated extra FREE-TIER keys, each with
// its own ~1000/day embed quota and its own circuit breaker. Keys are
// tried in order; a key whose circuit is open is skipped until its
// cooldown expires (half-open probe). NEVER list paid-tier keys here —
// they bill per call and would silently drain that project's cap.
const GEMINI_FREE_KEYS = [GEMINI_API_KEY,
  ...(process.env.GEMINI_FREE_KEYS || "").split(","),
  ...Object.keys(process.env)
    .filter((k) => /^GEMINI_FREE_KEYS_\d+$/.test(k))
    .sort()
    .map((k) => process.env[k])]
  .map((k) => (k || "").trim()).filter(Boolean);
const freeGeminiCircuits = new Map(); // apiKey -> circuit-open-until ms
function freeKeyCircuitOpen(key) {
  return Date.now() < (freeGeminiCircuits.get(key) || 0);
}
function freeGeminiCircuitOpen() {
  // "open" means EVERY free key is circuit-broken — callers use this to
  // decide whether the free leg is worth attempting at all.
  return GEMINI_FREE_KEYS.every(freeKeyCircuitOpen);
}
function keyTag(key) {
  return `...${String(key).slice(-4)}`;
}
const INITIAL_BACKOFF_MS = 500;
const MAX_BACKOFF_MS = 30000;

// ---- ops-event emit ------------------------------------------------------
// Same door as scripts/ada/embed-probe.py::_emit — an ops-event doc in the
// ada-ha-events collection (ops-digest flags the type, Ada surfaces read
// it). The probe only polls every 15min, so a provider cap-hit ran silent
// for ~30min on 2026-11-12 (298 failed embeds) before its next tick.
// Emitting HERE at the circuit-open / failure-streak moment is what pages
// at minute ~2 instead.
const MDDB_OPS_URL = (process.env.MDDB_OPS_URL || "http://100.102.134.91:11023")
  .replace(/\/+$/, "").replace(/\/v1$/, "");
const OPS_COLLECTION = process.env.ADA_OPS_COLLECTION || "ada-ha-events-tony";
// N consecutive failed embed requests before embed_providers_down fires.
const EMBED_FAIL_ALERT_AFTER = parseInt(process.env.EMBED_FAIL_ALERT_AFTER || "3", 10);
// Min gap between repeat emits of the same event type (flap damping).
const OPS_ALERT_MIN_MS = parseInt(process.env.OPS_ALERT_MIN_MS || "900000", 10);
const opsAlertSentAt = {};
let consecutiveEmbedFailures = 0;
let embedFailuresTotal = 0;
let embedOkTotal = 0;
let lastEmbedError = null;
let alertedProvidersDown = false;

function emitOpsEvent(evType, detail) {
  const now = Date.now();
  if (now - (opsAlertSentAt[evType] || 0) < OPS_ALERT_MIN_MS) return;
  opsAlertSentAt[evType] = now;
  const ts = new Date().toISOString();
  const body = JSON.stringify({
    collection: OPS_COLLECTION,
    key: `ops-embed-proxy-${evType}-${ts.replace(/[-:T.]/g, "").slice(0, 14)}`,
    lang: "en",
    contentMd: detail,
    meta: {
      kind: ["ops-event"], type: [evType], instance: ["tony"],
      session_id: ["gemini-ollama-proxy"], ts: [ts],
    },
  });
  // Fire-and-forget — alerting must never delay or fail the embed path.
  const ctrl = new AbortController();
  const timer = setTimeout(() => ctrl.abort(), 4000);
  fetch(`${MDDB_OPS_URL}/v1/add`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body,
    signal: ctrl.signal,
  })
    .then(() => console.log(`ops event ${evType} emitted`))
    .catch((e) => console.log(`ops event write failed (${evType}): ${e.message}`))
    .finally(() => clearTimeout(timer));
}

// Alias map — anything unmapped falls through to GEMINI_EMBEDDING_MODEL
// (the active space). Deliberately no text-embedding-004 → -001 alias:
// -001 is a different vector space than -2 and would poison the index.
const MODEL_ALIASES = {
  "nomic-embed-text": "gemini-embedding-2",
  "gemini-embedding-001": "gemini-embedding-001",
  "gemini-embedding-1": "gemini-embedding-001",
  "gemini-embedding-002": "gemini-embedding-2",
  "gemini-embedding-2": "gemini-embedding-2",
  "gemini-embedding-2-preview": "gemini-embedding-2",
};

function sleep(ms) {
  return new Promise((resolve) => setTimeout(resolve, ms));
}

function sendJson(res, status, obj) {
  const body = JSON.stringify(obj);
  res.writeHead(status, {
    "Content-Type": "application/json",
    "Content-Length": Buffer.byteLength(body),
    "Access-Control-Allow-Origin": "*",
    "Access-Control-Allow-Methods": "GET, POST, OPTIONS",
    "Access-Control-Allow-Headers": "Content-Type",
  });
  res.end(body);
}

function resolveGeminiModel(requested) {
  const key = (requested || "").toLowerCase().trim();
  return MODEL_ALIASES[key] || GEMINI_EMBEDDING_MODEL;
}

class RateLimiter {
  constructor(rpm) {
    this.minInterval = 60000 / rpm;
    this.nextAvailable = 0;
    this.tail = Promise.resolve();
  }

  acquire() {
    const p = this.tail;
    this.tail = p.then(async () => {
      const now = Date.now();
      const wait = Math.max(0, this.nextAvailable - now);
      if (wait > 0) await sleep(wait);
      this.nextAvailable = Date.now() + this.minInterval;
    });
    return this.tail;
  }
}

const geminiRateLimiter = new RateLimiter(MAX_RPM);

function retryAfterMs(response) {
  const raw = response.headers.get("retry-after") || response.headers.get("Retry-After");
  if (!raw) return null;
  const seconds = parseInt(raw, 10);
  return isNaN(seconds) ? null : seconds * 1000;
}

function parseGeminiBatch(data, count) {
  if (!data.embeddings || !Array.isArray(data.embeddings)) {
    if (data.embedding && Array.isArray(data.embedding.values)) {
      return [data.embedding.values];
    }
    throw new Error("unexpected Gemini response: missing embeddings array");
  }
  if (data.embeddings.length !== count) {
    throw new Error(`expected ${count} embeddings, got ${data.embeddings.length}`);
  }
  return data.embeddings.map((entry, i) => {
    if (Array.isArray(entry.values)) return entry.values;
    if (entry.embedding && Array.isArray(entry.embedding.values)) return entry.embedding.values;
    throw new Error(`unexpected embedding shape at index ${i}`);
  });
}

async function _fetchGeminiBatchForModel(texts, geminiModel, outputDimensionality, apiKey = GEMINI_API_KEY) {
  const url = `https://generativelanguage.googleapis.com/v1beta/models/${geminiModel}:batchEmbedContents?key=${apiKey}`;
  const requests = texts.map((text) => ({
    model: `models/${geminiModel}`,
    content: { parts: [{ text }] },
    outputDimensionality,
  }));

  let lastError;
  for (let attempt = 0; attempt < MAX_RETRIES; attempt++) {
    if (attempt > 0) {
      const backoff = Math.min(INITIAL_BACKOFF_MS * 2 ** (attempt - 1), MAX_BACKOFF_MS);
      await sleep(backoff);
    }

    await geminiRateLimiter.acquire();

    const response = await fetch(url, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ requests }),
    });

    if (response.ok) {
      const data = await response.json();
      return parseGeminiBatch(data, texts.length);
    }

    const errorText = await response.text();
    lastError = `Gemini API error: ${response.status} - ${errorText}`;

    if (response.status === 429) {
      const retryMs = retryAfterMs(response);
      if (retryMs && retryMs > 0) {
        await sleep(Math.min(retryMs, MAX_BACKOFF_MS));
      }
      continue;
    }

    if (response.status >= 500) {
      continue;
    }

    throw new Error(lastError);
  }

  throw new Error(lastError);
}

async function fetchGeminiBatch(texts, geminiModel, outputDimensionality, fallbackModel = null, apiKey = GEMINI_API_KEY) {
  try {
    return await _fetchGeminiBatchForModel(texts, geminiModel, outputDimensionality, apiKey);
  } catch (err) {
    if (fallbackModel && String(err).includes("429")) {
      console.log(
        `Primary Gemini model ${geminiModel} rate-limited; trying fallback ${fallbackModel}`
      );
      return await _fetchGeminiBatchForModel(texts, fallbackModel, outputDimensionality, apiKey);
    }
    throw err;
  }
}

// Free-key legs with per-key quota breakers: keys whose circuit is open
// are skipped; a key that exhausts its retries opens ITS circuit for one
// window and the next key in the ring is tried. Only when every key's
// circuit is open does the leg fail through to the paid/OR chain.
async function fetchFreeGeminiBatch(texts, geminiModel, outputDimensionality, fallbackModel = null) {
  const now = Date.now();
  const candidates = GEMINI_FREE_KEYS.filter(
    (k) => now >= (freeGeminiCircuits.get(k) || 0));
  if (!candidates.length) {
    throw new Error("free Gemini circuits open (quota breaker)");
  }
  let lastErr = null;
  for (const key of candidates) {
    try {
      return await fetchGeminiBatch(
        texts, geminiModel, outputDimensionality, fallbackModel, key);
    } catch (err) {
      lastErr = err;
      freeGeminiCircuits.set(key, Date.now() + FREE_GEMINI_CIRCUIT_MS);
      console.log(
        `free Gemini key ${keyTag(key)} failed ` +
        `(${String(err.message).slice(0, 80)}); circuit open ` +
        `${FREE_GEMINI_CIRCUIT_MS / 1000}s`);
      emitOpsEvent("embed_free_gemini_circuit",
        `Free Gemini key ${keyTag(key)} circuit OPEN for ` +
        `${FREE_GEMINI_CIRCUIT_MS / 1000}s — ` +
        `${String(err.message).slice(0, 200)} — next key / paid leg serving`);
    }
  }
  throw lastErr;
}

// Paid-Gemini leg with the spend firewall: only successful (billed)
// calls count; a cap-hit refuses before any API call is made.
async function fetchPaidGeminiBatch(texts, geminiModel, outputDimensionality) {
  const capped = paidCapHit();
  if (capped) {
    emitOpsEvent("embed_paid_cap",
      `Paid Gemini fallback ${capped} — paid leg skipped; embeds hard-fail ` +
      `until the window resets (today ${paidCallsToday}/${PAID_GEMINI_DAILY_CAP}, ` +
      `hour ${paidCallsThisHour}/${PAID_GEMINI_HOURLY_CAP})`);
    throw new Error(`paid Gemini ${capped}`);
  }
  const out = await fetchGeminiBatch(
    texts, geminiModel, outputDimensionality, null, GEMINI_API_KEY_PAID);
  paidCallBilled();
  return out;
}

async function fetchOllamaBatch(texts) {
  const resp = await fetch(`${OLLAMA_FALLBACK_BASE}/api/embed`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ model: OLLAMA_FALLBACK_MODEL, input: texts }),
  });
  if (!resp.ok) {
    const t = await resp.text();
    throw new Error(`Ollama fallback error: ${resp.status} - ${t}`);
  }
  const data = await resp.json();
  return data.embeddings || [];
}

async function fetchOpenRouterBatch(texts, orModel, outputDimensionality) {
  const resp = await fetch(`${OPENROUTER_BASE}/embeddings`, {
    method: "POST",
    headers: {
      "Content-Type": "application/json",
      Authorization: `Bearer ${OPENROUTER_API_KEY}`,
    },
    body: JSON.stringify({
      model: orModel,
      input: texts,
      dimensions: outputDimensionality,
      // OR's default Google AI Studio upstream rejects with a bogus
      // API_KEY_INVALID; the "Google" (Vertex) route works. No fallback
      // — a fallback hop lands back on the broken route.
      provider: { order: [OPENROUTER_PROVIDER], allow_fallbacks: false },
    }),
  });
  if (!resp.ok) {
    const t = await resp.text();
    throw new Error(`OpenRouter error: ${resp.status} - ${t.slice(0, 200)}`);
  }
  const data = await resp.json();
  const list = data.data || [];
  if (list.length !== texts.length) {
    throw new Error(`OpenRouter returned ${list.length}/${texts.length} embeddings`);
  }
  return list.map((entry) => entry.embedding);
}

async function fetchGatewayEmbedBatch(texts, outputDimensionality) {
  const resp = await fetch(`${EMBED_GATEWAY_BASE}/v1/embeddings`, {
    method: "POST",
    headers: {
      "Content-Type": "application/json",
      Authorization: `Bearer ${EMBED_GATEWAY_KEY}`,
    },
    body: JSON.stringify({
      model: EMBED_GATEWAY_MODEL,
      input: texts,
      dimensions: outputDimensionality,
    }),
  });
  if (!resp.ok) {
    const t = await resp.text();
    throw new Error(`Embed gateway error: ${resp.status} - ${t.slice(0, 200)}`);
  }
  const data = await resp.json();
  const list = data.data || [];
  if (list.length !== texts.length) {
    throw new Error(`Embed gateway returned ${list.length}/${texts.length} embeddings`);
  }
  return list.map((entry) => entry.embedding);
}

async function fetchBackupBatch(texts, geminiModel, outputDimensionality, skipGemini = false) {
  // Order: OpenRouter/gateway (Vertex gemini space) -> direct Gemini -> Ollama.
  // When OR is primary this whole chain is the normal path.
  if (OR_LEG_CONFIGURED) {
    const orModel = `${OPENROUTER_PREFIX}${geminiModel}`;
    const orLabel = EMBED_VIA_GATEWAY ? `litellm:${EMBED_GATEWAY_MODEL}` : orModel;
    const orCircuitOpen = Date.now() < orCircuitOpenUntil;
    const orCapped = orDailyCapHit();
    if (!orCircuitOpen && !orCapped) {
      console.log(`routing ${texts.length} input(s) via ${EMBED_VIA_GATEWAY ? "embed gateway" : "OpenRouter"} ${orLabel}`);
      try {
        const out = EMBED_VIA_GATEWAY
          ? await fetchGatewayEmbedBatch(texts, outputDimensionality)
          : await fetchOpenRouterBatch(texts, orModel, outputDimensionality);
        orCallsToday += 1;
        lastBackupProvider = orLabel;
        return out;
      } catch (err) {
        console.log(`${EMBED_VIA_GATEWAY ? "Embed gateway" : "OpenRouter"} failed (${String(err.message).slice(0, 80)})`);
        orCircuitOpenUntil = Date.now() + OR_CIRCUIT_COOLDOWN_MS;
        // Circuit closed->open transition (inside !orCircuitOpen branch):
        // a key/spend-cap failure pages now, not at the next probe tick.
        emitOpsEvent("embed_circuit_open",
          `OpenRouter embed circuit OPEN for ${OR_CIRCUIT_COOLDOWN_MS / 1000}s — ` +
          `${String(err.message).slice(0, 200)} — ` +
          `serving direct-Gemini fallback while it holds`);
      }
    }
    // Same-space fallback: embed-bench verified direct Gemini
    // gemini-embedding-2 is bit-identical (cosine 1.000) to the OR
    // Vertex route — safe to serve. Ollama stays refused (different
    // space). If no GEMINI_API_KEY, fall through to hard-fail.
    if (GEMINI_API_KEY) {
      try {
        const out = await fetchFreeGeminiBatch(
          texts, geminiModel, outputDimensionality, null);
        lastBackupProvider = `${geminiModel}-direct-fallback`;
        console.log(`served via direct Gemini fallback (${geminiModel}` +
          `${orCircuitOpen ? ", OR circuit open" : ""})`);
        return out;
      } catch (e2) {
        console.log(`direct Gemini fallback failed (${String(e2.message).slice(0, 80)})`);
      }
    }
    // Paid-Gemini leg: same model/vector space as free — strictly better
    // than the hard-fail below during a free-quota outage. Spend-bounded
    // by PAID_GEMINI_HOURLY_CAP / PAID_GEMINI_DAILY_CAP.
    if (GEMINI_API_KEY_PAID) {
      try {
        const out = await fetchPaidGeminiBatch(
          texts, geminiModel, outputDimensionality);
        lastBackupProvider = `${geminiModel}-paid`;
        console.log(`served via paid Gemini fallback (${geminiModel})`);
        return out;
      } catch (e3) {
        console.log(`paid Gemini fallback failed (${String(e3.message).slice(0, 80)})`);
      }
    }
    // Fail hard — wrong-space fallback is worse than surfacing the
    // failure to the caller.
    const orState = orCircuitOpen ? " circuit-open" : (orCapped ? ` daily-cap ${OR_FALLBACK_DAILY_CAP} hit` : "");
    const paidState = GEMINI_API_KEY_PAID && paidCapHit() ? ` + paid ${paidCapHit()}` : "";
    throw new Error(`all same-space providers down (OR${orState} + Gemini failed${paidState})`);
  }
  if (GEMINI_API_KEY && !skipGemini) {
    try {
      const out = await fetchFreeGeminiBatch(
        texts, geminiModel, outputDimensionality,
        GEMINI_EMBEDDING_FALLBACK_MODEL
      );
      lastBackupProvider = geminiModel;
      return out;
    } catch (err) {
      console.log(`backup Gemini failed (${String(err.message).slice(0, 80)})`);
    }
  }
  // Paid-Gemini leg: identical model + vector space as the free key, so
  // serving it during a free-quota outage keeps the index consistent —
  // strictly better than the different-space Ollama fallback below.
  // Bounded spend: PAID_GEMINI_HOURLY_CAP / PAID_GEMINI_DAILY_CAP.
  if (GEMINI_API_KEY_PAID) {
    try {
      const out = await fetchPaidGeminiBatch(
        texts, geminiModel, outputDimensionality);
      lastBackupProvider = `${geminiModel}-paid`;
      console.log(`served via paid Gemini fallback (${geminiModel})`);
      return out;
    } catch (err) {
      console.log(`paid Gemini failed (${String(err.message).slice(0, 80)})`);
    }
  }
  if (!OLLAMA_FALLBACK_BASE) {
    const paidState = GEMINI_API_KEY_PAID && paidCapHit()
      ? ` (paid ${paidCapHit()})` : "";
    throw new Error(`no backup embedding provider configured${paidState}`);
  }
  console.log(`embedding ${texts.length} input(s) via Ollama ${OLLAMA_FALLBACK_MODEL}`);
  lastBackupProvider = OLLAMA_FALLBACK_MODEL;
  return await fetchOllamaBatch(texts);
}

async function handleEmbed(req, res) {
  let raw = "";
  for await (const chunk of req) {
    raw += chunk.toString();
  }

  let payload;
  try {
    payload = JSON.parse(raw);
  } catch {
    return sendJson(res, 400, { error: "invalid JSON" });
  }

  const requestedModel = payload.model || "text-embedding-004";
  const geminiModel = resolveGeminiModel(requestedModel);

  let isSingle;
  let inputs;
  if (typeof payload.input === "string") {
    isSingle = true;
    inputs = [payload.input];
  } else if (Array.isArray(payload.input)) {
    isSingle = false;
    inputs = payload.input;
  } else if (typeof payload.prompt === "string") {
    isSingle = true;
    inputs = [payload.prompt];
  } else if (Array.isArray(payload.prompts)) {
    isSingle = false;
    inputs = payload.prompts;
  } else {
    return sendJson(res, 400, { error: "input must be a non-empty string or array of strings" });
  }
  if (!Array.isArray(inputs) || inputs.length === 0) {
    return sendJson(res, 400, { error: "input must be a non-empty string or array of strings" });
  }

  for (let i = 0; i < inputs.length; i++) {
    if (typeof inputs[i] !== "string" || inputs[i].trim().length === 0) {
      return sendJson(res, 400, { error: `input at index ${i} must be a non-empty string` });
    }
  }

  let outputDimensionality = payload.outputDimensionality;
  if (!outputDimensionality && payload.options && payload.options.outputDimensionality) {
    outputDimensionality = payload.options.outputDimensionality;
  }
  outputDimensionality = outputDimensionality
    ? parseInt(outputDimensionality, 10)
    : DEFAULT_DIMENSIONS;

  if (!OR_LEG_CONFIGURED && !GEMINI_API_KEY && !GEMINI_API_KEY_PAID) {
    return sendJson(res, 500, {
      error: "no embedding provider configured (set EMBED_GATEWAY_BASE, OPENROUTER_API_KEY or GEMINI_API_KEY)",
    });
  }

  const start = process.hrtime.bigint();
  const embeddings = [];
  let usedFallback = false;
  try {
    for (let i = 0; i < inputs.length; i += BATCH_SIZE) {
      const chunk = inputs.slice(i, i + BATCH_SIZE);
      let chunkEmbeddings;
      const circuitOpen =
        (OLLAMA_FALLBACK_BASE || OR_LEG_CONFIGURED) &&
        (Date.now() < geminiCircuitOpenUntil || freeGeminiCircuitOpen());
      if (OPENROUTER_API_KEY && OPENROUTER_PRIMARY) {
        // OpenRouter-primary: every request takes the backup chain, which
        // goes OR -> direct Gemini -> fatal. skipGemini is irrelevant
        // (unreachable) but kept explicit for readability.
        chunkEmbeddings = await fetchBackupBatch(
          chunk, geminiModel, outputDimensionality, true);
        usedFallback = true;
      } else if (circuitOpen) {
        chunkEmbeddings = await fetchBackupBatch(
          chunk, geminiModel, outputDimensionality, true);
        usedFallback = true;
      } else {
        try {
          chunkEmbeddings = await fetchFreeGeminiBatch(
            chunk,
            geminiModel,
            outputDimensionality,
            GEMINI_EMBEDDING_FALLBACK_MODEL
          );
        } catch (err) {
          if (!OLLAMA_FALLBACK_BASE && !OR_LEG_CONFIGURED) throw err;
          geminiCircuitOpenUntil = Date.now() + CIRCUIT_COOLDOWN_MS;
          console.log(
            `Gemini failed (${err.message.slice(0, 80)}); circuit open ${CIRCUIT_COOLDOWN_MS / 1000}s`
          );
          emitOpsEvent("embed_circuit_open",
            `Gemini embed circuit OPEN for ${CIRCUIT_COOLDOWN_MS / 1000}s — ` +
            `${String(err.message).slice(0, 200)} — routing to backup chain`);
          chunkEmbeddings = await fetchBackupBatch(
            chunk, geminiModel, outputDimensionality, true);
          usedFallback = true;
        }
      }
      embeddings.push(...chunkEmbeddings);
    }
  } catch (err) {
    consecutiveEmbedFailures++;
    embedFailuresTotal++;
    lastEmbedError = String(err.message).slice(0, 200);
    if (!alertedProvidersDown &&
        consecutiveEmbedFailures >= EMBED_FAIL_ALERT_AFTER) {
      // N consecutive dead requests = all same-space providers down
      // (cap-hit, quota outage). Once per episode; restored event re-arms.
      alertedProvidersDown = true;
      emitOpsEvent("embed_providers_down",
        `${consecutiveEmbedFailures} consecutive embed failures — ` +
        `last: ${lastEmbedError} — circuit or_open=${Date.now() < orCircuitOpenUntil} ` +
        `gemini_open=${Date.now() < geminiCircuitOpenUntil}`);
    }
    return sendJson(res, 502, { error: err.message });
  }
  if (alertedProvidersDown) {
    alertedProvidersDown = false;
    emitOpsEvent("embed_provider_restored",
      `embeds serving again after ${consecutiveEmbedFailures} consecutive ` +
      `failure(s) — provider=${usedFallback ? lastBackupProvider : geminiModel}`);
  }
  consecutiveEmbedFailures = 0;
  embedOkTotal++;
  const end = process.hrtime.bigint();
  const durationMs = Number((end - start) / 1000000n);

  const result = {
    model: requestedModel,
    gemini_model: geminiModel,
    provider: usedFallback ? lastBackupProvider : geminiModel,
    fallback: usedFallback ? lastBackupProvider : null,
    output_dimensionality: outputDimensionality,
    duration_ms: durationMs,
    embeddings: embeddings,
  };
  if (isSingle) {
    result.embedding = embeddings[0];
  }

  sendJson(res, 200, result);
}

const server = createServer((req, res) => {
  if (req.method === "OPTIONS") {
    res.writeHead(204, {
      "Access-Control-Allow-Origin": "*",
      "Access-Control-Allow-Methods": "GET, POST, OPTIONS",
      "Access-Control-Allow-Headers": "Content-Type",
    });
    res.end();
    return;
  }

  if (req.method === "GET" && req.url === "/health") {
    return sendJson(res, 200, {
      status: "ok",
      gemini_model: GEMINI_EMBEDDING_MODEL,
      dimensions: DEFAULT_DIMENSIONS,
      ollama_fallback: OLLAMA_FALLBACK_BASE ? OLLAMA_FALLBACK_MODEL : null,
      provider_mode: OR_LEG_CONFIGURED
        ? (OPENROUTER_API_KEY && OPENROUTER_PRIMARY ? "openrouter-primary" : "gemini-primary")
        : "gemini-only",
      embed_gateway: EMBED_VIA_GATEWAY ? EMBED_GATEWAY_MODEL : null,
      circuit: {
        or_open: Date.now() < orCircuitOpenUntil,
        gemini_open: Date.now() < geminiCircuitOpenUntil,
        free_gemini_open: freeGeminiCircuitOpen(),
        free_keys: GEMINI_FREE_KEYS.length,
        or_daily_cap: OR_FALLBACK_DAILY_CAP || null,
        or_calls_today: orCallsToday,
        paid_daily_cap: PAID_GEMINI_DAILY_CAP || null,
        paid_calls_today: paidCallsToday,
        paid_hourly_cap: PAID_GEMINI_HOURLY_CAP || null,
        paid_calls_hour: paidCallsThisHour,
      },
      embed: {
        consecutive_failures: consecutiveEmbedFailures,
        failures_total: embedFailuresTotal,
        ok_total: embedOkTotal,
        last_error: lastEmbedError,
      },
      last_backup_provider: lastBackupProvider,
    });
  }

  if (req.method === "POST" && (req.url === "/api/embed" || req.url === "/api/embeddings")) {
    return handleEmbed(req, res);
  }

  sendJson(res, 404, { error: "not found" });
});

server.listen(PORT, HOST, () => {
  console.log(`Gemini-Ollama proxy listening on http://${HOST}:${PORT}`);
});

// PID-1 in the podman container: SIGTERM is only delivered to PID 1 when a
// handler is registered — without this, every unit stop waited out the 10s
// timeout then SIGKILLed, logging "Failed with result exit-code".
for (const sig of ["SIGTERM", "SIGINT"]) {
  process.on(sig, () => {
    server.close(() => process.exit(0));
    setTimeout(() => process.exit(0), 2000).unref();
  });
}
