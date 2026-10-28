import assert from "node:assert/strict";
import { existsSync, readFileSync } from "node:fs";
import test from "node:test";
import {
  getExternalRequestRejection,
  isAllowedExternalRequest,
  isValidBasicAuthorization,
  rewriteDownstreamHeaders,
  rewriteUpstreamHeaders,
} from "../stacks/con01/cline-kanban/proxy-policy.mjs";

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
  assert.doesNotMatch(proxy, /Volume=.*\.local\/share\/cline-kanban\/data/);
  assert.match(proxy, /PublishPort=100\.72\.146\.39:3484:3484\/tcp/);
  assert.doesNotMatch(proxy, /Pod=/);
  assert.match(network, /NetworkName=cline-kanban/);
  assert.match(proxySource, /BACKEND_HOST = "cline-kanban"/);
  assert.equal(
    existsSync(new URL("../stacks/con01/cline-kanban/cline-kanban.pod", import.meta.url)),
    false,
  );
});
