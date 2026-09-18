#!/usr/bin/env node
/*
 * Doc links audit.
 * Verifies that markdown links in docs/INDEX.md and docs/runbooks/*.md,
 * `related:` frontmatter paths in runbooks, and path/related entries in
 * the runbook registry (ssot.runbooks.yml) resolve to real files.
 */
import { readFileSync, readdirSync, existsSync } from "fs";
import { join, dirname, relative } from "path";
import yaml from "js-yaml";

const PROJECT_ROOT = new URL("../../", import.meta.url).pathname.replace(/\/$/, "");
const DOCS_DIR = join(PROJECT_ROOT, "docs");
const RUNBOOKS_DIR = join(DOCS_DIR, "runbooks");
const REGISTRY = join(DOCS_DIR, "ssot", "ssot.runbooks.yml");
const INDEX = join(DOCS_DIR, "INDEX.md");

// repo-relative path prefixes that `related:` entries are expected to use
const RELATED_PREFIX = /^(docs|scripts|systemd|stacks)\/[\w./-]+/;

function markdownLinks(text) {
  const out = [];
  const re = /\[[^\]]*\]\(([^)\s]+)[^)]*\)/g;
  let m;
  while ((m = re.exec(text)) !== null) {
    const t = m[1];
    if (/^(https?:|mailto:|#)/.test(t)) continue;
    out.push(t.split("#")[0]);
  }
  return out;
}

function frontmatterRelated(text) {
  const fm = text.match(/^---\r?\n([\s\S]*?)\r?\n---/);
  if (!fm) return [];
  const out = [];
  // block/flow list items: "- docs/x" or "docs/x," on their own line
  for (const m of fm[1].matchAll(/^\s+-?\s*([A-Za-z0-9_./-]+)\s*[,\]]?\s*(#.*)?$/gm)) {
    const p = m[1];
    if (RELATED_PREFIX.test(p)) out.push(p);
  }
  // single-line flow style: related: [a, b, c]
  const inline = fm[1].match(/^related:\s*\[([^\]]+)\]/m);
  if (inline) {
    for (const p of inline[1].split(",")) {
      const t = p.trim();
      if (RELATED_PREFIX.test(t)) out.push(t);
    }
  }
  return out;
}

function checkMarkdownFile(file) {
  const issues = [];
  const rel = relative(PROJECT_ROOT, file);
  const text = readFileSync(file, "utf8");
  for (const link of markdownLinks(text)) {
    if (!existsSync(join(dirname(file), link))) {
      issues.push(`${rel}: broken link ${link}`);
    }
  }
  for (const p of frontmatterRelated(text)) {
    if (!existsSync(join(PROJECT_ROOT, p))) {
      issues.push(`${rel}: related path missing ${p}`);
    }
  }
  return issues;
}

function checkRegistry(file) {
  const issues = [];
  if (!existsSync(file)) return [`missing registry: ${relative(PROJECT_ROOT, file)}`];
  const doc = yaml.load(readFileSync(file, "utf8")) || {};
  for (const [name, entry] of Object.entries(doc.runbooks || {})) {
    if (!entry || typeof entry !== "object") continue;
    if (entry.path && !existsSync(join(PROJECT_ROOT, entry.path))) {
      issues.push(`registry '${name}': missing path ${entry.path}`);
    }
    for (const p of entry.related || []) {
      if (RELATED_PREFIX.test(p) && !existsSync(join(PROJECT_ROOT, p))) {
        issues.push(`registry '${name}': related path missing ${p}`);
      }
    }
  }
  return issues;
}

function main() {
  const issues = [];

  issues.push(...checkMarkdownFile(INDEX));

  if (existsSync(RUNBOOKS_DIR)) {
    for (const f of readdirSync(RUNBOOKS_DIR).sort()) {
      if (f.endsWith(".md")) {
        issues.push(...checkMarkdownFile(join(RUNBOOKS_DIR, f)));
      }
    }
  }

  issues.push(...checkRegistry(REGISTRY));

  const result = {
    ok: issues.length === 0,
    generated: new Date().toISOString(),
    issues,
    total_issues: issues.length,
  };

  console.log(JSON.stringify(result, null, 2));
  process.exit(result.ok ? 0 : 1);
}

main();
