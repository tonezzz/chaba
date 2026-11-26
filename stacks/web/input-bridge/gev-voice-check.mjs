#!/usr/bin/env node
"use strict";
// gev-voice-check — regression check for the GEV voice invariants on the
// vendored bundle (kanban card gev-voice).
//
// The gods-eye-view source repo is not dispatchable (no pushable remote,
// not in dispatch-repos.conf — see gev-program-design), so the truth we can
// test is the staged bundle in stacks/web/public/apps/gev/assets/. Two
// layers of checks:
//
//   STRUCTURAL — the mic chain is source -> GainNode -> ScriptProcessor,
//   gain starts at 0, setMicrophoneEnabled writes gain 1/0 on the same
//   transition as the recording flag, and the ws message listener handles
//   inbound binary (playback path) + {type:interrupted} flush.
//
//   BEHAVIORAL — the real onaudioprocess + setMicrophoneEnabled bodies are
//   extracted from the bundle and driven against a mock audio graph. We
//   assert the card metric directly: while muted, ZERO outbound PCM frames
//   AND the signal reaching the processor is all zeros — i.e. the GainNode
//   carries the invariant, not the recording flag alone. A mutation run
//   (flag gate stripped) must still yield silence; that is what proves the
//   gain gate works and this check can catch its removal.
//
//   node gev-voice-check.mjs                    # repo bundle
//   node gev-voice-check.mjs --live             # live bundle on tony-dell
//   node gev-voice-check.mjs --bundle <path>
//
// Env: GEV_URL (default https://tony-dell.taila0626a.ts.net/apps/gev/)
// Exit 0 = all checks passed (WARNs allowed), 1 = a check failed,
// 2 = could not load a bundle.
import fs from 'node:fs';
import path from 'node:path';
import { fileURLToPath } from 'node:url';

const REPO = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '../../..');
const ASSETS = path.join(REPO, 'stacks/web/public/apps/gev/assets');
const INDEX_HTML = path.join(REPO, 'stacks/web/public/apps/gev/index.html');
const BRIDGE = path.join(REPO, 'stacks/tony-dell/gev-gemini/bridge.py');
const GEV_URL = process.env.GEV_URL || 'https://tony-dell.taila0626a.ts.net/apps/gev/';

const checks = [];
function warn(name, detail = '') {
  console.log(`WARN  ${name}` + (detail ? `  (${detail})` : ''));
}
// PASS/FAIL/WARN convention of the sibling check scripts
function rec(name, ok, detail = '') {
  console.log(`${ok ? 'PASS' : 'FAIL'}  ${name}` + (detail ? `  (${detail})` : ''));
  checks.push(Boolean(ok));
}

// ---------- bundle loading ------------------------------------------------
function repoBundle() {
  const hits = fs.readdirSync(ASSETS).filter(f => /^index-.*\.js$/.test(f));
  if (!hits.length) throw new Error(`no index-*.js under ${ASSETS}`);
  // the entry bundle is whichever index-*.js index.html loads — vendor
  // chunks (index-*.js without the voice controller) also match the glob.
  try {
    const m = fs.readFileSync(INDEX_HTML, 'utf8')
      .match(/src="\/apps\/gev\/assets\/(index-[^"]+\.js)"/);
    if (m && hits.includes(m[1])) {
      return { name: m[1], src: fs.readFileSync(path.join(ASSETS, m[1]), 'utf8') };
    }
  } catch { /* fall through to name-sort */ }
  const pick = hits
    // prefer the highest -vN patched copy over the bare build
    .sort((a, b) => (b.match(/-v(\d+)\.js$/)?.[1] | 0) - (a.match(/-v(\d+)\.js$/)?.[1] | 0))[0];
  return { name: pick, src: fs.readFileSync(path.join(ASSETS, pick), 'utf8') };
}

async function liveBundle() {
  const html = await (await fetch(GEV_URL)).text();
  const m = html.match(/src="\/apps\/gev\/assets\/(index-[^"]+\.js)"/);
  if (!m) throw new Error(`no bundle reference in ${GEV_URL}`);
  const url = new URL('/apps/gev/assets/' + m[1], GEV_URL).href;
  const res = await fetch(url);
  if (!res.ok) throw new Error(`GET ${url} -> ${res.status}`);
  return { name: m[1], src: await res.text(), html };
}

// ---------- extraction helpers --------------------------------------------
function methodBody(src, sig) {
  // sig is the method signature WITHOUT the opening brace
  const at = src.indexOf(sig);
  if (at < 0) return null;
  const open = src.indexOf('{', at + sig.length);
  let depth = 0;
  for (let i = open; i < src.length; i++) {
    if (src[i] === '{') depth++;
    else if (src[i] === '}' && --depth === 0) return src.slice(open + 1, i);
  }
  return null;
}

