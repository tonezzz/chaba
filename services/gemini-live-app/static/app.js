let ws = null;
let audioCtx = null;
let micStream = null;
let processor = null;
let inputNode = null;
let isRecording = false;
let playbackQueue = [];
let isPlaying = false;

const elStatus = document.getElementById('status');
const elSource = document.getElementById('source');
const elLog = document.getElementById('log');
const btnConnect = document.getElementById('connect');
const btnDisconnect = document.getElementById('disconnect');
const btnPTT = document.getElementById('ptt');
const btnRefresh = document.getElementById('refresh');
const inputText = document.getElementById('text');

function logLine(s) {
  elLog.textContent += s + "\n";
  elLog.scrollTop = elLog.scrollHeight;
}

function wsUrl() {
  const proto = location.protocol === 'https:' ? 'wss:' : 'ws:';
  return proto + '//' + location.host + '/ws/live';
}

async function refreshSource() {
  try {
    const r = await fetch('/source');
    const j = await r.json();
    if (j && j.ok) {
      elSource.textContent = `source: ${j.title || j.url} (${j.updated_at})`;
    } else {
      elSource.textContent = 'source: (missing SOURCE_URL)';
    }
  } catch {
    elSource.textContent = 'source: (error)';
  }
}

async function forceRefreshSource() {
  try {
    const r = await fetch('/refresh', { method: 'POST' });
    const j = await r.json();
    if (j && j.ok) {
      await refreshSource();
      logLine('source refreshed');
    } else {
      logLine('refresh failed');
    }
  } catch (e) {
    logLine('refresh error: ' + String(e));
  }
}

function decodeB64ToBytes(b64) {
  const bin = atob(b64);
  const bytes = new Uint8Array(bin.length);
  for (let i = 0; i < bin.length; i++) bytes[i] = bin.charCodeAt(i);
  return bytes;
}

function pcm16leToFloat32(pcmBytes) {
  const view = new DataView(pcmBytes.buffer, pcmBytes.byteOffset, pcmBytes.byteLength);
  const out = new Float32Array(pcmBytes.byteLength / 2);
  for (let i = 0; i < out.length; i++) {
    const v = view.getInt16(i * 2, true);
    out[i] = Math.max(-1, Math.min(1, v / 32768));
  }
  return out;
}

async function ensureAudioCtx() {
  if (!audioCtx) audioCtx = new (window.AudioContext || window.webkitAudioContext)();
  if (audioCtx.state !== 'running') await audioCtx.resume();
}

async function startMic() {
  await ensureAudioCtx();
  micStream = await navigator.mediaDevices.getUserMedia({ audio: true });
  inputNode = audioCtx.createMediaStreamSource(micStream);

  // ScriptProcessor is deprecated but fine for MVP.
  processor = audioCtx.createScriptProcessor(4096, 1, 1);
  processor.onaudioprocess = (e) => {
    if (!isRecording || !ws || ws.readyState !== WebSocket.OPEN) return;
    const input = e.inputBuffer.getChannelData(0);

    // Downsample to 16k and convert to pcm16.
    const inRate = audioCtx.sampleRate;
    const outRate = 16000;
    const ratio = inRate / outRate;
    const outLen = Math.floor(input.length / ratio);
    const pcm = new Int16Array(outLen);
    for (let i = 0; i < outLen; i++) {
      const idx = Math.floor(i * ratio);
      const s = input[idx] || 0;
      const v = Math.max(-1, Math.min(1, s));
      pcm[i] = v < 0 ? v * 32768 : v * 32767;
    }

    const bytes = new Uint8Array(pcm.buffer);
    let bin = '';
    for (let i = 0; i < bytes.length; i++) bin += String.fromCharCode(bytes[i]);
    const b64 = btoa(bin);

    ws.send(JSON.stringify({
      type: 'audio',
      data: b64,
      mimeType: 'audio/pcm;rate=16000'
    }));
  };

  inputNode.connect(processor);
  processor.connect(audioCtx.destination);
}

function stopMic() {
  try {
    if (processor) processor.disconnect();
    if (inputNode) inputNode.disconnect();
  } catch {}
  processor = null;
  inputNode = null;

  try {
    if (micStream) {
      for (const t of micStream.getTracks()) t.stop();
    }
  } catch {}
  micStream = null;
}

async function playPcmChunk(pcmFloat32, sampleRate) {
  await ensureAudioCtx();

  // Resample if needed
  let data = pcmFloat32;
  if (sampleRate && sampleRate !== audioCtx.sampleRate) {
    const ratio = sampleRate / audioCtx.sampleRate;
    const outLen = Math.floor(pcmFloat32.length / ratio);
    const out = new Float32Array(outLen);
    for (let i = 0; i < outLen; i++) {
      const idx = Math.floor(i * ratio);
      out[i] = pcmFloat32[idx] || 0;
    }
    data = out;
  }

  const buf = audioCtx.createBuffer(1, data.length, audioCtx.sampleRate);
  buf.getChannelData(0).set(data);
  const src = audioCtx.createBufferSource();
  src.buffer = buf;
  src.connect(audioCtx.destination);

  await new Promise((resolve) => {
    src.onended = resolve;
    src.start();
  });
}

