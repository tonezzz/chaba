#!/usr/bin/env node
/*
 * Caddyfile format and syntax audit.
 * Requires caddy binary to be on PATH.
 */
import { spawnSync } from 'child_process';
import { fileURLToPath } from 'url';
import { dirname, join } from 'path';

const __dirname = dirname(fileURLToPath(import.meta.url));
const projectRoot = join(__dirname, '..', '..');
const caddyfile = join(projectRoot, 'stacks', 'web', 'Caddyfile');

function run(cmd, args) {
  const result = spawnSync(cmd, args, { stdio: 'pipe', encoding: 'utf8' });
  return {
    ok: result.status === 0,
    code: result.status,
    stdout: result.stdout?.trim() || '',
    stderr: result.stderr?.trim() || '',
  };
}

const fmt = run('caddy', ['fmt', '--overwrite', caddyfile]);
const adapt = run('caddy', ['adapt', '--config', caddyfile, '--adapter', 'caddyfile']);

if (!fmt.ok) {
  console.error(`Caddy format failed:\n${fmt.stderr || fmt.stdout}`);
  process.exit(1);
}

if (!adapt.ok) {
  console.error(`Caddy adapt failed:\n${adapt.stderr || adapt.stdout}`);
  process.exit(1);
}

console.log(JSON.stringify({ ok: true, file: caddyfile, message: 'Caddyfile format and syntax OK' }));
