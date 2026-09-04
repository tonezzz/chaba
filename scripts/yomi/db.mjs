import { Pool } from 'pg';
import { existsSync, readFileSync } from 'node:fs';

const ENV_PATH = '/home/tony/CascadeProjects/chaba-tony-dell/stacks/web/.env';

function loadEnv(path) {
  if (!existsSync(path)) return;
  for (const line of readFileSync(path, 'utf8').split('\n')) {
    const m = line.match(/^([A-Za-z_][A-Za-z0-9_]*)=(.*)$/);
    if (!m) continue;
    const [, key, value] = m;
    if (process.env[key] != null) continue;
    process.env[key] = value.trim().replace(/\$\$/g, '$');
  }
}

loadEnv(ENV_PATH);

const user = process.env.POSTGRES_USER || 'chaba';
const password = process.env.POSTGRES_PASSWORD || 'chabapass';
const db = process.env.POSTGRES_DB || 'chaba';
const host = process.env.POSTGRES_HOST || '127.0.0.1';
const port = process.env.POSTGRES_PORT || '5432';

const pool = new Pool({
  connectionString: process.env.DATABASE_URL
    || `postgres://${user}:${password}@${host}:${port}/${db}`,
});

export default pool;
