#!/usr/bin/env node
/*
 * Ada memory-banks audit: registry <-> MDDB drift, schema hygiene,
 * NotebookLM routing coverage, sync freshness, and devin-bank
 * distillation backlog.
 *
 * Expected state is derived from docs/ssot/apps/ssot.apps.ada-memory-banks.yml
 * (the banks: block is machine-readable); thresholds come from this audit's
 * entry in docs/ssot/infrastructure/ssot.audit.yml.
 *
 * Verdicts: registry/MDDB unreachable = FAIL (issue); live-state mismatches
 * = warn (DRIFT-style — usually means update the registry, not the system).
 */
import http from "http";
import { URL } from "url";
import { readFileSync, readdirSync, statSync, existsSync } from "fs";
import { join, dirname } from "path";
import yaml from "js-yaml";

const PROJECT_ROOT = new URL("../../", import.meta.url).pathname.replace(/\/$/, "");
const BANKS_SSOT = join(PROJECT_ROOT, "docs/ssot/apps/ssot.apps.ada-memory-banks.yml");
const AUDIT_SSOT = join(PROJECT_ROOT, "docs/ssot/infrastructure/ssot.audit.yml");
const MDDB_BASE = (process.env.MDDB_BASE || "http://127.0.0.1:11023/v1").replace(/\/$/, "");
const SUMMARIES_DIR = process.env.DEVIN_SUMMARIES_DIR || `${process.env.HOME}/.local/share/devin/cli/summaries`;
const ADA_ENV_FILES = (process.env.ADA_ENV_FILES ||
  `${process.env.HOME}/.config/secrets/ada-pi-pwa.env`).split(":");

const VALID_STATUS = new Set(["active", "draft", "superseded", "retracted", "expired"]);
const CORE_FIELDS = ["kind", "status", "scope", "source", "written_by"];

const issues = [];
const warns = [];
const notes = [];
const issue = (m) => issues.push(m);
const warn = (m) => warns.push(m);
const note = (m) => notes.push(m);

function thresholds() {
  const def = {
    max_undistilled_devin: 200,
    max_doc_bytes: 51200,
    max_missing_core_docs: 0,
    devin_sync_stale_days: 2,
    revision_bloat_ratio: 20,
  };
  try {
    const doc = yaml.load(readFileSync(AUDIT_SSOT, "utf8"));
    const entry = (doc.audits || []).find((a) => a.name === "memory-banks");
    return { ...def, ...(entry?.thresholds || {}) };
  } catch {
    return def;
  }
}

function getJson(path, timeoutMs = 15000) {
  return new Promise((resolve, reject) => {
    const u = new URL(MDDB_BASE + path);
    const req = http.get(
      { hostname: u.hostname, port: u.port, path: u.pathname + u.search, timeout: timeoutMs },
      (res) => {
        let data = "";
        res.on("data", (c) => (data += c));
        res.on("end", () => {
          if (res.statusCode !== 200) return reject(new Error(`HTTP ${res.statusCode}`));
          try {
            resolve(data ? JSON.parse(data) : null);
          } catch (e) {
            reject(new Error(`bad JSON: ${e.message}`));
          }
        });
      }
    );
    req.on("error", reject);
    req.on("timeout", () => req.destroy(new Error("timeout")));
  });
}

function postJson(path, payload, timeoutMs = 30000) {
  return new Promise((resolve, reject) => {
    const u = new URL(MDDB_BASE + path);
    const body = JSON.stringify(payload);
    const req = http.request(
      {
        hostname: u.hostname,
        port: u.port,
        path: u.pathname,
        method: "POST",
        headers: { "Content-Type": "application/json", "Content-Length": Buffer.byteLength(body) },
        timeout: timeoutMs,
      },
      (res) => {
        let out = "";
        res.on("data", (c) => (out += c));
        res.on("end", () => {
          if (res.statusCode !== 200) return reject(new Error(`HTTP ${res.statusCode}`));
          try {
            resolve(out ? JSON.parse(out) : null);
          } catch (e) {
            reject(new Error(`bad JSON: ${e.message}`));
          }
        });
      }
    );
    req.on("error", reject);
    req.on("timeout", () => req.destroy(new Error("timeout")));
    req.write(body);
    req.end();
  });
}

