#!/usr/bin/env node
"use strict";
// gev-patch-dist — idempotent post-build patcher for the GEV bundle.
//
// Codifies the "after every build, patch dist/assets/index-*.js" step from
// AGENTS.md (GEV Gemini Live voice deployment) so the patches survive a
// rebuild and are checkable in CI. The gods-eye-view repo is NOT
// dispatchable (no pushable remote — see kanban card gev-program-design),
// so the same rules also patch the vendored bundle staged in this repo at
// stacks/web/public/apps/gev/assets/.
//
// Patches:
//   api      "/api/...     -> "/apps/gev/api/...     (string literals only)
//   models   "/models/...  -> "/apps/gev/models/...  (string literals only)
//   msaa     msaaSamples:4 -> UA-gated 1 on iPad/iPhone (WebGL crash)
//   playback voice controller plays inbound binary PCM16@24k frames,
//            flushes on {type:interrupted}, closes ctx in cleanupSession
//
// The playback patch is what closes the playback gap on the client half —
// bridge.py (stacks/tony-dell/gev-gemini) forwards model_turn audio as
// binary ws frames; without this the page drops them on the floor.
//
// Usage:
//   node gev-patch-dist.mjs <index-*.js | dir-containing-it> [--check] [--quiet]
//     default : apply missing patches in place
//     --check : verify only — exit 0 fully patched, 1 patchable-but-unpatched,
//               2 anchor not found (bundle changed; update this script)
import fs from 'node:fs';
import path from 'node:path';

const PLAY_METHODS =
  'playGeminiAudio(t){try{let n=this.playCtx;if(!n){const s=window.AudioContext||window.webkitAudioContext;' +
  'if(!s)return;n=this.playCtx=new s({sampleRate:24e3}),n.resume().catch(()=>{}),this.playNext=0,' +
  'this.playSrcs=[]}const i=new Int16Array(t);if(!i.length)return;const o=n.createBuffer(1,i.length,24e3),' +
  'a=o.getChannelData(0);for(let e=0;e<i.length;e++)a[e]=i[e]/32768;const r=n.createBufferSource();' +
  'r.buffer=o,r.connect(n.destination),this.playSrcs.push(r),' +
  'r.onended=()=>{const e=this.playSrcs.indexOf(r);e>=0&&this.playSrcs.splice(e,1)};' +
  'const l=Math.max(n.currentTime,this.playNext);r.start(l),this.playNext=l+o.duration}' +
  'catch(n){console.warn("[GEV] playback:",n)}}' +
  'stopGeminiAudio(){try{if(this.playSrcs)for(const t of this.playSrcs.splice(0))try{t.stop()}catch{};' +
  'this.playNext=0}catch{}}';

