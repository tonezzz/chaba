import assert from "node:assert/strict";
import test from "node:test";
import {
  isAllowedExternalRequest,
  rewriteDownstreamHeaders,
  rewriteUpstreamHeaders,
} from "../stacks/con01/cline-kanban/proxy-policy.mjs";

const goodHeaders = {
  host: "100.72.146.39:3484",
  origin: "http://100.72.146.39:3484",
};

test("accepts the exact tailnet host and same-origin browser request", () => {
  assert.equal(isAllowedExternalRequest(goodHeaders, "POST"), true);
});

test("rejects unknown hosts and cross-origin requests", () => {
  assert.equal(
    isAllowedExternalRequest(
      { ...goodHeaders, host: "attacker.example:3484" },
      "GET",
    ),
    false,
  );
  assert.equal(
    isAllowedExternalRequest(
      { ...goodHeaders, origin: "https://attacker.example" },
      "POST",
    ),
    false,
  );
});

test("allows originless navigation only for safe methods", () => {
  assert.equal(
    isAllowedExternalRequest({ host: goodHeaders.host }, "GET"),
    true,
  );
  assert.equal(
    isAllowedExternalRequest({ host: goodHeaders.host }, "POST"),
    false,
  );
  assert.equal(
    isAllowedExternalRequest({ host: goodHeaders.host }, "GET", { upgrade: true }),
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
