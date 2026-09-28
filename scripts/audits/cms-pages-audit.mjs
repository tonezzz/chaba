#!/usr/bin/env node
/*
 * Ada CMS page structure and naming audit.
 * Validates every document in the MDDB `ada-cms-pages` collection against the
 * page contract enforced by ada-pi's cms_* tools (backend/tool_runner.py):
 *   - slug (= doc key): ^[a-z0-9][a-z0-9_-]{0,63}$, convention prefers hyphens
 *   - meta.kind includes "page" (required for cms_list_pages visibility)
 *   - meta.slug matches the doc key
 *   - meta.title non-empty
 *   - meta.format in {markdown, html, yaml, slides}
 *   - meta.updated is a parseable ISO timestamp
 *   - content non-empty
 * Live read-only probe — never writes.
 */
import http from "http";
import { URL } from "url";

const MDDB_BASE = process.env.MDDB_BASE || "http://100.74.146.0:11023";
const COLLECTION = process.env.CMS_COLLECTION || "ada-cms-pages";
const LIMIT = 500;
const MAX_RESPONSE_MS = 5000;

const SLUG_RE = /^[a-z0-9][a-z0-9_-]{0,63}$/;
const VALID_FORMATS = new Set(["markdown", "html", "yaml", "slides"]);
const REQUIRED_META = ["slug", "title", "format", "updated"];

const issues = [];
const warns = [];
const notes = [];

function issue(msg) {
  issues.push(msg);
}
function warn(msg) {
  warns.push(msg);
}
function note(msg) {
  notes.push(msg);
}

function postJson(url, payload, timeoutMs = 20000) {
  return new Promise((resolve, reject) => {
    const u = new URL(url);
    const data = JSON.stringify(payload);
    const start = Date.now();
    const req = http.request(
      {
        hostname: u.hostname,
        port: u.port || 80,
        path: u.pathname + u.search,
        method: "POST",
        headers: {
          "Content-Type": "application/json",
          "Content-Length": Buffer.byteLength(data),
        },
        timeout: timeoutMs,
      },
      (res) => {
        let out = "";
        res.setEncoding("utf8");
        res.on("data", (c) => {
          out += c;
        });
        res.on("end", () => {
          if (res.statusCode !== 200) {
            reject(new Error(`HTTP ${res.statusCode}: ${out.slice(0, 200)}`));
            return;
          }
          try {
            resolve({ body: out ? JSON.parse(out) : null, durationMs: Date.now() - start });
          } catch (e) {
            reject(new Error(`Invalid JSON from ${url}: ${e.message}`));
          }
        });
      }
    );
    req.on("error", reject);
    req.on("timeout", () => {
      req.destroy();
      reject(new Error("timeout"));
    });
    req.write(data);
    req.end();
  });
}

function metaFirst(meta, key) {
  const v = meta?.[key];
  if (Array.isArray(v)) return v.length ? String(v[0]) : null;
  return typeof v === "string" ? v : null;
}

function metaHas(meta, key, val) {
  const v = meta?.[key];
  return Array.isArray(v) ? v.includes(val) : v === val;
}

function checkDoc(doc) {
  const key = doc.key || "(no key)";
  const meta = doc.meta || {};
  const where = `page ${JSON.stringify(key)}`;

  // Naming convention: the doc key IS the slug.
  if (!SLUG_RE.test(key)) {
    issue(`${where}: slug violates ^[a-z0-9][a-z0-9_-]{0,63}$`);
  } else if (key.includes("_")) {
    warn(`${where}: slug uses '_' — convention prefers '-'`); // cosmetic only
  }

  // Required meta contract.
  for (const field of REQUIRED_META) {
    if (!metaFirst(meta, field)) {
      issue(`${where}: missing meta.${field}`);
    }
  }
  if (!metaHas(meta, "kind", "page")) {
    warn(`${where}: meta.kind != "page" — invisible to cms_list_pages`);
  }

  const slugMeta = metaFirst(meta, "slug");
  if (slugMeta && slugMeta !== key) {
    issue(`${where}: meta.slug ${JSON.stringify(slugMeta)} != doc key`);
  }

  const fmt = metaFirst(meta, "format");
  if (fmt && !VALID_FORMATS.has(fmt)) {
    issue(
      `${where}: format ${JSON.stringify(fmt)} not in {${[...VALID_FORMATS].join(", ")}}`
    );
  }

  const updated = metaFirst(meta, "updated");
  if (updated && Number.isNaN(Date.parse(updated))) {
    issue(`${where}: meta.updated ${JSON.stringify(updated)} is not a valid timestamp`);
  }

  const content = doc.contentMd ?? doc.content ?? "";
  if (!String(content).trim()) {
    issue(`${where}: empty content`);
  }

  return { key, ok: true };
}

async function main() {
  const { body, durationMs } = await postJson(`${MDDB_BASE}/v1/search`, {
    collection: COLLECTION,
    limit: LIMIT,
  }).catch((e) => {
    issue(`MDDB /v1/search ${COLLECTION} unreachable at ${MDDB_BASE}: ${e.message}`);
    return { body: null, durationMs: 0 };
  });

  if (body) {
    if (durationMs > MAX_RESPONSE_MS) {
      warn(`collection listing slow: ${durationMs}ms`);
    }
    if (!Array.isArray(body)) {
      issue(`unexpected /v1/search response shape (not an array)`);
    } else {
      note(`${COLLECTION}: ${body.length} document(s) (${durationMs}ms)`);
      let bad = 0;
      const before = issues.length + warns.length;
      for (const doc of body) checkDoc(doc);
      bad = issues.length + warns.length - before;
      if (bad === 0) note("all pages satisfy the structure + naming contract");
      if (body.length >= LIMIT) {
        warn(`listing hit LIMIT=${LIMIT} — collection may be truncated, raise it`);
      }
    }
  }

  const result = {
    ok: issues.length === 0,
    generated: new Date().toISOString(),
    mddb: MDDB_BASE,
    collection: COLLECTION,
    issues,
    warns,
    notes,
    total_issues: issues.length,
    total_warns: warns.length,
    total_notes: notes.length,
  };
  console.log(JSON.stringify(result, null, 2));
  process.exit(result.ok ? 0 : 1);
}

main().catch((e) => {
  console.error(JSON.stringify({ ok: false, error: e.message, stack: e.stack }));
  process.exit(1);
});