function expandCollections(banks) {
  // bank -> [{collection, scope, writable, instances, kinds, notebooklm_group}]
  const out = [];
  for (const [name, spec] of Object.entries(banks)) {
    const coll = spec.mddb_collection || "";
    const instances = spec.instances || [];
    const base = {
      bank: name,
      writable: !!spec.writable,
      kinds: spec.kinds || [],
      notebooklm_group: spec.notebooklm_group || null,
      status: spec.status || "active",
    };
    if (coll.includes("{instance}")) {
      for (const inst of instances) {
        out.push({ ...base, collection: coll.replace("{instance}", inst) });
      }
    } else {
      out.push({ ...base, collection: coll });
    }
  }
  return out;
}

function metaVal(doc, field) {
  const v = (doc.meta || {})[field];
  return Array.isArray(v) ? v[0] : v;
}

function patchJson(path, payload, timeoutMs = 15000) {
  return new Promise((resolve, reject) => {
    const u = new URL(MDDB_BASE + path);
    const body = JSON.stringify(payload);
    const req = http.request(
      {
        hostname: u.hostname,
        port: u.port,
        path: u.pathname,
        method: "PATCH",
        headers: { "Content-Type": "application/json", "Content-Length": Buffer.byteLength(body) },
        timeout: timeoutMs,
      },
      (res) => {
        let out = "";
        res.on("data", (c) => (out += c));
        res.on("end", () => resolve({ status: res.statusCode, body: out }));
      }
    );
    req.on("error", reject);
    req.on("timeout", () => req.destroy(new Error("timeout")));
    req.write(body);
    req.end();
  });
}

async function probeMetaUpdate() {
  const probe = { collection: "test", key: "audit/meta-update-probe", lang: "en" };
  try {
    await postJson("/add", { ...probe, contentMd: "audit probe", meta: { probe: ["0"] } });
    const r = await patchJson("/update", { ...probe, meta: { probe: ["1"] } });
    if (r.status !== 200 || /error|not found/i.test(r.body)) {
      warn(
        `PATCH /v1/update broken (status ${r.status}: ${r.body.slice(0, 120)}) — ` +
          "ada-pi correct-in-place writes silently fail; supersede must re-add"
      );
    } else {
      note("PATCH /v1/update works");
    }
  } catch (e) {
    warn(`meta-update probe failed: ${e.message}`);
  } finally {
    await postJson("/delete", probe).catch(() => {});
  }
}

