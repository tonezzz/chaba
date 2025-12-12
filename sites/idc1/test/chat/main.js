const API_BASE = '/test/chat/api';
const ENTER_PREF_KEY = 'glama_enter_to_send';
const LANGUAGE_PREF_KEY = 'glama_language_preference';

const statusEl = document.getElementById('status');
const chatLogEl = document.getElementById('chat-log');
const chatForm = document.getElementById('chat-form');
const chatInput = document.getElementById('chat-input');
const sendButton = document.getElementById('send-button');
const enterToggle = document.getElementById('enter-toggle');
const temperatureInput = document.getElementById('temperature');
const languageSelect = document.getElementById('language-select');
const template = document.getElementById('message-template');

const LANGUAGE_OPTIONS = [
  { value: 'auto', label: 'Auto detect' },
  { value: 'en', label: 'English' },
  { value: 'th', label: 'ไทย (Thai)' },
  { value: 'es', label: 'Español' },
  { value: 'ja', label: '日本語' },
  { value: 'zh', label: '中文' }
];

const SPEECH_LOCALE_MAP = {
  en: 'en-US',
  th: 'th-TH',
  es: 'es-ES',
  ja: 'ja-JP',
  zh: 'zh-CN'
};

const history = [];
const supportsSpeechSynthesis = typeof window !== 'undefined' && 'speechSynthesis' in window;
let selectedLanguage = (() => {
  try {
    const stored = window.localStorage.getItem(LANGUAGE_PREF_KEY);
    if (stored && LANGUAGE_OPTIONS.some((option) => option.value === stored)) {
      return stored;
    }
  } catch {}
  return 'auto';
})();
let activeUtterance = null;

const setStatus = (text, ok = false) => {
  statusEl.textContent = text;
  statusEl.classList.toggle('ok', ok);
};

const formatTime = (date = new Date()) =>
  date.toLocaleTimeString(undefined, { hour: '2-digit', minute: '2-digit' });

const getLanguageLabel = (value) => {
  if (!value) return '';
  const match = LANGUAGE_OPTIONS.find((option) => option.value === value);
  return match ? match.label : value.toUpperCase();
};

const resolveSpeechLocale = (code) => {
  if (!code || code === 'auto') {
    return 'en-US';
  }
  if (code.includes('-')) {
    return code;
  }
  return SPEECH_LOCALE_MAP[code] || 'en-US';
};

const appendMessage = ({ role, content, pending = false, languageCode = null, canSpeak = false }) => {
  const clone = template.content.cloneNode(true);
  const article = clone.querySelector('.message');
  const langLabelEl = clone.querySelector('.message-lang');
  const speakerBtn = clone.querySelector('.message-speaker');
  article.classList.add(role);
  if (pending) article.classList.add('pending');

  clone.querySelector('.message-role').textContent = role === 'user' ? 'You' : 'Glama';
  clone.querySelector('.message-time').textContent = formatTime();
  clone.querySelector('.message-body').textContent = content;

  const langToShow = languageCode || (selectedLanguage !== 'auto' ? selectedLanguage : null);
  if (langLabelEl) {
    if (langToShow) {
      langLabelEl.textContent = getLanguageLabel(langToShow);
      langLabelEl.hidden = false;
    } else {
      langLabelEl.hidden = true;
    }
  }

  if (speakerBtn) {
    const speechText = typeof content === 'string' ? content.trim() : '';
    const enableSpeaker =
      !pending && role === 'assistant' && canSpeak && speechText && supportsSpeechSynthesis;
    if (enableSpeaker) {
      speakerBtn.hidden = false;
      speakerBtn.dataset.speakText = speechText;
      speakerBtn.dataset.speakLang = resolveSpeechLocale(languageCode || selectedLanguage);
    } else {
      speakerBtn.hidden = true;
      speakerBtn.removeAttribute('data-speak-text');
      speakerBtn.removeAttribute('data-speak-lang');
      speakerBtn.classList.remove('is-speaking');
    }
  }

  chatLogEl.appendChild(clone);
  chatLogEl.scrollTop = chatLogEl.scrollHeight;
  return chatLogEl.lastElementChild;
};

const refreshStatus = async () => {
  try {
    const res = await fetch(`${API_BASE}/health`);
    if (!res.ok) throw new Error(res.statusText);
    const data = await res.json();
    setStatus(data.status === 'ok' ? `Ready · ${data.model}` : 'Glama not configured', data.status === 'ok');
  } catch (error) {
    console.error('[glama-ui] status failed', error);
    setStatus('Status unavailable');
  }
};

