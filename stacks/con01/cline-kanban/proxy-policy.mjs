const SAFE_METHODS = new Set(["GET", "HEAD", "OPTIONS"]);

export function isAllowedExternalRequest(
  headers,
  method,
  {
    externalHost = "100.72.146.39:3484",
    externalOrigin = "http://100.72.146.39:3484",
    upgrade = false,
  } = {},
) {
  if (String(headers.host || "").toLowerCase() !== externalHost.toLowerCase()) {
    return false;
  }

  const origin = headers.origin;
  if (typeof origin !== "string" || !origin) {
    return !upgrade && SAFE_METHODS.has(String(method || "").toUpperCase());
  }
  return origin === externalOrigin;
}

export function rewriteUpstreamHeaders(headers) {
  const rewritten = { ...headers, host: "0.0.0.0:3485" };
  if (headers.origin) {
    rewritten.origin = "http://0.0.0.0:3485";
  }
  return rewritten;
}

export function rewriteDownstreamHeaders(headers) {
  const rewritten = { ...headers };
  if (
    typeof rewritten.location === "string" &&
    rewritten.location.startsWith("http://0.0.0.0:3485")
  ) {
    rewritten.location = rewritten.location.replace(
      "http://0.0.0.0:3485",
      "http://100.72.146.39:3484",
    );
  }
  if (rewritten["access-control-allow-origin"] === "http://0.0.0.0:3485") {
    rewritten["access-control-allow-origin"] = "http://100.72.146.39:3484";
  }
  return rewritten;
}
