#!/usr/bin/env node
/*
 * MDDB health and consistency audit.
 * Runs live checks against the tony-dell MDDB HTTP API and the
 * tony-omen Gemini-Ollama embedding proxy, plus local DB file metrics.
 */
import http from 'http';
import { URL } from 'url';
import { statSync } from 'fs';

const MDDB_BASE = 'http://localhost:11023';
const PROXY_URLS = [
  'http://tony-omen:11435',
  'http://100.75.102.88:11435',
];
const DB_PATH = '/home/tony/.config/containers/mddb/data/mddb.db';
const MIN_DOCUMENTS = 50;
const MAX_DB_SIZE_BYTES = 1024 * 1024 * 1024; // 1 GB

const issues = [];
const notes = [];

function issue(msg) {
  issues.push(msg);
}

function note(msg) {
  notes.push(msg);
}

function getJson(url, timeoutMs = 10000) {
  return new Promise((resolve, reject) => {
    const u = new URL(url);
    const req = http.get(
      {
        hostname: u.hostname,
        port: u.port || 80,
        path: u.pathname + u.search,
        timeout: timeoutMs,
      },
      (res) => {
        let data = '';
        res.setEncoding('utf8');
        res.on('data', (chunk) => { data += chunk; });
        res.on('end', () => {
          if (res.statusCode !== 200) {
            reject(new Error(`HTTP ${res.statusCode}: ${data.slice(0, 200)}`));
            return;
          }
          try {
            resolve(data ? JSON.parse(data) : null);
          } catch (e) {
            reject(new Error(`Invalid JSON from ${url}: ${e.message}`));
          }
        });
      }
    );
    req.on('error', reject);
    req.on('timeout', () => {
      req.destroy();
      reject(new Error('timeout'));
    });
  });
}

async function checkMddbHealth() {
  const health = await getJson(`${MDDB_BASE}/health`).catch((e) => {
    issue(`MDDB /health unreachable: ${e.message}`);
    return null;
  });
  if (!health) return;

  if (health.status !== 'healthy' && health.status !== 'ok') {
    issue(`MDDB /health status=${health.status}`);
  } else {
    note('MDDB /health OK');
  }
  if (health.mode && health.mode !== 'wr') {
    issue(`MDDB mode is ${health.mode}, expected wr`);
  }
}

async function checkMddbStats() {
  const stats = await getJson(`${MDDB_BASE}/v1/stats`).catch((e) => {
    issue(`MDDB /v1/stats unreachable: ${e.message}`);
    return null;
  });
  if (!stats) return;

  if (stats.mode && stats.mode !== 'wr') {
    issue(`MDDB /v1/stats mode=${stats.mode}, expected wr`);
  }
  if (typeof stats.totalDocuments !== 'number' || stats.totalDocuments < MIN_DOCUMENTS) {
    issue(`MDDB totalDocuments=${stats.totalDocuments} (expected >= ${MIN_DOCUMENTS})`);
  }
  if (!stats.databaseSize) {
    issue('MDDB databaseSize missing');
  }
  if (stats.indexQueue) {
    if ((stats.indexQueue.failed || 0) > 0) {
      issue(`MDDB indexQueue.failed=${stats.indexQueue.failed}`);
    }
  }
  note(`MDDB collections=${(stats.collections || []).length} totalDocuments=${stats.totalDocuments}`);
}

async function checkProxyHealth() {
  let reachable = false;
  for (const proxyUrl of PROXY_URLS) {
    const health = await getJson(`${proxyUrl}/health`).catch(() => null);
    if (health && (health.status === 'ok' || health.status === 'healthy')) {
      reachable = true;
      if (health.gemini_model !== 'gemini-embedding-2') {
        issue(`Gemini proxy primary model is ${health.gemini_model}, expected gemini-embedding-2`);
      }
      if (health.dimensions !== 768) {
        issue(`Gemini proxy dimensions=${health.dimensions}, expected 768`);
      }
      note(`Gemini proxy OK at ${proxyUrl} (${health.gemini_model})`);
      break;
    }
  }
  if (!reachable) {
    issue(`Gemini-Ollama proxy unreachable on ${PROXY_URLS.join(' or ')}`);
  }
}

function checkDbFile() {
  try {
    const st = statSync(DB_PATH);
    const sizeMB = (st.size / 1024 / 1024).toFixed(1);
    note(`mddb.db size=${sizeMB} MB`);
    if (st.size > MAX_DB_SIZE_BYTES) {
      issue(`mddb.db size ${sizeMB} MB exceeds 1 GB`);
    }
  } catch (e) {
    issue(`Cannot stat ${DB_PATH}: ${e.message}`);
  }
}

async function main() {
  await checkMddbHealth();
  await checkMddbStats();
  await checkProxyHealth();
  checkDbFile();

  const result = {
    ok: issues.length === 0,
    generated: new Date().toISOString(),
    mddb: MDDB_BASE,
    db_path: DB_PATH,
    issues,
    notes,
    total_issues: issues.length,
    total_notes: notes.length,
  };
  console.log(JSON.stringify(result, null, 2));
  process.exit(result.ok ? 0 : 1);
}

main().catch((e) => {
  console.error(JSON.stringify({ ok: false, error: e.message }));
  process.exit(1);
});