async function drainPlayback() {
  if (isPlaying) return;
  isPlaying = true;
  try {
    while (playbackQueue.length) {
      const it = playbackQueue.shift();
      await playPcmChunk(it.data, it.sampleRate);
    }
  } finally {
    isPlaying = false;
  }
}

function connect() {
  if (ws && ws.readyState === WebSocket.OPEN) return;

  ws = new WebSocket(wsUrl());
  elStatus.textContent = 'connecting';

  ws.onopen = async () => {
    elStatus.textContent = 'connected';
    btnDisconnect.disabled = false;
    btnPTT.disabled = false;
    logLine('ws connected');
    await refreshSource();
  };

  ws.onclose = () => {
    elStatus.textContent = 'disconnected';
    btnDisconnect.disabled = true;
    btnPTT.disabled = true;
    isRecording = false;
    stopMic();
    logLine('ws closed');
  };

  ws.onerror = (e) => {
    logLine('ws error');
  };

  ws.onmessage = (ev) => {
    let msg = null;
    try { msg = JSON.parse(ev.data); } catch { return; }
    if (!msg || !msg.type) return;

    if (msg.type === 'state') {
      logLine('state: ' + msg.state + ' model=' + (msg.model || ''));
      const src = msg.source || {};
      if (src && (src.title || src.url)) {
        elSource.textContent = `source: ${src.title || src.url} (${src.updated_at || ''})`;
      }
      return;
    }

    if (msg.type === 'text') {
      logLine('assistant: ' + String(msg.text || ''));
      return;
    }

    if (msg.type === 'transcript') {
      logLine('transcript: ' + String(msg.text || ''));
      return;
    }

    if (msg.type === 'citations') {
      console.groupCollapsed('citations');
      console.log(msg);
      if (Array.isArray(msg.chunks)) console.table(msg.chunks);
      console.groupEnd();
      return;
    }

    if (msg.type === 'audio') {
      const b64 = String(msg.data || '');
      if (!b64) return;
      const bytes = decodeB64ToBytes(b64);
      const pcm = pcm16leToFloat32(bytes);
      const sr = Number(msg.sampleRate || 24000);
      playbackQueue.push({ data: pcm, sampleRate: sr });
      drainPlayback();
      return;
    }

    if (msg.type === 'error') {
      logLine('error: ' + String(msg.message || msg.kind || 'error'));
      if (msg.detail) logLine('detail: ' + String(msg.detail));
      return;
    }
  };
}

btnConnect.onclick = () => connect();
btnDisconnect.onclick = () => { if (ws) ws.close(); };
btnRefresh.onclick = () => forceRefreshSource();

btnPTT.addEventListener('mousedown', async () => {
  if (!ws || ws.readyState !== WebSocket.OPEN) return;
  if (isRecording) return;
  isRecording = true;
  await startMic();
  logLine('recording...');
});

btnPTT.addEventListener('mouseup', async () => {
  if (!ws || ws.readyState !== WebSocket.OPEN) return;
  if (!isRecording) return;
  isRecording = false;
  stopMic();
  ws.send(JSON.stringify({ type: 'audio_stream_end' }));
  logLine('end utterance');
});

btnPTT.addEventListener('mouseleave', async () => {
  // If mouse leaves while holding, treat as release.
  if (!isRecording) return;
  btnPTT.dispatchEvent(new MouseEvent('mouseup'));
});

inputText.addEventListener('keydown', (e) => {
  if (e.key !== 'Enter' || e.shiftKey) return;
  e.preventDefault();
  const txt = String(inputText.value || '').trim();
  if (!txt) return;
  if (!ws || ws.readyState !== WebSocket.OPEN) {
    logLine('not connected');
    return;
  }
  inputText.value = '';
  logLine('you: ' + txt);
  ws.send(JSON.stringify({ type: 'text', text: txt }));
});

// Spacebar push-to-talk
window.addEventListener('keydown', (e) => {
  if (e.code !== 'Space') return;
  if (e.repeat) return;
  if (document.activeElement === inputText) return;
  btnPTT.dispatchEvent(new MouseEvent('mousedown'));
});
window.addEventListener('keyup', (e) => {
  if (e.code !== 'Space') return;
  if (document.activeElement === inputText) return;
  btnPTT.dispatchEvent(new MouseEvent('mouseup'));
});

refreshSource();
