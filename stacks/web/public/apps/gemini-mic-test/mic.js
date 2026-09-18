const WS_URL = window.GEMINI_MIC_WS_URL ||
  (location.hostname === 'localhost'
    ? 'ws://localhost:3009/ws'
    : '/api/gemini-mic/ws');

const STATUS_LABELS = {
  idle: 'OFF',
  connecting: 'CONNECTING',
  listening: 'LISTENING',
  executing: 'EXECUTING',
  error: 'ERROR',
};

const root = document.getElementById('gemini-mic');
const button = document.getElementById('gemini-mic-button');
const statusEl = document.getElementById('gemini-mic-status');
const detail = document.getElementById('gemini-mic-detail');
const bars = Array.from(root.querySelectorAll('.gemini-mic-visualizer span'));

let ws = null;
let audioCtx = null;
let micStream = null;
let micSource = null;
let micProcessor = null;
let visualizerCtx = null;
let visualizerAnalyser = null;
let visualizerSource = null;
let visualizerData = null;
let visualizerFrame = null;
let outputCtx = null;
let outputProcessor = null;
let outputQueue = [];

function setStatus(st, msg = '') {
  root.dataset.status = st;
  statusEl.textContent = STATUS_LABELS[st] || st;
  if (msg) detail.textContent = msg;
}

function floatToInt16(floats) {
  const out = new Int16Array(floats.length);
  for (let i = 0; i < floats.length; i++) {
    const s = Math.max(-1, Math.min(1, floats[i]));
    out[i] = s < 0 ? s * 0x8000 : s * 0x7FFF;
  }
  return out;
}

function int16ToBase64(int16) {
  const buf = new ArrayBuffer(int16.length * 2);
  const view = new DataView(buf);
  for (let i = 0; i < int16.length; i++) view.setInt16(i * 2, int16[i], true);
  let bin = '';
  const bytes = new Uint8Array(buf);
  for (let i = 0; i < bytes.length; i++) bin += String.fromCharCode(bytes[i]);
  return btoa(bin);
}

function base64ToInt16(b64) {
  const bin = atob(b64);
  const arr = new Int16Array(bin.length / 2);
  const view = new DataView(new ArrayBuffer(bin.length));
  for (let i = 0; i < bin.length; i++) view.setUint8(i, bin.charCodeAt(i));
  for (let i = 0; i < arr.length; i++) arr[i] = view.getInt16(i * 2, true);
  return arr;
}

function int16ToFloat(int16) {
  const out = new Float32Array(int16.length);
  for (let i = 0; i < int16.length; i++) out[i] = int16[i] / 0x7FFF;
  return out;
}

function startVisualizer(stream) {
  stopVisualizer();
  const AudioContextClass = window.AudioContext || window.webkitAudioContext;
  if (!AudioContextClass || !stream) return;
  const ctx = new AudioContextClass({ sampleRate: 16000 });
  ctx.resume().catch(() => {});
  const analyser = ctx.createAnalyser();
  analyser.fftSize = 64;
  analyser.smoothingTimeConstant = 0.72;
  const src = ctx.createMediaStreamSource(stream);
  src.connect(analyser);
  visualizerCtx = ctx;
  visualizerAnalyser = analyser;
  visualizerSource = src;
  visualizerData = new Uint8Array(analyser.frequencyBinCount);

  const loop = () => {
    if (!visualizerAnalyser) return;
    const data = visualizerData;
    visualizerAnalyser.getByteFrequencyData(data);
    const binCount = data.length;
    bars.forEach((bar, i) => {
      const start = Math.floor((i / bars.length) * binCount);
      const end = Math.max(start + 1, Math.floor(((i + 1) / bars.length) * binCount));
      let e = 0;
      for (let b = start; b < end; b++) e += data[b];
      const n = Math.min(1, (e / (end - start)) / 190);
      const g = n <= 0.12 ? 0 : (n - 0.12) / (1 - 0.12);
      const shaped = Math.pow(g, 0.72);
      bar.style.height = `${Math.round(5 + shaped * 23)}px`;
      bar.style.opacity = `${(0.5 + shaped * 0.5).toFixed(2)}`;
    });
    visualizerFrame = requestAnimationFrame(loop);
  };
  loop();
}

function stopVisualizer() {
  if (visualizerFrame) cancelAnimationFrame(visualizerFrame);
  visualizerFrame = null;
  if (visualizerSource) { try { visualizerSource.disconnect(); } catch {} }
  if (visualizerAnalyser) { try { visualizerAnalyser.disconnect(); } catch {} }
  if (visualizerCtx) { visualizerCtx.close().catch(() => {}); }
  visualizerSource = null;
  visualizerAnalyser = null;
  visualizerData = null;
  visualizerCtx = null;
  for (const bar of bars) { bar.style.removeProperty('height'); bar.style.removeProperty('opacity'); }
}

