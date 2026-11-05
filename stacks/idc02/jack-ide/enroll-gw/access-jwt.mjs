import { createPublicKey, verify } from "node:crypto";

const JWKS_TTL_MS = 15 * 60 * 1000;
const jwksCache = new Map();

function decodeJson(segment) {
  return JSON.parse(Buffer.from(segment, "base64url").toString("utf8"));
}

async function loadJwks(url, fetchImpl, nowMs, force = false) {
  const cached = jwksCache.get(url);
  if (!force && cached && cached.expiresAt > nowMs) return cached.keys;

  const response = await fetchImpl(url, {
    headers: { accept: "application/json" },
    signal: AbortSignal.timeout(5000),
  });
  if (!response.ok) throw new Error(`Cloudflare JWKS request failed: ${response.status}`);

  const document = await response.json();
  if (!Array.isArray(document.keys)) throw new Error("Cloudflare JWKS has no keys");
  jwksCache.set(url, { keys: document.keys, expiresAt: nowMs + JWKS_TTL_MS });
  return document.keys;
}

export async function verifyCloudflareAccessJwt(
  token,
  {
    issuer,
    audience,
    jwksUrl,
    nowMs = Date.now(),
    fetchImpl = globalThis.fetch,
  } = {},
) {
  if (
    typeof token !== "string" ||
    token.length > 16_384 ||
    !issuer ||
    !audience ||
    !jwksUrl ||
    typeof fetchImpl !== "function"
  ) {
    return false;
  }

  const parts = token.split(".");
  if (parts.length !== 3) return false;

  try {
    const header = decodeJson(parts[0]);
    const claims = decodeJson(parts[1]);
    if (header.alg !== "RS256" || typeof header.kid !== "string") return false;
    if (claims.iss !== issuer) return false;
    const audiences = Array.isArray(claims.aud) ? claims.aud : [claims.aud];
    if (!audiences.includes(audience)) return false;

    const nowSeconds = Math.floor(nowMs / 1000);
    if (!Number.isFinite(claims.exp) || claims.exp <= nowSeconds) return false;
    if (Number.isFinite(claims.nbf) && claims.nbf > nowSeconds + 30) return false;
    if (Number.isFinite(claims.iat) && claims.iat > nowSeconds + 60) return false;

    let keys = await loadJwks(jwksUrl, fetchImpl, nowMs);
    let jwk = keys.find((key) => key.kid === header.kid);
    if (!jwk) {
      keys = await loadJwks(jwksUrl, fetchImpl, nowMs, true);
      jwk = keys.find((key) => key.kid === header.kid);
    }
    if (!jwk || jwk.kty !== "RSA") return false;

    const publicKey = createPublicKey({ key: jwk, format: "jwk" });
    const signed = Buffer.from(`${parts[0]}.${parts[1]}`);
    const signature = Buffer.from(parts[2], "base64url");
    return verify("RSA-SHA256", signed, publicKey, signature);
  } catch {
    return false;
  }
}
