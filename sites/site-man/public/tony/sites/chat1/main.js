const statusEl = document.getElementById('status');
const langSelect = document.getElementById('langSelect');
const listenBtn = document.getElementById('listenBtn');
const transcriptText = document.getElementById('transcriptText');
const transcriptMeta = document.getElementById('transcriptMeta');
const replyTextEl = document.getElementById('replyText');
const playReplyBtn = document.getElementById('playReplyBtn');

const SpeechRecognitionImpl = window.SpeechRecognition || window.webkitSpeechRecognition || null;
const DEFAULT_LANG = 'en-US';
const LANGUAGE_OPTIONS = [
  { code: 'en-US', label: 'English (US)' },
  { code: 'th-TH', label: 'ไทย (TH)' },
  { code: 'zh-CN', label: '中文 (CN)' },
  { code: 'ja-JP', label: '日本語' }
];

const state = {
  language: DEFAULT_LANG,
  transcript: '',
  reply: '',
  listening: false,
  speaking: false,
  recognition: null,
  lastUtterance: null,
  sessionId: null
};
let touchHoldActive = false;

const resolveApiBase = () => {
  if (window.CHABA_API_BASE) return window.CHABA_API_BASE;
  const meta = document.querySelector('meta[name="api-base"]');
  if (meta?.content) return meta.content;
  const origin = window.location.origin;
  if (origin.includes('localhost:4174')) return 'http://localhost:3001';
  return origin;
};

const API_BASE = resolveApiBase();
const VOICE_CHAT_URL = `${API_BASE}/voice-chat`;

const setStatus = (message, tone = 'ready') => {
  if (!statusEl) return;
  statusEl.textContent = message;
  statusEl.dataset.tone = tone;
};

const setTranscript = (text, meta = '—') => {
  transcriptText.textContent = text || 'No input yet.';
  transcriptMeta.textContent = meta;
  state.transcript = text || '';
};

const setReplyText = (text) => {
  state.reply = text || '';
  replyTextEl.textContent = text || 'No response yet.';
  playReplyBtn.disabled = !text;
};

const hydrateLanguageOptions = () => {
  langSelect.innerHTML = '';
  LANGUAGE_OPTIONS.forEach((entry) => {
    const option = document.createElement('option');
    option.value = entry.code;
    option.textContent = entry.label;
    if (entry.code === state.language) option.selected = true;
    langSelect.appendChild(option);
  });
};

const stopSpeaking = () => {
  window.speechSynthesis?.cancel();
  state.speaking = false;
};

const speak = (text) => {
  if (!text) return;
  stopSpeaking();
  const utterance = new SpeechSynthesisUtterance(text);
  const langPrefix = state.language.slice(0, 2).toLowerCase();
  if (langPrefix === 'th') utterance.lang = 'th-TH';
  else utterance.lang = 'en-US';
  utterance.rate = 1;
  state.lastUtterance = utterance;
  state.speaking = true;
  utterance.onend = () => {
    state.speaking = false;
  };
  window.speechSynthesis?.speak(utterance);
};

const attachSpeechRecognition = () => {
  if (!SpeechRecognitionImpl) {
    setStatus('Speech recognition unavailable on this browser', 'error');
    listenBtn.disabled = true;
    return;
  }
  const recognition = new SpeechRecognitionImpl();
  recognition.lang = state.language;
  recognition.interimResults = true;
  recognition.continuous = false;

  recognition.onstart = () => {
    state.listening = true;
    listenBtn.textContent = touchHoldActive ? 'Listening… release to stop' : 'Listening… tap to stop';
    setStatus('Listening…', 'listening');
  };

  recognition.onerror = (event) => {
    state.listening = false;
    listenBtn.textContent = '🎙️ Tap to speak';
    const blocked = event.error === 'not-allowed' || event.error === 'service-not-allowed';
    const message = blocked
      ? 'Mic blocked. Enable microphone permissions in Safari/Chrome settings.'
      : `Mic error: ${event.error || 'unknown'}`;
    setStatus(message, 'error');
  };

  recognition.onend = () => {
    state.listening = false;
    listenBtn.textContent = '🎙️ Tap to speak';
    setStatus('Ready', 'ready');
  };

  recognition.onresult = (event) => {
    let finalTranscript = '';
    let interimTranscript = '';
    for (let i = event.resultIndex; i < event.results.length; i++) {
      const result = event.results[i];
      if (result.isFinal) {
        finalTranscript += result[0].transcript;
      } else {
        interimTranscript += result[0].transcript;
      }
    }
    const combined = `${finalTranscript}${interimTranscript}`.trim();
    setTranscript(combined || '…', `${state.language} • ${new Date().toLocaleTimeString()}`);

    if (finalTranscript.trim()) {
      recognition.stop();
      handleTranscript(finalTranscript.trim());
    }
  };

  state.recognition = recognition;
};