function startPlayback() {
  if (outputProcessor) return;
  const ctx = new AudioContext({ sampleRate: 24000 });
  const proc = ctx.createScriptProcessor(4096, 0, 1);
  proc.onaudioprocess = (e) => {
    const out = e.outputBuffer.getChannelData(0);
    let written = 0;
    while (written < out.length && outputQueue.length) {
      const chunk = outputQueue[0];
      const take = Math.min(chunk.length, out.length - written);
      out.set(chunk.subarray(0, take), written);
      if (take === chunk.length) {
        outputQueue.shift();
      } else {
        outputQueue[0] = chunk.subarray(take);
      }
      written += take;
    }
    if (written < out.length) out.fill(0, written);
  };
  proc.connect(ctx.destination);
  outputCtx = ctx;
  outputProcessor = proc;
}

function stopPlayback() {
  if (outputProcessor) { try { outputProcessor.disconnect(); } catch {} }
  if (outputCtx) { outputCtx.close().catch(() => {}); }
  outputProcessor = null;
  outputCtx = null;
  outputQueue = [];
}

function playAudio(b64) {
  startPlayback();
  outputQueue.push(int16ToFloat(base64ToInt16(b64)));
}

async function startMic() {
  if (micStream) return;
  try {
    micStream = await navigator.mediaDevices.getUserMedia({
      audio: { sampleRate: 16000, channelCount: 1, echoCancellation: true, noiseSuppression: true },
    });
    audioCtx = new AudioContext({ sampleRate: 16000 });
    await audioCtx.resume();
    const source = audioCtx.createMediaStreamSource(micStream);
    const proc = audioCtx.createScriptProcessor(4096, 1, 1);
    proc.onaudioprocess = (e) => {
      if (!ws || ws.readyState !== 1) return;
      const floats = e.inputBuffer.getChannelData(0);
      const pcm = floatToInt16(floats);
      ws.send(JSON.stringify({ type: 'audio', data: int16ToBase64(pcm) }));
    };
    source.connect(proc);
    proc.connect(audioCtx.destination);
    micSource = source;
    micProcessor = proc;
    startVisualizer(micStream);
  } catch (e) {
    setStatus('error', 'Mic error: ' + e.message);
  }
}

function stopMic() {
  if (micProcessor) { try { micProcessor.disconnect(); } catch {} }
  if (micSource) { try { micSource.disconnect(); } catch {} }
  if (micStream) { micStream.getTracks().forEach((t) => t.stop()); }
  if (audioCtx) { audioCtx.close().catch(() => {}); }
  micProcessor = null;
  micSource = null;
  micStream = null;
  audioCtx = null;
  stopVisualizer();
}

function connect() {
  if (ws) return;
  setStatus('connecting', 'Connecting...');
  let url = WS_URL;
  if (!url.startsWith('ws://') && !url.startsWith('wss://')) {
    const proto = window.location.protocol === 'https:' ? 'wss:' : 'ws:';
    url = `${proto}//${window.location.host}${url}`;
  }
  ws = new WebSocket(url);
  ws.onopen = () => setStatus('listening', 'Listening...');
  ws.onclose = () => {
    setStatus('idle', 'VOICE STANDBY');
    ws = null;
    stopMic();
    stopPlayback();
  };
  ws.onerror = () => setStatus('error', 'WebSocket error');
  ws.onmessage = (e) => {
    let msg;
    try { msg = JSON.parse(e.data); } catch { return; }
    if (msg.type === 'error') {
      setStatus('error', msg.message);
      return;
    }
    if (msg.type === 'server-content') {
      const sc = msg.content || {};
      if (sc.inputTranscription?.text) setStatus('listening', 'You: ' + sc.inputTranscription.text);
      if (sc.outputTranscription?.text) setStatus('executing', 'Gemini: ' + sc.outputTranscription.text);
      if (sc.modelTurn?.parts) {
        for (const part of sc.modelTurn.parts) {
          if (part.inlineData?.data) playAudio(part.inlineData.data);
        }
      }
    }
    if (msg.type === 'status') detail.textContent = msg.message;
  };
}

function disconnect() {
  if (ws) { ws.close(); ws = null; }
}

button.addEventListener('click', async () => {
  if (ws) {
    disconnect();
  } else {
    await startMic();
    if (micStream) connect();
  }
});
