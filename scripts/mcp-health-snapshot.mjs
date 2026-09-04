#!/usr/bin/env node
// Periodic snapshot of mcp-health status without desktop notifications.
// Spawns mcp-health via the SSH wrapper, calls get_health_status, logs to file,
// and writes to the SSOT focus-inbox only when something is failing.
import { spawn } from 'child_process';
import { mkdirSync, writeFileSync } from 'fs';
import { dirname, join } from 'path';
import { fileURLToPath } from 'url';

const __dirname = dirname(fileURLToPath(import.meta.url));
const LOG_DIR = '/home/tony/CascadeProjects/chaba-tony-dell/logs';
const LOG_FILE = join(LOG_DIR, 'mcp-health-snapshot.log');
const INBOX_DIR = '/home/tony/CascadeProjects/chaba-tony-dell/docs/ssot/focus-inbox';
const WRAPPER = '/home/tony/.config/devin/mcp-scripts/mcp-health-ssh.sh';

mkdirSync(LOG_DIR, { recursive: true });

function log(message) {
  const line = `${new Date().toISOString()} ${message}`;
  console.error(line);
  writeFileSync(LOG_FILE, line + '\n', { flag: 'a' });
}

function send(proc, msg) {
  proc.stdin.write(JSON.stringify(msg) + '\n');
}

function callTool(proc, id, name, args = {}) {
  send(proc, {
    jsonrpc: '2.0',
    id,
    method: 'tools/call',
    params: { name, arguments: args }
  });
}

async function runSnapshot() {
  const proc = spawn(WRAPPER, [], { stdio: ['pipe', 'pipe', 'pipe'] });
  let buffer = '';
  let requestId = 1;

  const pending = new Map();
  const results = [];

  proc.stdout.on('data', (data) => {
    buffer += data.toString('utf8');
    const lines = buffer.split('\n');
    buffer = lines.pop();
    for (const line of lines) {
      if (!line.trim()) continue;
      try {
        const msg = JSON.parse(line);
        if (msg.id !== undefined && pending.has(msg.id)) {
          const { resolve } = pending.get(msg.id);
          pending.delete(msg.id);
          resolve(msg);
        } else if (msg.method === 'ping' && msg.id !== undefined) {
          send(proc, { jsonrpc: '2.0', id: msg.id, result: {} });
        } else if (msg.method) {
          // Ignore server notifications
        }
      } catch (e) {
        log(`JSON parse error: ${e.message}`);
      }
    }
  });

  proc.stderr.on('data', (data) => {
    const txt = data.toString('utf8').trim();
    if (txt) log(`server: ${txt}`);
  });

  const request = (name, args = {}) => new Promise((resolve, reject) => {
    const id = requestId++;
    pending.set(id, { resolve, reject });
    callTool(proc, id, name, args);
    setTimeout(() => {
      if (pending.has(id)) {
        pending.delete(id);
        reject(new Error(`Timeout waiting for ${name}`));
      }
    }, 120000);
  });

  try {
    send(proc, {
      jsonrpc: '2.0',
      id: requestId++,
      method: 'initialize',
      params: {
        protocolVersion: '2024-11-05',
        capabilities: {},
        clientInfo: { name: 'mcp-health-snapshot', version: '1.0' }
      }
    });

    // Wait briefly for initialize to be acknowledged before making calls
    await new Promise(r => setTimeout(r, 500));

    const result = await request('get_health_status');
    if (result.error) {
      throw new Error(result.error.message);
    }

    const text = result.result?.content?.[0]?.text;
    if (!text) {
      throw new Error('No text content in response');
    }

    const status = JSON.parse(text);
    const { healthy, degraded, error, unknown, total } = status.summary || {};
    log(`summary total=${total} healthy=${healthy} degraded=${degraded} error=${error} unknown=${unknown}`);

    const categories = status.services_by_category || {};
    const allServices = Object.values(categories).flat();
    const failing = allServices.filter(s =>
      s.status !== 'healthy' && s.status !== 'intentional'
    );

    if (failing.length > 0) {
      log(`failing services: ${failing.map(s => s.service).join(', ')}`);
      mkdirSync(INBOX_DIR, { recursive: true });
      const stamp = new Date().toISOString().replace(/[:.]/g, '-').slice(0, 19);
      const inbox = join(INBOX_DIR, `mcp-health-snapshot-${stamp}.yml`);
      const txt = `title: Health Snapshot Alert\nsubtitle: ${failing.length} services not healthy\nicon: heart-pulse\nfocus:\n  label: 'mcp-health: ${failing.length} failing'\n  text: |\n${failing.map(s => `    - ${s.category} / ${s.service}: ${s.status}${s.error ? ' - ' + s.error : ''}`).join('\n')}\n  status: draft\n  priority: high\n  tags:\n  - health\n  - monitoring\n  - snapshot\n  subtasks:\n${failing.map(s => `  - label: Investigate ${s.service}\n    status: not_started`).join('\n')}\nsource:\n  session: mcp-health-snapshot\n  date: ${new Date().toISOString().slice(0, 10)}\n`;
      writeFileSync(inbox, txt);
    } else {
      log('all healthy');
    }

    proc.stdin.end();
    // Give the server a moment to exit cleanly, then force kill and exit
    setTimeout(() => {
      if (proc.exitCode === null) {
        log('force killing mcp-health process');
        proc.stdout.removeAllListeners();
        proc.stderr.removeAllListeners();
        proc.stdin.removeAllListeners();
        proc.stdout.destroy();
        proc.stderr.destroy();
        proc.stdin.destroy();
        proc.kill('SIGKILL');
      }
      process.exit(process.exitCode || 0);
    }, 2000);
  } catch (e) {
    log(`snapshot failed: ${e.message}`);
    if (proc.exitCode === null) {
      proc.stdout.removeAllListeners();
      proc.stderr.removeAllListeners();
      proc.stdin.removeAllListeners();
      proc.stdout.destroy();
      proc.stderr.destroy();
      proc.stdin.destroy();
      proc.kill('SIGKILL');
    }
    process.exit(1);
  }
}

runSnapshot();