const sendMessage = async (message) => {
  const payload = {
    message,
    history,
    temperature: Number(temperatureInput.value),
    language: selectedLanguage
  };

  const placeholder = appendMessage({
    role: 'assistant',
    content: '…thinking',
    pending: true,
    languageCode: selectedLanguage
  });
  history.push({ role: 'user', content: message, language: selectedLanguage });

  try {
    const res = await fetch(`${API_BASE}/chat`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(payload)
    });
    if (!res.ok) {
      throw new Error((await res.json())?.error || 'glama_chat_failed');
    }
    const data = await res.json();
    placeholder.remove();
    const replyLanguage = data.language || selectedLanguage;
    appendMessage({
      role: 'assistant',
      content: data.reply,
      languageCode: replyLanguage,
      canSpeak: true
    });
    history.push({ role: 'assistant', content: data.reply, language: replyLanguage });
  } catch (error) {
    console.error('[glama-ui] send failed', error);
    placeholder.remove();
    appendMessage({ role: 'assistant', content: `Error: ${error.message || 'Failed to reach backend'}` });
  }
};

chatForm.addEventListener('submit', (event) => {
  event.preventDefault();
  const message = chatInput.value.trim();
  if (!message) return;
  appendMessage({ role: 'user', content: message, languageCode: selectedLanguage });
  chatInput.value = '';
  sendMessage(message);
});

chatInput.addEventListener('keydown', (event) => {
  if (event.key === 'Enter' && !event.shiftKey && enterToggle.checked) {
    event.preventDefault();
    chatForm.requestSubmit();
  }
});

enterToggle.addEventListener('change', () => {
  localStorage.setItem(ENTER_PREF_KEY, enterToggle.checked ? '1' : '0');
});

const initEnterPreference = () => {
  const stored = localStorage.getItem(ENTER_PREF_KEY);
  enterToggle.checked = stored !== '0';
};

const hydrateLanguageSelect = () => {
  if (!languageSelect) return;
  languageSelect.innerHTML = '';
  LANGUAGE_OPTIONS.forEach((option) => {
    const opt = document.createElement('option');
    opt.value = option.value;
    opt.textContent = option.label;
    if (option.value === selectedLanguage) {
      opt.selected = true;
    }
    languageSelect.appendChild(opt);
  });
};

const bindLanguageSelector = () => {
  if (!languageSelect) return;
  languageSelect.addEventListener('change', (event) => {
    selectedLanguage = event.target.value;
    try {
      localStorage.setItem(LANGUAGE_PREF_KEY, selectedLanguage);
    } catch {}
  });
};

const stopSpeaking = () => {
  if (!supportsSpeechSynthesis) return;
  window.speechSynthesis.cancel();
  const activeButton = chatLogEl.querySelector('.message-speaker.is-speaking');
  if (activeButton) {
    activeButton.classList.remove('is-speaking');
  }
  activeUtterance = null;
};

const speakText = (text, locale, buttonEl) => {
  if (!supportsSpeechSynthesis || !text) return;
  stopSpeaking();
  activeUtterance = new SpeechSynthesisUtterance(text);
  activeUtterance.lang = locale || 'en-US';
  activeUtterance.rate = 1;
  if (buttonEl) {
    buttonEl.classList.add('is-speaking');
  }
  activeUtterance.onend = activeUtterance.onerror = () => {
    if (buttonEl) {
      buttonEl.classList.remove('is-speaking');
    }
    activeUtterance = null;
  };
  window.speechSynthesis.speak(activeUtterance);
};

chatLogEl.addEventListener('click', (event) => {
  const speakerBtn = event.target.closest('.message-speaker');
  if (!speakerBtn || speakerBtn.hidden) return;
  const text = speakerBtn.dataset.speakText;
  if (!text) return;
  const lang = speakerBtn.dataset.speakLang || resolveSpeechLocale(selectedLanguage);
  speakText(text, lang, speakerBtn);
});

const init = () => {
  initEnterPreference();
  hydrateLanguageSelect();
  bindLanguageSelector();
  refreshStatus();
  appendMessage({
    role: 'assistant',
    content: 'Welcome! This panel talks directly to Glama via the new a1.idc1 backend. Ask away when ready.'
  });
};

init();
