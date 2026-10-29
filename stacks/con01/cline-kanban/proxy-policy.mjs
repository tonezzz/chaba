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
    publicHost = "",
    publicOrigin = "",
    passcode = "",
    accessJwtValid = false,
    upgrade = false,
  } = options;

  const host = String(headers.host || "").toLowerCase();
  const isPublic = Boolean(publicHost) && host === publicHost.toLowerCase();
  const isTailnet = host === externalHost.toLowerCase();
  if (!isPublic && !isTailnet) {
    return "host";
  }

  const origin = headers.origin;
  const expectedOrigin = isPublic ? publicOrigin : externalOrigin;
  if (typeof origin !== "string" || !origin) {
    if (upgrade || !SAFE_METHODS.has(String(method || "").toUpperCase())) {
      return "origin";
    }
  } else if (origin !== expectedOrigin) {
    return "origin";
  }

  if (isPublic) return accessJwtValid ? null : "access";
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
  const rewritten = { ...headers, host: "0.0.0.0:3485" };
  delete rewritten.authorization;
  for (const name of Object.keys(rewritten)) {
    if (name.toLowerCase().startsWith("cf-access-")) delete rewritten[name];
  }
  if (typeof rewritten.cookie === "string") {
    const cookies = rewritten.cookie
      .split(/;\s*/)
      .filter((cookie) => {
        const name = cookie.split("=", 1)[0].trim();
        return !/^cf_(?:authorization|appsession|access_.*)$/i.test(name);
      });
    if (cookies.length) rewritten.cookie = cookies.join("; ");
    else delete rewritten.cookie;
  }
  if (headers.origin) {
    rewritten.origin = "http://0.0.0.0:3485";
  }
  return rewritten;
}

export function rewriteDownstreamHeaders(
  headers,
  externalOrigin = "http://100.72.146.39:3484",
) {
  const rewritten = { ...headers };
  if (
    typeof rewritten.location === "string" &&
    rewritten.location.startsWith("http://0.0.0.0:3485")
  ) {
    rewritten.location = rewritten.location.replace(
      "http://0.0.0.0:3485",
      externalOrigin,
    );
  }
  if (rewritten["access-control-allow-origin"] === "http://0.0.0.0:3485") {
    rewritten["access-control-allow-origin"] = externalOrigin;
  }
  return rewritten;
}