function arrowBody(src, anchor) {
  const at = src.indexOf(anchor);
  if (at < 0) return null;
  const open = src.indexOf('{', at);
  let depth = 0;
  for (let i = open; i < src.length; i++) {
    if (src[i] === '{') depth++;
    else if (src[i] === '}' && --depth === 0) return src.slice(open + 1, i);
  }
  return null;
}

// ---------- behavioral harness --------------------------------------------
// Emulates the WebAudio graph at PCM level: the mic always emits non-zero
// frames; the GainNode scales them; the extracted onaudioprocess body runs
// on the post-gain signal; flushAndSend-equivalent ships what was buffered.
function makeHarness(setMicSrc, onaudioSrc, setMicParam, onaudioParam) {
  const ctx = {
    isRecording: false,
    micGain: { gain: { value: 0 } },
    recordedChunks: [],
    ui: null,
    sent: [],
  };
  const setMic = new Function(setMicParam || 't', setMicSrc);
  const onaudio = new Function(onaudioParam || 'e', onaudioSrc);
  const tick = n => {
    for (let i = 0; i < n; i++) {
      // live mic frame (non-zero) scaled by the gain node
      const raw = Float32Array.from({ length: 64 }, () => 0.5);
      const gained = raw.map(v => v * ctx.micGain.gain.value);
      onaudio.call(ctx, { inputBuffer: { getChannelData: () => gained } });
    }
  };
  return {
    ctx,
    setMic: v => setMic.call(ctx, v),
    tick,
    flush() {
      const out = ctx.recordedChunks.flatMap(c => [...c]);
      ctx.recordedChunks = [];
      ctx.sent.push(out);
      return out;
    },
  };
}

const nonzero = a => a.reduce((n, v) => n + (v !== 0 ? 1 : 0), 0);

