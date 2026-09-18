const TOKEN_URL = "/apps/gev/token";
const WS_BASE =
  "wss://generativelanguage.googleapis.com/ws/google.ai.generativelanguage.v1beta.GenerativeService.BidiGenerateContentConstrained?access_token=";

const SYSTEM_INSTRUCTION = "You are GEV Voice, a concise voice assistant.";

const root = document.getElementById("gemini-mic");
const button = document.getElementById("gemini-mic-button");
const statusEl = document.getElementById("gemini-mic-status");
const detail = document.getElementById("gemini-mic-detail");
const bars = Array.from(root.querySelectorAll(".gemini-mic-visualizer span"));

let ws = null;
let pendingClose = false;
let audioCtx = null;
let micStream = null;
let micSource = null;
let micProcessor = null;
let micResampler = null;
let visualizerCtx = null;
let visualizerAnalyser = null;
let visualizerSource = null;
let visualizerData = null;
let visualizerFrame = null;
let outputCtx = null;
let outputProcessor = null;
let outputResampler = null;

function setStatus(st, msg = "") {
  root.dataset.status = st;
  statusEl.textContent =
    { idle: "OFF", connecting: "CONN", listening: "ON", executing: "...", error: "ERR" }[st] || st;
  if (msg) detail.textContent = msg;
}

function floatToInt16(floats) {
  const out = new Int16Array(floats.length);
  for (let i = 0; i < floats.length; i++) {
    const s = Math.max(-1, Math.min(1, floats[i]));
    out[i] = s < 0 ? s * 0x8000 : s * 0x7fff;
  }
  return out;
}

function int16ToBase64(int16) {
  const buf = new ArrayBuffer(int16.length * 2);
  const view = new DataView(buf);
  for (let i = 0; i < int16.length; i++) view.setInt16(i * 2, int16[i], true);
  let bin = "";
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
  for (let i = 0; i < int16.length; i++) out[i] = int16[i] / 0x7fff;
  return out;
}

class Resampler {
  constructor(inputRate, outputRate) {
    this.step = inputRate / outputRate;
    this.buffer = [];
    this.phase = 0;
  }
  push(data) {
    for (let i = 0; i < data.length; i++) this.buffer.push(data[i]);
  }
  produce(n) {
    const out = new Float32Array(n);
    for (let j = 0; j < n; j++) {
      if (this.phase + 1 >= this.buffer.length) {
        out.fill(0, j);
        break;
      }
      const i = Math.floor(this.phase);
      const frac = this.phase - i;
      const a = this.buffer[i];
      const b = this.buffer[i + 1];
      out[j] = a + (b - a) * frac;
      this.phase += this.step;
    }
    this.prune();
    return out;
  }
  prune() {
    const lastIdx = this.buffer.length - 1;
    if (this.phase >= lastIdx) {
      this.buffer = this.buffer.slice(lastIdx);
      this.phase -= lastIdx;
    } else {
      const used = Math.floor(this.phase);
      if (used > 0) {
        this.buffer = this.buffer.slice(used);
        this.phase -= used;
      }
    }
  }
}

function startPlayback() {
  if (outputProcessor) return;
  const AudioContextClass = window.AudioContext || window.webkitAudioContext;
  if (!AudioContextClass) return;
  try {
    outputCtx = new AudioContextClass({ sampleRate: 24000 });
  } catch {
    outputCtx = new AudioContextClass();
  }
  outputResampler = new Resampler(24000, outputCtx.sampleRate);
  const proc = outputCtx.createScriptProcessor(4096, 0, 1);
  proc.onaudioprocess = (e) => {
    const out = e.outputBuffer.getChannelData(0);
    out.set(outputResampler.produce(out.length));
  };
  proc.connect(outputCtx.destination);
  outputProcessor = proc;
}

function stopPlayback() {
  if (outputProcessor) {
    try {
      outputProcessor.disconnect();
    } catch {}
  }
  if (outputCtx) {
    outputCtx.close().catch(() => {});
  }
  outputProcessor = null;
  outputCtx = null;
  outputResampler = null;
}

function playAudio(b64) {
  startPlayback();
  outputResampler.push(int16ToFloat(base64ToInt16(b64)));
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
      const n = Math.min(1, e / (end - start) / 190);
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
  if (visualizerSource) {
    try {
      visualizerSource.disconnect();
    } catch {}
  }
  if (visualizerAnalyser) {
    try {
      visualizerAnalyser.disconnect();
    } catch {}
  }
  if (visualizerCtx) {
    visualizerCtx.close().catch(() => {});
  }
  visualizerSource = null;
  visualizerAnalyser = null;
  visualizerData = null;
  visualizerCtx = null;
  for (const bar of bars) {
    bar.style.removeProperty("height");
    bar.style.removeProperty("opacity");
  }
}

