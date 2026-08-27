import fs from 'fs';
import path from 'path';
import crypto from 'crypto';
import { fileURLToPath } from 'url';

const __dirname = path.dirname(fileURLToPath(import.meta.url));
const CACHE_BASE = path.join(__dirname, 'cache');

function ensureDir(p) {
  if (!fs.existsSync(p)) fs.mkdirSync(p, { recursive: true });
}

function sha(s) {
  return crypto.createHash('sha256').update(s).digest('hex').slice(0, 16);
}

function parseArgs() {
  const args = process.argv.slice(2);
  const qIdx = args.indexOf('--query');
  const sIdx = args.indexOf('--session');
  const mIdx = args.indexOf('--max-results');
  const rIdx = args.indexOf('--record-result');
  const quick = args.includes('--quick');
  const query = qIdx >= 0 ? args[qIdx + 1] : undefined;
  const session = sIdx >= 0 ? args[sIdx + 1] : (process.env.DEVIN_SESSION_ID || process.pid.toString());
  const max = mIdx >= 0 ? (parseInt(args[mIdx + 1], 10) || 5) : 5;
  const result = rIdx >= 0 ? args[rIdx + 1] : undefined;
  return { query, session, quick, max, result };
}

function classify(query) {
  const q = query.toLowerCase();
  if (/(\b|^)(mcp|mcp-call|mcp-tool|mcp server)(\b|$)/.test(q)) return 'mcp';
  if (/(\b|^)(service|down|restart|status|health|container|podman|docker|systemctl|logs)(\b|$)/.test(q)) return 'service-health';
  if (/(\b|^)(ssot|focus|jobs|infrastructure|services|terminology|night-jobs|improvements)(\b|$)/.test(q)) return 'ssot';
  if (/(\b|^)(file|function|class|script|code|where|grep|search.*code|implementation|bug)(\b|$)/.test(q)) return 'code';
  return 'general-doc';
}

function buildPlan({ query, session, quick, max }) {
  const intent = classify(query);
  const useMddb = !quick && ['ssot','general-doc','code'].includes(intent);
  const useSsot = ['ssot','general-doc','service-health','code'].includes(intent);
  const useGrep = ['code','general-doc','service-health'].includes(intent);
  const useHealth = ['service-health'].includes(intent);
  const useMcp = ['mcp'].includes(intent);
  return {
    query,
    session,
    intent,
    use_mddb: useMddb,
    use_ssot: useSsot,
    use_grep: useGrep,
    use_health: useHealth,
    use_mcp: useMcp,
    quick,
    max_results: max,
    cache_dir: path.join(CACHE_BASE, 'sessions', session),
    audit_path: path.join(CACHE_BASE, 'sessions', session, 'audit.ndjson'),
    ssot_glob: 'docs/ssot/**/*.yml',
    code_glob: '**/*.{mjs,js,ts,py,sh,yml}',
    health_glob: 'docs/ssot/infrastructure/ssot.health*.yml',
    mddb_health_url: 'http://127.0.0.1:11023/health'
  };
}

function writeCacheAndAudit(plan) {
  ensureDir(plan.cache_dir);
  const key = sha(plan.query);
  fs.writeFileSync(path.join(plan.cache_dir, `${key}.json`), JSON.stringify(plan, null, 2));
  const audit = { t: new Date().toISOString(), query: plan.query, intent: plan.intent, plan };
  fs.appendFileSync(plan.audit_path, JSON.stringify(audit) + '\n');
}

function recordResult({ session, result }) {
  const dir = path.join(CACHE_BASE, 'sessions', session);
  ensureDir(dir);
  fs.appendFileSync(path.join(dir, 'audit.ndjson'), JSON.stringify({ t: new Date().toISOString(), result }) + '\n');
}

function main() {
  const { query, session, quick, max, result } = parseArgs();
  if (result) {
    recordResult({ session, result });
    return;
  }
  if (!query) {
    console.error('Usage: info-find.mjs --query "<query>" [--session <id>] [--quick] [--max-results N] [--record-result <json>]');
    process.exit(1);
  }
  const plan = buildPlan({ query, session, quick, max });
  writeCacheAndAudit(plan);
  console.log(JSON.stringify(plan, null, 2));
}

main();
