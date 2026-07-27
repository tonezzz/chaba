import fs from 'node:fs';
import path from 'node:path';

const SRC = '../chaba/docs/overview';
const DST = 'public/docs/overview';
const MANIFEST = 'public/data/docs-overview.json';

function humanize(str) {
  return str.replace(/[-_]/g, ' ').replace(/\b\w/g, (c) => c.toUpperCase());
}

function parseName(filename) {
  const ext = path.extname(filename);
  const base = path.basename(filename, ext);
  const parts = base.split('.');
  if (parts.length >= 3) {
    return {
      group: parts[0],
      subgroup: parts[1],
      name: parts.slice(2).join('.'),
      title: humanize(parts.slice(2).join(' '))
    };
  }
  if (parts.length === 2) {
    return {
      group: parts[0],
      subgroup: 'General',
      name: parts[1],
      title: humanize(parts[1])
    };
  }
  return {
    group: 'Ungrouped',
    subgroup: 'General',
    name: base,
    title: humanize(base)
  };
}

function walk(dir, out = []) {
  if (!fs.existsSync(dir)) return out;
  for (const entry of fs.readdirSync(dir, { withFileTypes: true })) {
    const full = path.join(dir, entry.name);
    if (entry.isDirectory()) {
      walk(full, out);
    } else if (entry.isFile() && (full.endsWith('.yaml') || full.endsWith('.yml'))) {
      out.push(full);
    }
  }
  return out;
}

fs.mkdirSync(path.dirname(MANIFEST), { recursive: true });
fs.rmSync(DST, { recursive: true, force: true });
fs.mkdirSync(DST, { recursive: true });

const files = walk(path.resolve(SRC)).map((file) => path.relative(path.resolve(SRC), file));
const items = [];

for (const rel of files) {
  const srcPath = path.resolve(SRC, rel);
  const dstPath = path.join(DST, rel);
  fs.mkdirSync(path.dirname(dstPath), { recursive: true });
  fs.copyFileSync(srcPath, dstPath);
  const parsed = parseName(path.basename(rel));
  const content = fs.readFileSync(srcPath, 'utf8');
  const titleMatch = content.match(/^title:\s*(.+)$/m);
  if (titleMatch) parsed.title = titleMatch[1].trim();
  parsed.href = '/docs/overview/' + rel.replace(/\\/g, '/');
  items.push(parsed);
}

items.sort((a, b) => `${a.group}.${a.subgroup}.${a.name}`.localeCompare(`${b.group}.${b.subgroup}.${b.name}`));

fs.writeFileSync(MANIFEST, JSON.stringify({ items }, null, 2));
console.log(`Synced ${items.length} docs to ${MANIFEST}`);