async function main() {
  const th = thresholds();

  // --- registry ---
  let banks;
  try {
    banks = yaml.load(readFileSync(BANKS_SSOT, "utf8")).banks || {};
  } catch (e) {
    issue(`Cannot read banks registry ${BANKS_SSOT}: ${e.message}`);
    return done(null);
  }
  const expected = expandCollections(banks);
  note(`registry: ${Object.keys(banks).length} banks -> ${expected.length} collections`);

  // --- MDDB stats --- (cold-cache slow after restarts; retry once)
  let stats = await getJson("/stats", 60000).catch(() => null);
  if (!stats) {
    await new Promise((r) => setTimeout(r, 2000));
    stats = await getJson("/stats", 60000).catch((e) => {
      issue(`MDDB /v1/stats unreachable at ${MDDB_BASE}: ${e.message}`);
      return null;
    });
  }
  if (!stats) return done(null);
  const live = new Map((stats.collections || []).map((c) => [c.name, c]));

  // --- drift: missing / orphan collections ---
  const expectedNames = new Set(expected.map((e) => e.collection));
  for (const e of expected) {
    if (!live.has(e.collection)) {
      warn(`DRIFT collection ${e.collection} (bank ${e.bank}) declared but missing in MDDB`);
    }
  }
  for (const name of live.keys()) {
    if (name.startsWith("ada-ha-bank-") && !expectedNames.has(name)) {
      warn(`DRIFT orphan collection ${name} exists in MDDB but no bank declares it`);
    }
  }

  // --- per-collection checks ---
  for (const e of expected) {
    const c = live.get(e.collection);
    if (!c) continue;
    if (c.documentCount === 0) {
      (e.writable ? warn : note)(
        `collection ${e.collection} is empty (bank ${e.bank}, writable=${e.writable})`
      );
      continue;
    }
    if (c.documentCount > 0 && c.revisionCount > c.documentCount * th.revision_bloat_ratio) {
      note(
        `${e.collection}: revisionCount ${c.revisionCount} is >${th.revision_bloat_ratio}x docs ${c.documentCount}`
      );
    }

    const docs = await postJson("/search", { collection: e.collection, limit: 5000 }).catch(
      (err) => {
        warn(`cannot list ${e.collection}: ${err.message}`);
        return null;
      }
    );
    if (!docs) continue;

    // The ada memory schema (kind/status/scope/source/written_by) governs
    // curated bank docs only — synced knowledge collections (kb-*,
    // infrastructure-ssot) carry their own upstream meta.
    if (e.collection.startsWith("ada-ha-bank-")) {
      let missingCore = 0;
      let badStatus = 0;
      let badKind = 0;
      for (const d of docs) {
        const meta = d.meta || {};
        if (CORE_FIELDS.some((f) => !meta[f] || !meta[f][0])) missingCore++;
        if (meta.status && meta.status[0] && !VALID_STATUS.has(meta.status[0])) badStatus++;
        if (e.kinds.length && meta.kind && meta.kind[0] && !e.kinds.includes(meta.kind[0]))
          badKind++;
      }
      if (missingCore > th.max_missing_core_docs) {
        warn(`${e.collection}: ${missingCore} doc(s) missing core meta (${CORE_FIELDS.join("/")})`);
      }
      if (badStatus) warn(`${e.collection}: ${badStatus} doc(s) with invalid status value`);
      if (badKind)
        warn(`${e.collection}: ${badKind} doc(s) with kind outside bank kinds [${e.kinds}]`);
    }
    const oversized = docs.filter((d) => (d.contentMd || "").length > th.max_doc_bytes).length;
    if (oversized) note(`${e.collection}: ${oversized} doc(s) >${th.max_doc_bytes} bytes`);

    // --- devin distillation backlog ---
    if (e.bank === "devin") {
      const raw = docs.filter(
        (d) => metaVal(d, "subject") === "devin-session" && metaVal(d, "status") === "active"
      );
      const superseded = docs.filter((d) => metaVal(d, "status") === "superseded").length;
      const rollups = docs.filter((d) => metaVal(d, "subject") === "devin-weekly-rollup").length;
      note(
        `${e.collection}: ${raw.length} raw session docs active, ${superseded} superseded, ${rollups} weekly rollups`
      );
      if (raw.length > th.max_undistilled_devin) {
        warn(
          `${e.collection}: ${raw.length} undistilled session docs (>${th.max_undistilled_devin}) — run scripts/ada/distill-devin-bank.py`
        );
      }
    }
  }

  // --- devin sync freshness (host-local: summaries dir may not exist here) ---
  if (existsSync(SUMMARIES_DIR)) {
    const files = readdirSync(SUMMARIES_DIR)
      .filter((f) => f.startsWith("history_") && f.endsWith(".md"))
      .map((f) => statSync(join(SUMMARIES_DIR, f)).mtimeMs);
    if (files.length) {
      const newestFile = Math.max(...files);
      const devColl = expected.find((e) => e.bank === "devin" && live.has(e.collection));
      if (devColl) {
        const docs = await postJson("/search", {
          collection: devColl.collection,
          limit: 5000,
        }).catch(() => []);
        const newestDoc = Math.max(
          0,
          ...docs.map((d) => (d.addedAt || d.updatedAt || 0) * 1000)
        );
        const lagDays = (newestFile - newestDoc) / 86400000;
        if (lagDays > th.devin_sync_stale_days) {
          warn(
            `devin bank stale: newest summary file is ${lagDays.toFixed(1)}d newer than newest doc — sync-devin-summaries.py not running?`
          );
        } else {
          note(`devin sync freshness ok (lag ${lagDays.toFixed(1)}d)`);
        }

        // --- devin coverage: every non-empty local summary should have a
        // bank doc (devin/<hex> for CLI threads, devin-session/<name> for
        // desktop session summaries). Fresh files get a grace window
        // because the importer only runs hourly.
        const remoteKeys = new Set(docs.map((d) => d.key).filter(Boolean));
        const graceMs = 3 * 3600 * 1000;
        const nowMs = Date.now();
        let missing = 0, missingFresh = 0, emptyStubs = 0, missingNamed = 0;
        for (const f of readdirSync(SUMMARIES_DIR)) {
          if (!f.startsWith("history_") || !f.endsWith(".md")) continue;
          const st = statSync(join(SUMMARIES_DIR, f));
          if (st.size === 0) { emptyStubs++; continue; }
          if (remoteKeys.has(`devin/${f.slice(8, -3)}`)) continue;
          if (nowMs - st.mtimeMs > graceMs) missing++; else missingFresh++;
        }
        const namedDir = `${process.env.HOME}/.local/share/devin/summaries`;
        if (existsSync(namedDir)) {
          for (const f of readdirSync(namedDir)) {
            if (!f.endsWith(".md")) continue;
            const st = statSync(join(namedDir, f));
            if (st.size === 0) { emptyStubs++; continue; }
            if (remoteKeys.has(`devin-session/${f.slice(0, -3)}`)) continue;
            if (nowMs - st.mtimeMs > graceMs) missingNamed++; else missingFresh++;
          }
        }
        if (missing || missingNamed) {
          warn(
            `devin coverage: ${missing + missingNamed} non-empty summaries older than 3h missing from bank — sync-devin-summaries.py failing or keys drifting`
          );
        } else {
          note(
            `devin coverage ok (all non-empty summaries in bank; ${missingFresh} inside lag window, ${emptyStubs} empty stubs)`
          );
        }
      }
    }
  } else {
    note(`${SUMMARIES_DIR} not present on this host; skipping devin sync freshness`);
  }

  // --- PATCH /v1/update probe: ada-pi's correct-in-place writes depend on
  // it. Self-cleaning probe doc in the scratch `test` collection. ---
  await probeMetaUpdate();

  // --- NotebookLM group routing coverage (env var name only, never values) ---
  const grouped = expected.filter((e) => e.notebooklm_group);
  if (grouped.length) {
    let anyConfigured = false;
    for (const envFile of ADA_ENV_FILES) {
      if (!existsSync(envFile)) {
        note(`env file ${envFile} absent — skipped NLM routing check for it`);
        continue;
      }
      const text = readFileSync(envFile, "utf8");
      if (/^(export )?NOTEBOOKLM_NOTEBOOK_IDS_JSON=/m.test(text)) {
        anyConfigured = true;
        note(`NOTEBOOKLM_NOTEBOOK_IDS_JSON present in ${envFile}`);
      } else {
        warn(
          `${envFile} lacks NOTEBOOKLM_NOTEBOOK_IDS_JSON — banks with notebooklm_group (${[
            ...new Set(grouped.map((g) => g.notebooklm_group)),
          ].join(", ")}) will fall back to the default notebook for this backend`
        );
      }
    }
    if (!anyConfigured && ADA_ENV_FILES.every((f) => !existsSync(f))) {
      note("no ada env files found on this host; NLM routing check skipped");
    }
  }

  done(stats);
}

function done(stats) {
  const result = {
    ok: issues.length === 0,
    generated: new Date().toISOString(),
    mddb: MDDB_BASE,
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
