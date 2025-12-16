const express = require('express');
const fs = require('fs-extra');
const path = require('path');
const { execFile } = require('child_process');

const PORT = parseInt(process.env.PORT || '8080', 10);
const APPHOST_TOKEN = process.env.APPHOST_TOKEN || '';

const ARTIFACTS_DIR = process.env.APPHOST_ARTIFACTS_DIR || '/srv/app';
const REPO_DIR = process.env.APPHOST_REPO_DIR || '/repo';
const CACHE_DIR = process.env.APPHOST_CACHE_DIR || '/cache';

const REPO_URL = process.env.APPHOST_REPO_URL || '';
const DEFAULT_REF = process.env.APPHOST_REF || 'main';

const INSTALL_COMMAND = process.env.APPHOST_INSTALL_COMMAND || 'npm ci';
const BUILD_COMMAND = process.env.APPHOST_BUILD_COMMAND || 'npm run build';
const OUTPUT_DIR = process.env.APPHOST_OUTPUT_DIR || 'dist';

const RELEASES_TO_KEEP = parseInt(process.env.APPHOST_RELEASES_TO_KEEP || '5', 10);

const RELEASES_DIR = path.join(ARTIFACTS_DIR, 'releases');
const CURRENT_LINK = path.join(ARTIFACTS_DIR, 'current');
const STATE_DIR = path.join(ARTIFACTS_DIR, '.state');
const STATUS_FILE = path.join(STATE_DIR, 'status.json');

function nowIso() {
  return new Date().toISOString();
}

function runCmd(command, options = {}) {
  return new Promise((resolve, reject) => {
    execFile('bash', ['-lc', command], { ...options }, (err, stdout, stderr) => {
      if (err) {
        const e = new Error(`Command failed: ${command}\n${stderr || stdout || err.message}`);
        e.code = err.code;
        e.stdout = stdout;
        e.stderr = stderr;
        return reject(e);
      }
      return resolve({ stdout, stderr });
    });
  });
}

async function writeStatus(update) {
  await fs.ensureDir(STATE_DIR);
  const current = (await fs.pathExists(STATUS_FILE)) ? await fs.readJson(STATUS_FILE) : {};
  const merged = { ...current, ...update, updated_at: nowIso() };
  await fs.writeJson(STATUS_FILE, merged, { spaces: 2 });
  return merged;
}

async function readStatus() {
  if (!(await fs.pathExists(STATUS_FILE))) {
    return { status: 'empty', updated_at: null };
  }
  return fs.readJson(STATUS_FILE);
}

function requireToken(req, res, next) {
  if (!APPHOST_TOKEN) return next();
  const got = req.header('x-apphost-token') || '';
  if (!got || got !== APPHOST_TOKEN) {
    return res.status(401).json({ error: 'unauthorized' });
  }
  return next();
}

async function ensureRepo() {
  if (!REPO_URL) {
    throw new Error('APPHOST_REPO_URL is required');
  }
  await fs.ensureDir(REPO_DIR);
  const gitDir = path.join(REPO_DIR, '.git');
  if (!(await fs.pathExists(gitDir))) {
    await runCmd(`git init`, { cwd: REPO_DIR });
    await runCmd(`git remote add origin "${REPO_URL}"`, { cwd: REPO_DIR });
  }
  await runCmd(`git remote set-url origin "${REPO_URL}"`, { cwd: REPO_DIR });
}

async function checkoutRef(ref) {
  const safeRef = ref || DEFAULT_REF;
  await runCmd(`git fetch origin --prune`, { cwd: REPO_DIR });
  await runCmd(`git checkout -B apphost "origin/${safeRef}" || git checkout -B apphost "${safeRef}"`, { cwd: REPO_DIR });
  await runCmd(`git reset --hard`, { cwd: REPO_DIR });
  const { stdout } = await runCmd(`git rev-parse HEAD`, { cwd: REPO_DIR });
  return stdout.trim();
}

function makeReleaseId(gitSha) {
  const short = (gitSha || 'unknown').slice(0, 12);
  const ts = new Date().toISOString().replace(/[-:]/g, '').replace(/\..+/, '');
  return `${ts}-${short}`;
}

