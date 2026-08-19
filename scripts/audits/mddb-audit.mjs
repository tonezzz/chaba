#!/usr/bin/env node
/*
 * MDDB health, embedding pipeline, and data integrity audit.
 * Runs live checks against the MDDB HTTP API and the Gemini-Ollama proxy.
 */
import http from 'http';
import { URL } from 'url';
import { statSync, readdirSync } from 'fs';
import { dirname, join, basename } from 'path';
import { spawnSync } from 'child_process';

const MDDB_BASE = process.env.MDDB_BASE || 'http://tony-dell:11023';
const DB_PATH = process.env.MDDB_DB_PATH || '';
const PROXY_URLS = [
  'http://tony-omen:11435',
  'http://100.75.102.88:11435',
];
const MIN_DOCUMENTS = 50;
const MAX_DB_SIZE_BYTES = 1024 * 1024 * 1024; // 1 GB
const MAX_RESPONSE_MS = 2000;
const MAX_BACKUP_AGE_HOURS = 24;

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
    const start = Date.now();
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
            const parsed = data ? JSON.parse(data) : null;
            resolve({ body: parsed, durationMs: Date.now() - start });
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

function postJson(url, payload, timeoutMs = 10000) {
  return new Promise((resolve, reject) => {
    const u = new URL(url);
    const data = JSON.stringify(payload);
    const start = Date.now();
    const req = http.request(
      {
        hostname: u.hostname,
        port: u.port || 80,
        path: u.pathname + u.search,
        method: 'POST',
        headers: {
          'Content-Type': 'application/json',
          'Content-Length': Buffer.byteLength(data),
        },
        timeout: timeoutMs,
      },
      (res) => {
        let out = '';
        res.setEncoding('utf8');
        res.on('data', (chunk) => { out += chunk; });
        res.on('end', () => {
          if (res.statusCode !== 200) {
            reject(new Error(`HTTP ${res.statusCode}: ${out.slice(0, 200)}`));
            return;
          }
          try {
            const parsed = out ? JSON.parse(out) : null;
            resolve({ body: parsed, durationMs: Date.now() - start });
          } catch (e) {
            reject(new Error(`Invalid JSON from ${url}: ${e.message}`));
          }
        });
      }
    );
    req.on('error', reject);
    req.on('timeout', () => { req.destroy(); reject(new Error('timeout')); });
    req.write(data);
    req.end();
  });
}

async function checkMddbHealth() {
  const { body, durationMs } = await getJson(`${MDDB_BASE}/health`).catch((e) => {
    issue(`MDDB /health unreachable: ${e.message}`);
    return { body: null, durationMs: 0 };
  });
  if (!body) return;

  if (durationMs > MAX_RESPONSE_MS) {
    issue(`MDDB /health slow: ${durationMs}ms`);
  }
  if (body.status !== 'healthy' && body.status !== 'ok') {
    issue(`MDDB /health status=${body.status}`);
  } else {
    note(`MDDB /health OK (${durationMs}ms)`);
  }
  if (body.mode && body.mode !== 'wr') {
    issue(`MDDB mode is ${body.mode}, expected wr`);
  }
}

async function checkMddbStats() {
  const { body, durationMs } = await getJson(`${MDDB_BASE}/v1/stats`).catch((e) => {
    issue(`MDDB /v1/stats unreachable: ${e.message}`);
    return { body: null, durationMs: 0 };
  });
  if (!body) return;

  if (durationMs > MAX_RESPONSE_MS) {
    issue(`MDDB /v1/stats slow: ${durationMs}ms`);
  }
  if (body.mode && body.mode !== 'wr') {
    issue(`MDDB /v1/stats mode=${body.mode}, expected wr`);
  }
  if (typeof body.totalDocuments !== 'number' || body.totalDocuments < MIN_DOCUMENTS) {
    issue(`MDDB totalDocuments=${body.totalDocuments} (expected >= ${MIN_DOCUMENTS})`);
  }
  if (!body.databaseSize) {
    issue('MDDB databaseSize missing');
  }
  if (body.indexQueue) {
    if ((body.indexQueue.failed || 0) > 0) {
      issue(`MDDB indexQueue.failed=${body.indexQueue.failed}`);
    }
    if ((body.indexQueue.fallbacks || 0) > 0) {
      issue(`MDDB indexQueue.fallbacks=${body.indexQueue.fallbacks}`);
    }
  }
  note(`MDDB collections=${(body.collections || []).length} totalDocuments=${body.totalDocuments} (${durationMs}ms)`);
}

async function checkMddbSearch() {
  const { body, durationMs } = await postJson(`${MDDB_BASE}/v1/search`, {
    collection: 'kb-system',
    query: 'postgres',
    limit: 3,
  }).catch((e) => {
    issue(`MDDB /v1/search unreachable: ${e.message}`);
    return { body: null, durationMs: 0 };
  });
  if (!body) return;

  if (durationMs > MAX_RESPONSE_MS) {
    issue(`MDDB /v1/search slow: ${durationMs}ms`);
  }
  if (!Array.isArray(body) || body.length === 0) {
    issue('MDDB /v1/search returned no results for "postgres"');
  } else {
    const keys = body.map((d) => d.key).join(', ');
    note(`MDDB /v1/search OK: "postgres" returned ${body.length} result(s) (${durationMs}ms): ${keys.slice(0, 80)}`);
  }
}