const handleTranscript = async (text) => {
  setStatus('Contacting Glama…', 'listening');
  listenBtn.disabled = true;
  listenBtn.textContent = 'Contacting Glama…';
  try {
    const payload = {
      message: text,
      provider: 'glama',
      sessionName: 'chat1-mobile',
      sessionId: state.sessionId,
      accelerator: 'cpu'
    };
    const response = await fetch(VOICE_CHAT_URL, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(payload)
    });
    if (!response.ok) {
      const detail = await response.text();
      throw new Error(detail || `HTTP ${response.status}`);
    }
    const data = await response.json();
    state.sessionId = data?.session?.id || state.sessionId;
    const reply = data?.reply || '';
    if (!reply) {
      setStatus('Glama returned no reply', 'error');
      setReplyText('No response received.');
    } else {
      setReplyText(reply);
      speak(reply);
      setStatus('Reply ready', 'ready');
    }
  } catch (err) {
    console.error('Chat error', err);
    setStatus(`Error: ${err.message}`, 'error');
    setReplyText('Error while contacting Glama.');
  } finally {
    listenBtn.disabled = false;
    listenBtn.textContent = '🎙️ Tap to speak';
  }
};

const startListening = () => {
  if (!state.recognition || state.listening || listenBtn.disabled) return;
  state.recognition.lang = state.language;
  try {
    state.recognition.start();
  } catch (err) {
    const message = err?.message || err?.name || 'Mic unavailable';
    console.warn('recognition.start failed', err);
    const blocked = message.includes('not-allowed') || message.includes('service-not-allowed');
    setStatus(
      blocked ? 'Mic blocked. Enable microphone in Safari > Settings for this site.' : `Mic error: ${message}`,
      'error'
    );
  }
};

const stopListening = () => {
  if (!state.recognition || !state.listening) return;
  try {
    state.recognition.stop();
  } catch (err) {
    console.warn('recognition.stop failed', err);
  }
};

const toggleListening = () => {
  if (!state.recognition || listenBtn.disabled) return;
  if (state.listening) {
    stopListening();
  } else {
    startListening();
  }
};

const bindEvents = () => {
  listenBtn.addEventListener('pointerdown', (event) => {
    if (event.pointerType === 'touch') {
      touchHoldActive = true;
      startListening();
      event.preventDefault();
    }
  });

  listenBtn.addEventListener('pointerup', (event) => {
    if (event.pointerType === 'touch') {
      touchHoldActive = false;
      if (state.listening) {
        stopListening();
      }
      event.preventDefault();
    }
  });

  listenBtn.addEventListener('click', (event) => {
    // Mouse / trackpad taps toggle the mic; touch handled in pointer listeners above.
    if (event.pointerType === 'touch') return;
    event.preventDefault();
    toggleListening();
  });

  langSelect.addEventListener('change', (event) => {
    const value = event.target.value;
    state.language = value;
    if (state.recognition) {
      state.recognition.lang = value;
    }
  });

  playReplyBtn.addEventListener('click', () => {
    speak(state.reply);
  });
};

const init = () => {
  hydrateLanguageOptions();
  attachSpeechRecognition();
  bindEvents();
  setStatus('Ready', 'ready');
  setTranscript('', '—');
  setReplyText('');
};

init();
