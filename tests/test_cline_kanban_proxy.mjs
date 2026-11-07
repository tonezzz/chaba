import assert from "node:assert/strict";
import { generateKeyPairSync, sign } from "node:crypto";
import { existsSync, readFileSync } from "node:fs";
import test from "node:test";
import {
  getExternalRequestRejection,
  isAllowedExternalRequest,
  isValidBasicAuthorization,
  rewriteDownstreamHeaders,
  rewriteUpstreamHeaders,
} from "../stacks/con01/cline-kanban/proxy-policy.mjs";
import { verifyCloudflareAccessJwt } from "../stacks/con01/cline-kanban/access-jwt.mjs";

const testPasscode = "example-pilot-passcode-123456";
const goodHeaders = {
  host: "100.72.146.39:3484",
  origin: "http://100.72.146.39:3484",
  authorization: `Basic ${Buffer.from(`cline:${testPasscode}`).toString("base64")}`,
};
const options = { passcode: testPasscode };

test("accepts the exact tailnet host and same-origin browser request", () => {
  assert.equal(isAllowedExternalRequest(goodHeaders, "POST", options), true);
});

test("rejects bad host, cross-origin requests, and missing Basic Auth", () => {
  assert.equal(
    isAllowedExternalRequest(
      { ...goodHeaders, host: "attacker.example:3484" },
      "GET",
      options,
    ),
    false,
  );
  assert.equal(
    isAllowedExternalRequest(
      { ...goodHeaders, origin: "https://attacker.example" },
      "POST",
      options,
    ),
    false,
  );
  assert.equal(
    getExternalRequestRejection(
      { ...goodHeaders, authorization: undefined },
      "GET",
      options,
    ),
    "auth",
  );
});

test("allows originless navigation only for safe methods", () => {
  assert.equal(
    isAllowedExternalRequest(
      { host: goodHeaders.host, authorization: goodHeaders.authorization },
      "GET",
      options,
    ),
    true,
  );
  assert.equal(
    isAllowedExternalRequest(
      { host: goodHeaders.host, authorization: goodHeaders.authorization },
      "POST",
      options,
    ),
    false,
  );
  assert.equal(
    isAllowedExternalRequest(
      { host: goodHeaders.host, authorization: goodHeaders.authorization },
      "GET",
      { ...options, upgrade: true },
    ),
    false,
  );
});

test("validates Basic Auth without exposing its header upstream", () => {
  assert.equal(
    isValidBasicAuthorization(goodHeaders.authorization, testPasscode),
    true,
  );
  assert.equal(
    isValidBasicAuthorization(goodHeaders.authorization, "wrong-passcode"),
    false,
  );
  assert.equal(
    Object.hasOwn(rewriteUpstreamHeaders(goodHeaders), "authorization"),
    false,
  );
});

test("rewrites the upstream Host and Origin", () => {
  assert.deepEqual(rewriteUpstreamHeaders(goodHeaders), {
    host: "0.0.0.0:3485",
    origin: "http://0.0.0.0:3485",
  });
});

test("rewrites backend absolute URLs and CORS origin to the trusted URL", () => {
  assert.deepEqual(
    rewriteDownstreamHeaders({
      location: "http://0.0.0.0:3485/workspace",
      "access-control-allow-origin": "http://0.0.0.0:3485",
      "content-type": "text/html",
    }),
    {
      location: "http://100.72.146.39:3484/workspace",
      "access-control-allow-origin": "http://100.72.146.39:3484",
      "content-type": "text/html",
    },
  );
});

test("allows only same-origin public requests with a verified Access JWT", () => {
  const publicHeaders = {
    host: "cline.surf-thailand.com",
    origin: "https://cline.surf-thailand.com",
  };
  const publicOptions = {
    ...options,
    publicHost: "cline.surf-thailand.com",
    publicOrigin: "https://cline.surf-thailand.com",
  };
  assert.equal(
    getExternalRequestRejection(publicHeaders, "GET", {
      ...publicOptions,
      accessJwtValid: true,
    }),
    null,
  );
  assert.equal(
    getExternalRequestRejection(publicHeaders, "GET", publicOptions),
    "access",
  );
  assert.equal(
    getExternalRequestRejection(
      { ...publicHeaders, origin: "https://attacker.example" },
      "POST",
      { ...publicOptions, accessJwtValid: true },
    ),
    "origin",
  );
});

test("strips Cloudflare Access credentials before forwarding to the agent", () => {
  const rewritten = rewriteUpstreamHeaders({
    ...goodHeaders,
    "cf-access-jwt-assertion": "signed-access-token",
    "cf-access-authenticated-user-email": "operator@example.test",
    cookie: "CF_Authorization=access-cookie; cline_session=ok; CF_AppSession=app-cookie",
  });
  assert.equal(Object.hasOwn(rewritten, "authorization"), false);
  assert.equal(Object.hasOwn(rewritten, "cf-access-jwt-assertion"), false);
  assert.equal(Object.hasOwn(rewritten, "cf-access-authenticated-user-email"), false);
  assert.equal(rewritten.cookie, "cline_session=ok");
});