async function checkProxyHealth() {
  let reachable = false;
  for (const proxyUrl of PROXY_URLS) {
    const { body, durationMs } = await getJson(`${proxyUrl}/health`).catch(() => ({ body: null, durationMs: 0 }));
    if (body && (body.status === 'ok' || body.status === 'healthy')) {
      reachable = true;
      if (durationMs > MAX_RESPONSE_MS) {
        issue(`Gemini proxy slow at ${proxyUrl}: ${durationMs}ms`);
      }
      if (body.gemini_model !== 'gemini-embedding-2') {
        issue(`Gemini proxy primary model is ${body.gemini_model}, expected gemini-embedding-2`);
      }
      if (body.dimensions !== 768) {
        issue(`Gemini proxy dimensions=${body.dimensions}, expected 768`);
      }
      note(`Gemini proxy OK at ${proxyUrl} (${body.gemini_model}, ${durationMs}ms)`);
      break;
    }
  }
  if (!reachable) {
    issue(`Gemini-Ollama proxy unreachable on ${PROXY_URLS.join(' or ')}`);
  }
}

function checkDbFile() {
  if (!DB_PATH) {
    note('DB_PATH not set; skipping local DB size and backup checks');
    return;
  }

  let st;
  try {
    st = statSync(DB_PATH);
  } catch (e) {
    issue(`Cannot stat ${DB_PATH}: ${e.message}`);
    return;
  }

  const sizeMB = (st.size / 1024 / 1024).toFixed(1);
  note(`mddb.db size=${sizeMB} MB`);
  if (st.size > MAX_DB_SIZE_BYTES) {
    issue(`mddb.db size ${sizeMB} MB exceeds 1 GB`);
  }

  const dbDir = dirname(DB_PATH);
  let backups = [];
  try {
    backups = readdirSync(dbDir)
      .map((f) => ({ name: f, path: join(dbDir, f), stat: statSync(join(dbDir, f)) }))
      .filter((f) => f.name.startsWith('mddb.db.bak') || f.name.endsWith('.bak'))
      .sort((a, b) => b.stat.mtimeMs - a.stat.mtimeMs);
  } catch (e) {
    issue(`Cannot list backups in ${dbDir}: ${e.message}`);
    return;
  }

  if (backups.length === 0) {
    issue('No mddb.db backup files found');
    return;
  }

  const newest = backups[0];
  const ageHours = (Date.now() - newest.stat.mtimeMs) / (1000 * 60 * 60);
  const ageText = ageHours.toFixed(1);
  note(`newest backup: ${basename(newest.path)} (${(newest.stat.size / 1024 / 1024).toFixed(1)} MB, ${ageText}h old)`);
  if (ageHours > MAX_BACKUP_AGE_HOURS) {
    issue(`Newest backup is ${ageText}h old (expected <= ${MAX_BACKUP_AGE_HOURS}h)`);
  }
  if (newest.stat.size > st.size * 1.5) {
    issue(`Newest backup is much larger than live DB: ${newest.stat.size} vs ${st.size}`);
  }
}

function checkContainerLogs() {
  if (!DB_PATH) {
    note('DB_PATH not set; skipping container log scan');
    return;
  }
  const podman = spawnSync('which', ['podman'], { encoding: 'utf8' });
  if (!podman.stdout || podman.status !== 0) {
    note('podman not in PATH; skipping container log scan');
    return;
  }

  const logs = spawnSync('podman', ['logs', 'mddb', '--since', '24h'], {
    encoding: 'utf8',
    timeout: 15000,
  });
  if (logs.status === null || logs.error) {
    note(`Could not read mddb container logs: ${logs.error?.message || 'unknown'}`);
    return;
  }

  const text = (logs.stdout || '') + '\n' + (logs.stderr || '');
  const errorLines = text.split('\n').filter((line) => /\b(ERROR|FATAL|panic)\b/i.test(line));
  if (errorLines.length > 0) {
    issue(`mddb container log has ${errorLines.length} error line(s) in last 24h`);
    for (const line of errorLines.slice(0, 3)) {
      issue(`  log: ${line.trim().slice(0, 200)}`);
    }
  } else {
    note('mddb container log has no ERROR/FATAL lines in last 24h');
  }
}

async function main() {
  await checkMddbHealth();
  await checkMddbStats();
  await checkMddbSearch();
  await checkProxyHealth();
  checkDbFile();
  checkContainerLogs();

  const result = {
    ok: issues.length === 0,
    generated: new Date().toISOString(),
    mddb: MDDB_BASE,
    db_path: DB_PATH || null,
    issues,
    notes,
    total_issues: issues.length,
    total_notes: notes.length,
  };
  console.log(JSON.stringify(result, null, 2));
  process.exit(result.ok ? 0 : 1);
}

main().catch((e) => {
  console.error(JSON.stringify({ ok: false, error: e.message, stack: e.stack }));
  process.exit(1);
});