async function buildToRelease(releaseId) {
  const env = {
    ...process.env,
    npm_config_cache: path.join(CACHE_DIR, 'npm'),
  };

  await fs.ensureDir(CACHE_DIR);

  await runCmd(`set -euo pipefail; ${INSTALL_COMMAND}`, { cwd: REPO_DIR, env });
  await runCmd(`set -euo pipefail; ${BUILD_COMMAND}`, { cwd: REPO_DIR, env });

  const srcOut = path.join(REPO_DIR, OUTPUT_DIR);
  if (!(await fs.pathExists(srcOut))) {
    throw new Error(`Build output directory not found: ${srcOut}`);
  }

  const releaseDir = path.join(RELEASES_DIR, releaseId);
  await fs.ensureDir(RELEASES_DIR);
  await fs.remove(releaseDir);
  await fs.copy(srcOut, releaseDir);
  return releaseDir;
}

async function switchCurrentTo(releaseId) {
  await fs.ensureDir(ARTIFACTS_DIR);
  const target = path.join(RELEASES_DIR, releaseId);
  if (!(await fs.pathExists(target))) {
    throw new Error(`Release not found: ${releaseId}`);
  }
  await runCmd(`ln -sfn "${target}" "${CURRENT_LINK}"`);
}

async function listReleases() {
  if (!(await fs.pathExists(RELEASES_DIR))) return [];
  const entries = await fs.readdir(RELEASES_DIR);
  const dirs = [];
  for (const e of entries) {
    const p = path.join(RELEASES_DIR, e);
    try {
      const st = await fs.stat(p);
      if (st.isDirectory()) dirs.push({ id: e, mtimeMs: st.mtimeMs });
    } catch {
      // ignore
    }
  }
  dirs.sort((a, b) => b.mtimeMs - a.mtimeMs);
  return dirs.map(d => d.id);
}

async function garbageCollectReleases() {
  const keep = Number.isFinite(RELEASES_TO_KEEP) ? Math.max(1, RELEASES_TO_KEEP) : 5;
  const releases = await listReleases();
  const toDelete = releases.slice(keep);
  for (const id of toDelete) {
    await fs.remove(path.join(RELEASES_DIR, id));
  }
  return { kept: releases.slice(0, keep), deleted: toDelete };
}

const app = express();
app.use(express.json({ limit: '1mb' }));

app.get('/health', (_req, res) => {
  res.status(200).send('ok');
});

app.get('/status', async (_req, res) => {
  try {
    const status = await readStatus();
    res.json(status);
  } catch (e) {
    res.status(500).json({ error: String(e.message || e) });
  }
});

app.post('/publish', requireToken, async (req, res) => {
  const ref = (req.body && req.body.ref) ? String(req.body.ref) : DEFAULT_REF;
  const startedAt = nowIso();
  try {
    await writeStatus({ status: 'publishing', started_at: startedAt, ref });
    await ensureRepo();
    const gitSha = await checkoutRef(ref);
    const releaseId = makeReleaseId(gitSha);

    await writeStatus({ status: 'building', git_sha: gitSha, release_id: releaseId });
    await buildToRelease(releaseId);

    await writeStatus({ status: 'switching', git_sha: gitSha, release_id: releaseId });
    await switchCurrentTo(releaseId);

    const gc = await garbageCollectReleases();
    const final = await writeStatus({
      status: 'ready',
      git_sha: gitSha,
      release_id: releaseId,
      finished_at: nowIso(),
      gc,
    });

    res.json({ ok: true, ...final });
  } catch (e) {
    const errStatus = await writeStatus({ status: 'error', error: String(e.message || e), finished_at: nowIso() });
    res.status(500).json({ ok: false, ...errStatus });
  }
});

app.post('/rollback', requireToken, async (req, res) => {
  const releaseId = req.body && req.body.release_id ? String(req.body.release_id) : '';
  if (!releaseId) {
    return res.status(400).json({ error: 'release_id is required' });
  }
  try {
    await writeStatus({ status: 'rolling_back', target_release_id: releaseId });
    await switchCurrentTo(releaseId);
    const final = await writeStatus({ status: 'ready', release_id: releaseId, finished_at: nowIso() });
    return res.json({ ok: true, ...final });
  } catch (e) {
    const errStatus = await writeStatus({ status: 'error', error: String(e.message || e), finished_at: nowIso() });
    return res.status(500).json({ ok: false, ...errStatus });
  }
});

app.listen(PORT, async () => {
  await fs.ensureDir(ARTIFACTS_DIR);
  await fs.ensureDir(STATE_DIR);
  // Do not auto-publish on boot; publish is trigger-driven.
  console.log(`[mcp-apphost] listening on :${PORT}`);
});
