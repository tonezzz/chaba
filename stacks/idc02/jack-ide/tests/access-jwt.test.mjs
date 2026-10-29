import { test } from "node:test";
import assert from "node:assert/strict";
import { generateKeyPairSync, sign } from "node:crypto";
import { verifyCloudflareAccessJwt } from "../enroll-gw/access-jwt.mjs";

const ISSUER = "https://chaba-team.cloudflareaccess.com";
const AUDIENCE = "jack-audience";
const JWKS_URL = "https://example.test/certs";
const { privateKey, publicKey } = generateKeyPairSync("rsa", { modulusLength: 2048 });
const jwk = { ...publicKey.export({ format: "jwk" }), kid: "jack-test", alg: "RS256", use: "sig" };

function token(claims = {}) {
  const header = Buffer.from(JSON.stringify({ alg: "RS256", typ: "JWT", kid: "jack-test" })).toString("base64url");
  const payload = Buffer.from(JSON.stringify({
    iss: ISSUER,
    aud: AUDIENCE,
    iat: 1_700_000_000,
    exp: 1_700_000_600,
    ...claims,
  })).toString("base64url");
  const signed = `${header}.${payload}`;
  const signature = sign("RSA-SHA256", Buffer.from(signed), privateKey).toString("base64url");
  return `${signed}.${signature}`;
}

const options = (fetchImpl, jwksUrl = JWKS_URL) => ({
  issuer: ISSUER,
  audience: AUDIENCE,
  jwksUrl,
  nowMs: 1_700_000_100_000,
  fetchImpl,
});

const fetchJwks = async () => new Response(JSON.stringify({ keys: [jwk] }), {
  status: 200,
  headers: { "content-type": "application/json" },
});

test("accepts a valid Cloudflare Access JWT", async () => {
  assert.equal(await verifyCloudflareAccessJwt(token(), options(fetchJwks)), true);
});

test("rejects wrong audience, issuer, and expired claims", async () => {
  assert.equal(await verifyCloudflareAccessJwt(token({ aud: "other" }), options(fetchJwks)), false);
  assert.equal(await verifyCloudflareAccessJwt(token({ iss: "https://other.test" }), options(fetchJwks)), false);
  assert.equal(await verifyCloudflareAccessJwt(token({ exp: 1_699_999_999 }), options(fetchJwks)), false);
});

test("rejects malformed tokens and unavailable JWKS", async () => {
  assert.equal(await verifyCloudflareAccessJwt("not-a-jwt", options(fetchJwks)), false);
  assert.equal(
    await verifyCloudflareAccessJwt(token(), options(
      async () => new Response("no", { status: 503 }),
      "https://example.test/unavailable",
    )),
    false,
  );
});
