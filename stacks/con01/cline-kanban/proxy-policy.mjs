import { timingSafeEqual } from "node:crypto";

const SAFE_METHODS = new Set(["GET", "HEAD", "OPTIONS"]);

export function isValidBasicAuthorization(header, passcode, username = "cline") {
  const match = /^Basic\s+([A-Za-z0-9+/]+=*)$/i.exec(String(header || ""));
  if (!match || !passcode) return false;
  const actual = Buffer.from(match[1], "base64");
  const expected = Buffer.from(`${username}:${passcode}`);
  if (actual.length !== expected.length) return false;
  return timingSafeEqual(actual, expected);
}

export function getExternalRequestRejection(
  headers,
  method,
  options = {},
) {
  const {
    externalHost = "100.72.146.39:3484",
    externalOrigin = "http://100.72.146.39:3484",
    passcode = "",
    upgrade = false,
  } = options;

  if (String(headers.host || "").toLowerCase() !== externalHost.toLowerCase()) {
    return "host";
  }

  const origin = headers.origin;
  if (typeof origin !== "string" || !origin) {
    if (upgrade || !SAFE_METHODS.has(String(method || "").toUpperCase())) {
      return "origin";
    }
  } else if (origin !== externalOrigin) {
    return "origin";
  }

  if (!isValidBasicAuthorization(headers.authorization, passcode)) {
    return "auth";
  }
  return null;
}

export function isAllowedExternalRequest(
  headers,
  method,
  options = {},
) {
  return getExternalRequestRejection(headers, method, options) === null;
}

export function rewriteUpstreamHeaders(headers) {
  const rewritten = { ...headers, host: "127.0.0.1:3485" };
  delete rewritten.authorization;
  if (headers.origin) {
    rewritten.origin = "http://127.0.0.1:3485";
  }
  return rewritten;
}

export function rewriteDownstreamHeaders(headers) {
  const rewritten = { ...headers };
  if (
    typeof rewritten.location === "string" &&
    rewritten.location.startsWith("http://127.0.0.1:3485")
  ) {
    rewritten.location = rewritten.location.replace(
      "http://127.0.0.1:3485",
      "http://100.72.146.39:3484",
    );
  }
  if (rewritten["access-control-allow-origin"] === "http://127.0.0.1:3485") {
    rewritten["access-control-allow-origin"] = "http://100.72.146.39:3484";
  }
  return rewritten;
}
