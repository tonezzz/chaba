const API_BASE = '/test/chat/api';
const ENTER_PREF_KEY = 'glama_enter_to_send';

const statusEl = document.getElementById('status');
const chatLogEl = document.getElementById('chat-log');
const chatForm = document.getElementById('chat-form');
const chatInput = document.getElementById('chat-input');
const sendButton = document.getElementById('send-button');
const enterToggle = document.getElementById('enter-toggle');
const temperatureInput = document.getElementById('temperature');
const template = document.getElementById('message-template');

const history = [];

const setStatus = (text, ok = false) => {
  statusEl.textContent = text;
  statusEl.classList.toggle('ok', ok);
};

const formatTime = (date = new Date()) =>
  date.toLocaleTimeString(undefined, { hour: '2-digit', minute: '2-digit' });

const appendMessage = ({ role, content, pending = false }) => {
  const clone = template.content.cloneNode(true);
  const article = clone.querySelector('.message');
  article.classList.add(role);
  if (pending) article.classList.add('pending');

  clone.querySelector('.message-role').textContent = role === 'user' ? 'You' : 'Glama';
  clone.querySelector('.message-time').textContent = formatTime();
  clone.querySelector('.message-body').textContent = content;

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
    temperature: Number(temperatureInput.value)
  };

  const placeholder = appendMessage({ role: 'assistant', content: '…thinking', pending: true });
  history.push({ role: 'user', content: message });

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
    appendMessage({ role: 'assistant', content: data.reply });
    history.push({ role: 'assistant', content: data.reply });
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
  appendMessage({ role: 'user', content: message });
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

const init = () => {
  initEnterPreference();
  refreshStatus();
  appendMessage({
    role: 'assistant',
    content: 'Welcome! This panel talks directly to Glama via the new a1.idc1 backend. Ask away when ready.'
  });
};

init();