test("verifies Cloudflare Access JWT signature, issuer, audience, and time claims", async () => {
  const { privateKey, publicKey } = generateKeyPairSync("rsa", {
    modulusLength: 2048,
  });
  const jwksUrl = `https://jwks.test/${Date.now()}-${Math.random()}`;
  const jwk = {
    ...publicKey.export({ format: "jwk" }),
    kid: "test-kid",
    alg: "RS256",
    use: "sig",
  };
  const fetchImpl = async () => ({
    ok: true,
    json: async () => ({ keys: [jwk] }),
  });
  const nowSeconds = Math.floor(Date.now() / 1000);
  const makeToken = (claims, signingKey = privateKey) => {
    const encode = (value) => Buffer.from(JSON.stringify(value)).toString("base64url");
    const header = encode({ alg: "RS256", kid: "test-kid", typ: "JWT" });
    const payload = encode(claims);
    const input = `${header}.${payload}`;
    const signature = sign("RSA-SHA256", Buffer.from(input), signingKey).toString("base64url");
    return `${input}.${signature}`;
  };
  const options = {
    issuer: "https://chaba-team.cloudflareaccess.com",
    audience: "cline-app-audience",
    jwksUrl,
    nowMs: nowSeconds * 1000,
    fetchImpl,
  };
  const claims = {
    iss: options.issuer,
    aud: [options.audience],
    iat: nowSeconds,
    nbf: nowSeconds - 1,
    exp: nowSeconds + 300,
  };

  assert.equal(await verifyCloudflareAccessJwt(makeToken(claims), options), true);
  assert.equal(
    await verifyCloudflareAccessJwt(
      makeToken({ ...claims, aud: ["wrong-audience"] }),
      options,
    ),
    false,
  );
  assert.equal(
    await verifyCloudflareAccessJwt(
      makeToken({ ...claims, exp: nowSeconds - 1 }),
      options,
    ),
    false,
  );
  const other = generateKeyPairSync("rsa", { modulusLength: 2048 });
  assert.equal(
    await verifyCloudflareAccessJwt(makeToken(claims, other.privateKey), options),
    false,
  );
});

test("keeps the proxy credential out of the Cline agent container", () => {
  const app = readFileSync(
    new URL("../stacks/con01/cline-kanban/cline-kanban.container", import.meta.url),
    "utf8",
  );
  const proxy = readFileSync(
    new URL("../stacks/con01/cline-kanban/cline-kanban-proxy.container", import.meta.url),
    "utf8",
  );
  const proxySource = readFileSync(
    new URL("../stacks/con01/cline-kanban/proxy.mjs", import.meta.url),
    "utf8",
  );
  const entrypoint = readFileSync(
    new URL("../stacks/con01/cline-kanban/entrypoint.sh", import.meta.url),
    "utf8",
  );
  const network = readFileSync(
    new URL("../stacks/con01/cline-kanban/cline-kanban.network", import.meta.url),
    "utf8",
  );
  const containerfile = readFileSync(
    new URL("../stacks/con01/cline-kanban/Containerfile", import.meta.url),
    "utf8",
  );
  const caddyRoute = readFileSync(
    new URL("../stacks/idc02/cline.surf-thailand.com.caddy", import.meta.url),
    "utf8",
  );

  assert.match(app, /Environment=CLINE_ROLE=app/);
  assert.match(app, /Network=cline-kanban\.network/);
  assert.doesNotMatch(app, /EnvironmentFile=/);
  assert.doesNotMatch(app, /PublishPort=/);
  assert.doesNotMatch(app, /Pod=/);
  assert.match(entrypoint, /kanban --host 0\.0\.0\.0 --port 3485/);
  assert.match(entrypoint, /--skip-shutdown-cleanup/);
  assert.match(proxy, /Environment=CLINE_ROLE=proxy/);
  assert.match(proxy, /Network=cline-kanban\.network/);
  assert.match(proxy, /EnvironmentFile=%h\/\.config\/secrets\/cline-kanban\.env/);
  assert.match(proxy, /Environment=CLINE_PUBLIC_HOST=cline\.surf-thailand\.com/);
  assert.match(proxy, /Environment=CLINE_CF_ACCESS_AUD=/);
  assert.doesNotMatch(proxy, /Volume=.*\.local\/share\/cline-kanban\/data/);
  assert.match(proxy, /PublishPort=100\.72\.146\.39:3484:3484\/tcp/);
  assert.doesNotMatch(proxy, /Pod=/);
  assert.match(containerfile, /COPY .*access-jwt\.mjs/);
  assert.match(network, /NetworkName=cline-kanban/);
  assert.match(proxySource, /BACKEND_HOST = "cline-kanban"/);
  assert.match(caddyRoute, /cline\.surf-thailand\.com/);
  assert.match(caddyRoute, /reverse_proxy http:\/\/100\.72\.146\.39:3484/);
  assert.match(caddyRoute, /Cf-Access-Jwt-Assertion/);
  assert.doesNotMatch(caddyRoute, /header_up Authorization/);
  assert.equal(
    existsSync(new URL("../stacks/con01/cline-kanban/cline-kanban.pod", import.meta.url)),
    false,
  );
});
