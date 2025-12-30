import fs from 'fs';
import path from 'path';
import { fileURLToPath } from 'url';

const here = path.dirname(fileURLToPath(import.meta.url));
const projectRoot = path.resolve(here, '..');

const outDir = path.join(projectRoot, 'out');
const targetDir = path.resolve(projectRoot, '..', 'ai_app');

function copyDir(src, dest) {
  fs.mkdirSync(dest, { recursive: true });
  for (const entry of fs.readdirSync(src, { withFileTypes: true })) {
    const srcPath = path.join(src, entry.name);
    const destPath = path.join(dest, entry.name);
    if (entry.isDirectory()) {
      copyDir(srcPath, destPath);
    } else if (entry.isSymbolicLink()) {
      const link = fs.readlinkSync(srcPath);
      fs.symlinkSync(link, destPath);
    } else {
      fs.copyFileSync(srcPath, destPath);
    }
  }
}

if (!fs.existsSync(outDir)) {
  console.error(`[publish] missing out directory: ${outDir}`);
  console.error('[publish] run `npm run build` first');
  process.exit(1);
}

fs.rmSync(targetDir, { recursive: true, force: true });
copyDir(outDir, targetDir);

console.log(`[publish] copied ${outDir} -> ${targetDir}`);