async function main() {
  const argv = process.argv.slice(2);
  const live = argv.includes('--live');
  const bundleArg = argv.find(a => a.startsWith('--bundle='));
  let bundle;
  if (bundleArg) {
    const p = bundleArg.slice('--bundle='.length);
    bundle = { name: path.basename(p), src: fs.readFileSync(p, 'utf8') };
  } else if (live) {
    bundle = await liveBundle();
  } else {
    bundle = repoBundle();
  }
  const s = bundle.src;
  console.log(`bundle: ${bundle.name} (${s.length} bytes)${live ? ' [live]' : ''}`);

  // ---- structural: capture chain ------------------------------------------
  rec('mic capture chain exists (MediaStreamSource -> Gain -> ScriptProcessor)',
    s.includes('createMediaStreamSource') && s.includes('createGain') &&
    s.includes('createScriptProcessor'));
  rec('gain node starts muted (gain.value=0 at graph build)',
    /micGain\.gain\.value=0/.test(s) || /\.gain\.value=0/.test(s));
  rec('mic source routes through the gain node',
    /connect\(this\.micGain\)/.test(s) && /this\.micGain\.connect\(/.test(s));
  rec('processor output reaches ctx.destination (keeps graph alive)',
    /processor\.connect\(this\.micCtx\.destination\)/.test(s));

  // param names are minifier-renamed per build (t, s, e, ...) — capture them
  const setMicSig = s.match(/setMicrophoneEnabled\((\w+)\)/);
  const setMicParam = setMicSig && setMicSig[1];
  const setMicBody = setMicSig && methodBody(s, setMicSig[0]);
  rec('setMicrophoneEnabled method located', !!setMicBody);
  rec('setMicrophoneEnabled gates the GAIN on the same transition (v?1:0)',
    !!setMicBody && /gain\.value=\w+\?1:0/.test(setMicBody));
  rec('setMicrophoneEnabled sets the recording flag too',
    !!setMicBody && /isRecording=!!\w+/.test(setMicBody));

  const onaudioSig = s.match(/\.onaudioprocess=(\w+)=>/);
  const onaudioParam = onaudioSig && onaudioSig[1];
  const onaudioBody = arrowBody(s, '.onaudioprocess=');
  rec('onaudioprocess handler located', !!onaudioBody);
  rec('onaudioprocess buffers only while recording (flag gate present)',
    !!onaudioBody && /isRecording/.test(onaudioBody) &&
    /recordedChunks\.push/.test(onaudioBody));

  // ---- behavioral: mute invariant -----------------------------------------
  if (setMicBody && onaudioBody) {
    const h = makeHarness(setMicBody, onaudioBody, setMicParam, onaudioParam);

    // A. positive control — unmuted capture produces non-zero PCM
    h.setMic(true);
    h.tick(3);
    const voiced = h.flush();
    rec('unmuted capture produces non-zero PCM (positive control)',
      nonzero(voiced) > 0, `${nonzero(voiced)}/${voiced.length} non-zero samples`);

    // B. the card metric — muted => zero outbound PCM frames
    h.setMic(false);
    h.tick(4);
    const muted = h.flush();
    rec('muted => zero outbound PCM frames',
      muted.length === 0 && ctxGainIsZero(h),
      `${muted.length} frames buffered, gain=${h.ctx.micGain.gain.value}`);

    // C. mid-stream mute — recording tail flushes only pre-mute audio
    h.setMic(true); h.tick(2);
    h.setMic(false); h.tick(3);
    const tail = h.flush();
    rec('mid-stream mute flushes only pre-mute audio',
      tail.length === 128 && nonzero(tail) === 128,
      `${tail.length} samples, ${nonzero(tail)} non-zero (expect 128/128)`);

    // D. mutation: strip the flag gate — the GAIN alone must still silence.
    //    This is the proof the flag alone is not what protects the wire:
    //    if the isRecording check regresses, muted frames are zeros.
    const noFlag = onaudioBody.replace(/this\.isRecording&&/, '');
    const hm = makeHarness(setMicBody, noFlag, setMicParam, onaudioParam);
    hm.setMic(false);
    hm.tick(3);
    const leaked = hm.flush();
    rec('mutation(flag stripped): muted frames are silence via gain gate',
      leaked.length > 0 && nonzero(leaked) === 0,
      `${leaked.length} samples leaked, ${nonzero(leaked)} non-zero`);

    // E. sanity: harness would catch a dead gain gate — flag slip under a
    //    regressed gain (stuck at 1) leaks live audio. Guards the sim itself.
    const badSet = setMicBody.replace(/gain\.value=\w+\?1:0/, 'gain.value=1');
    const hb = makeHarness(badSet, onaudioBody, setMicParam, onaudioParam);
    hb.setMic(false);
    hb.ctx.isRecording = true;   // simulate a flag slip while "muted"
    hb.tick(2);
    const slip = hb.flush();
    rec('harness detects a flag slip when gain gate is absent (self-test)',
      nonzero(slip) > 0, `${nonzero(slip)} non-zero samples`);
  }

  // ---- playback path -------------------------------------------------------
  rec('ws listener routes inbound binary frames to playback',
    /i\.data instanceof ArrayBuffer/.test(s) && s.includes('playGeminiAudio'));
  rec('playback decodes PCM16 -> Float32 through an AudioContext',
    /new Int16Array\(t\)/.test(s) && /createBuffer\(1,/.test(s) &&
    /createBufferSource\(\)/.test(s));
  rec('{type:interrupted} flushes the playback queue',
    s.includes('t.type==="interrupted"?this.stopGeminiAudio()'));
  rec('cleanupSession stops playback + closes the play context',
    s.includes('this.playCtx&&(this.playCtx.close()'));

  if (!live && fs.existsSync(BRIDGE)) {
    const b = fs.readFileSync(BRIDGE, 'utf8');
    rec('bridge forwards model_turn inline_data as binary frames',
      /getattr\(sc, 'model_turn'/.test(b) && /websocket\.send\(data\)/.test(b),
      'stacks/tony-dell/gev-gemini/bridge.py');
    rec('bridge still requests AUDIO response modality',
      b.includes("'response_modalities': ['AUDIO']"));
  }

  // ---- iOS constraint -------------------------------------------------------
  if (!live) {
    const html = fs.readFileSync(INDEX_HTML, 'utf8');
    rec('index.html keeps apple-mobile-web-app-capable=no (iOS mic Safari-only)',
      /apple-mobile-web-app-capable" content="no"/.test(html));
  } else if (bundle.html) {
    rec('live index.html keeps apple-mobile-web-app-capable=no',
      /apple-mobile-web-app-capable" content="no"/.test(bundle.html));
  }

  // ---- live/repo drift ------------------------------------------------------
  if (live) {
    try {
      const repo = repoBundle();
      if (repo.name !== bundle.name) {
        warn(`live bundle ${bundle.name} != repo ${repo.name} — deploy drift`);
      }
    } catch (e) {
      warn(`repo bundle unreadable for drift compare: ${e.message}`);
    }
  }

  const failed = checks.filter(c => !c).length;
  console.log(`gev-voice-check: ${checks.length - failed}/${checks.length} PASS` +
    (failed ? ` (${failed} FAIL)` : ''));
  process.exit(failed ? 1 : 0);
}

function ctxGainIsZero(h) { return h.ctx.micGain.gain.value === 0; }

main().catch(e => {
  console.error(`gev-voice-check: could not run: ${e.message}`);
  process.exit(2);
});