async function startMic() {
  if (micStream) return;
  const AudioContextClass = window.AudioContext || window.webkitAudioContext;
  if (!AudioContextClass) {
    setStatus("error", "Web Audio not supported");
    return;
  }
  if (!navigator.mediaDevices || !navigator.mediaDevices.getUserMedia) {
    setStatus("error", "Microphone not available");
    return;
  }
  try {
    micStream = await navigator.mediaDevices.getUserMedia({
      audio: { echoCancellation: true, noiseSuppression: true },
    });
    try {
      audioCtx = new AudioContextClass({ sampleRate: 16000 });
    } catch {
      audioCtx = new AudioContextClass();
    }
    await audioCtx.resume();
    micResampler = new Resampler(audioCtx.sampleRate, 16000);
    const source = audioCtx.createMediaStreamSource(micStream);
    const proc = audioCtx.createScriptProcessor(4096, 1, 1);
    proc.onaudioprocess = (e) => {
      e.outputBuffer.getChannelData(0).fill(0);
      if (!micResampler) return;
      micResampler.push(e.inputBuffer.getChannelData(0));
      const pcm = floatToInt16(micResampler.drain());
      if (ws && ws.readyState === 1 && pcm.length) {
        const b64 = int16ToBase64(pcm);
        ws.send(
          JSON.stringify({
            realtimeInput: {
              audio: {
                data: b64,
                mimeType: "audio/pcm;rate=16000",
              },
            },
          })
        );
      }
    };
    source.connect(proc);
    proc.connect(audioCtx.destination);
    micSource = source;
    micProcessor = proc;
    startVisualizer(micStream);
  } catch (e) {
    setStatus("error", "Mic error: " + e.message);
  }
}

function stopMic() {
  if (micProcessor) {
    try {
      micProcessor.disconnect();
    } catch {}
  }
  if (micSource) {
    try {
      micSource.disconnect();
    } catch {}
  }
  if (micStream) {
    micStream.getTracks().forEach((t) => t.stop());
  }
  if (audioCtx) {
    audioCtx.close().catch(() => {});
  }
  micProcessor = null;
  micSource = null;
  micStream = null;
  audioCtx = null;
  micResampler = null;
  stopVisualizer();
}

async function connect() {
  if (ws) return;
  setStatus("connecting", "Getting token...");
  let token;
  try {
    const res = await fetch(TOKEN_URL);
    const data = await res.json();
    if (!res.ok || !data.token) throw new Error(data.error || "No token");
    token = data.token;
  } catch (e) {
    setStatus("error", "Token: " + e.message);
    return;
  }
  setStatus("connecting", "Connecting...");
  ws = new WebSocket(WS_BASE + token);
  ws.onopen = () => {
    const setup = {
      setup: {
        model: "models/gemini-3.1-flash-live-preview",
        generationConfig: {
          responseModalities: ["AUDIO"],
        },
        systemInstruction: { parts: [{ text: SYSTEM_INSTRUCTION }] },
      },
    };
    ws.send(JSON.stringify(setup));
    setStatus("listening", "Speak...");
  };
  ws.onerror = (e) => {
    setStatus("error", "WebSocket error");
    console.error(e);
  };
  ws.onclose = () => {
    setStatus("idle", "Standby");
    ws = null;
    pendingClose = false;
    stopMic();
    stopPlayback();
  };
  ws.onmessage = (e) => {
    let msg;
    try {
      msg = JSON.parse(e.data);
    } catch {
      return;
    }
    console.log("[GEV-DIRECT]", msg);
    if (msg.serverContent) {
      const sc = msg.serverContent;
      if (sc.outputTranscription && sc.outputTranscription.text) {
        detail.textContent = "Gemini: " + sc.outputTranscription.text;
      }
      if (sc.modelTurn && sc.modelTurn.parts) {
        for (const part of sc.modelTurn.parts) {
          if (part.inlineData && part.inlineData.data) playAudio(part.inlineData.data);
          if (part.text) detail.textContent = part.text;
        }
      }
      if (sc.turnComplete) {
        detail.textContent = "Done";
        if (pendingClose) {
          ws.close();
        }
      }
    }
    if (msg.toolCall) {
      // no tool runner yet in this prototype
      detail.textContent = "Tool: " + msg.toolCall.functionCalls.map((c) => c.name).join(", ");
    }
  };
  await startMic();
}

function finishTurn() {
  if (!ws) return;
  stopMic();
  pendingClose = true;
  setStatus("executing", "Thinking...");
  if (ws.readyState === 1) {
    ws.send(JSON.stringify({ clientContent: { turnComplete: true } }));
  }
}

button.addEventListener("click", () => {
  if (ws) {
    if (pendingClose) {
      ws.close();
    } else {
      finishTurn();
    }
  } else {
    connect();
  }
});