const PATCHES = [
  {
    name: 'api prefix',
    appliedIf: s => !/['"`]\/api\//.test(s),
    apply: s => s.replace(/(['"`])\/api\//g, '$1/apps/gev/api/'),
  },
  {
    name: 'models prefix',
    appliedIf: s => !/['"`]\/models\//.test(s),
    apply: s => s.replace(/(['"`])\/models\//g, '$1/apps/gev/models/'),
  },
  {
    name: 'msaaSamples iOS guard',
    anchor: 'msaaSamples:4',
    appliedIf: s => s.includes('msaaSamples:/iPad|iPhone|iPod/'),
    apply: s => s.replace('msaaSamples:4',
      'msaaSamples:/iPad|iPhone|iPod/.test(navigator.userAgent)?1:4'),
  },
  {
    name: 'voice binary listener',
    anchor: 'addEventListener("message",i=>{if(this.ws===n&&typeof i.data=="string")',
    appliedIf: s => s.includes('i.data instanceof ArrayBuffer'),
    // regex, not a literal: the JSON temp var is renamed by the minifier on
    // every rebuild (was `s`, then `o` in index-Bd5DfCi5) — capture it.
    apply: s => s.replace(
      /addEventListener\("message",i=>\{if\(this\.ws===n&&typeof i\.data=="string"\)try\{const (\w+)=JSON\.parse\(i\.data\);this\.handleGeminiMessage\(\1\)\}catch\{\}\}\)/,
      'addEventListener("message",i=>{if(this.ws!==n)return;' +
      'if(typeof i.data=="string")try{const $1=JSON.parse(i.data);' +
      'this.handleGeminiMessage($1)}catch{}else if(i.data instanceof ArrayBuffer)' +
      'try{this.playGeminiAudio(i.data)}catch{}})'),
  },
  {
    name: 'voice playback methods',
    anchor: 'shortcutVisibilityHandler=null}}',
    appliedIf: s => s.includes('playGeminiAudio(t){'),
    apply: s => s.replace('shortcutVisibilityHandler=null}}',
      'shortcutVisibilityHandler=null}' + PLAY_METHODS + '}'),
  },
  {
    name: 'interrupted flush',
    anchor: 'async handleGeminiMessage(t){t.type==="status"||(',
    appliedIf: s => s.includes('t.type==="interrupted"?this.stopGeminiAudio()'),
    apply: s => s.replace('async handleGeminiMessage(t){t.type==="status"||(',
      'async handleGeminiMessage(t){t.type==="interrupted"?this.stopGeminiAudio():' +
      't.type==="status"||('),
  },
  {
    name: 'cleanup playback',
    anchor: 'cleanupSession(){var t;if(this.closingAfterDone=!1,',
    appliedIf: s => s.includes('this.playCtx&&(this.playCtx.close()'),
    apply: s => s.replace('cleanupSession(){var t;if(this.closingAfterDone=!1,',
      'cleanupSession(){var t;if(this.stopGeminiAudio&&this.stopGeminiAudio(),' +
      'this.playCtx&&(this.playCtx.close().catch(()=>{}),this.playCtx=null),' +
      'this.closingAfterDone=!1,'),
  },
];

function resolveBundle(p) {
  const st = fs.statSync(p);
  if (st.isFile()) return p;
  const hits = fs.readdirSync(p).filter(f => /^index-.*\.js$/.test(f));
  if (!hits.length) throw new Error(`${p}: no index-*.js`);
  // the entry bundle is whichever index-*.js the sibling/parent index.html
  // loads — vendor chunks (index-*.js without the app code) also match the
  // glob, so never guess by name alone.
  for (const html of [path.join(p, 'index.html'), path.join(p, '..', 'index.html')]) {
    try {
      const m = fs.readFileSync(html, 'utf8')
        .match(/src="[^"]*?assets\/(index-[^"]+\.js)"/);
      if (m && hits.includes(m[1])) return path.join(p, m[1]);
    } catch { /* no index.html here */ }
  }
  // fallback: multiple bundles coexist (unpatched build + staged -vN
  // copies): prefer the highest -vN patched copy — same rule
  // gev-voice-check.mjs uses.
  hits.sort((a, b) => (b.match(/-v(\d+)\.js$/)?.[1] | 0) -
                      (a.match(/-v(\d+)\.js$/)?.[1] | 0));
  return path.join(p, hits[0]);
}

function main() {
  const argv = process.argv.slice(2);
  const checkOnly = argv.includes('--check');
  const quiet = argv.includes('--quiet');
  const target = argv.find(a => !a.startsWith('--'));
  if (!target) {
    console.error('usage: gev-patch-dist.mjs <index-*.js|dir> [--check] [--quiet]');
    process.exit(2);
  }
  const file = resolveBundle(target);
  let src = fs.readFileSync(file, 'utf8');

  let missing = 0, applied = 0, already = 0, noanchor = 0;
  for (const p of PATCHES) {
    if (p.appliedIf(src)) { already++; continue; }
    if (checkOnly) { missing++; if (!quiet) console.log(`MISS ${p.name}`); continue; }
    if (p.anchor && !src.includes(p.anchor)) {
      noanchor++;
      console.log(`NOANCHOR ${p.name} — anchor not found, bundle changed?`);
      continue;
    }
    const out = p.apply(src);
    if (out === src) {
      noanchor++;
      console.log(`NOOP ${p.name} — apply() changed nothing`);
      continue;
    }
    src = out; applied++;
    if (!quiet) console.log(`APPLY ${p.name}`);
  }

  if (!checkOnly && applied) {
    fs.writeFileSync(file, src);
    if (!quiet) console.log(`wrote ${file} (+${src.length} bytes total, ${applied} patch(es))`);
  }
  if (!quiet) {
    console.log(`${file}: ${already} already, ${applied} applied, ` +
      `${missing} missing, ${noanchor} anchor-miss`);
  }
  if (noanchor) process.exit(2);
  process.exit(missing ? 1 : 0);
}

main();
