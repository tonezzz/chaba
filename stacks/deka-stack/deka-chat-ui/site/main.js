const API_BASE = '/api';
const ENTER_PREF_KEY = 'deka_enter_to_send';

const statusEl = document.getElementById('status');
const chatLogEl = document.getElementById('chat-log');
const chatForm = document.getElementById('chat-form');
const chatInput = document.getElementById('chat-input');
const enterToggle = document.getElementById('enter-toggle');
const template = document.getElementById('message-template');

const history = [];

const setStatus = (text, ok = false) => {
  statusEl.textContent = text;
  statusEl.classList.toggle('ok', ok);
};

const formatTime = (date = new Date()) =>
  date.toLocaleTimeString(undefined, { hour: '2-digit', minute: '2-digit' });

const appendMessage = ({ role, content, pending = false, meta = null }) => {
  const clone = template.content.cloneNode(true);
  const article = clone.querySelector('.message');
  const metaEl = clone.querySelector('.message-meta');

  article.classList.add(role);
  if (pending) article.classList.add('pending');

  clone.querySelector('.message-role').textContent = role === 'user' ? 'You' : 'Assistant';
  clone.querySelector('.message-time').textContent = formatTime();

  const bodyEl = clone.querySelector('.message-body');
  bodyEl.textContent = typeof content === 'string' ? content : JSON.stringify(content, null, 2);

  if (metaEl) {
    if (meta) {
      metaEl.textContent = meta;
      metaEl.hidden = false;
    } else {
      metaEl.hidden = true;
    }
  }

  chatLogEl.appendChild(clone);
  chatLogEl.scrollTop = chatLogEl.scrollHeight;
  return chatLogEl.lastElementChild;
};

const refreshStatus = async () => {
  try {
    const res = await fetch(`${API_BASE}/stats`);
    if (!res.ok) throw new Error(res.statusText);
    const data = await res.json();
    const ok = !!data.ok;
    const discovered = data?.body?.total_discovered;
    const label = typeof discovered === 'number' ? `Ready · ${discovered} docs` : 'Ready';
    setStatus(label, ok);
  } catch {
    setStatus('Status unavailable');
  }
};

const initEnterPreference = () => {
  const stored = localStorage.getItem(ENTER_PREF_KEY);
  enterToggle.checked = stored !== '0';
};

enterToggle.addEventListener('change', () => {
  localStorage.setItem(ENTER_PREF_KEY, enterToggle.checked ? '1' : '0');
});

chatInput.addEventListener('keydown', (event) => {
  if (event.key === 'Enter' && !event.shiftKey && enterToggle.checked) {
    event.preventDefault();
    chatForm.requestSubmit();
  }
});

const sendMessage = async (message) => {
  const placeholder = appendMessage({ role: 'assistant', content: '…thinking', pending: true });
  history.push({ role: 'user', content: message });

  try {
    const res = await fetch(`${API_BASE}/chat`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ message, history })
    });

    if (!res.ok) {
      let detail = 'deka_chat_failed';
      try {
        const body = await res.json();
        detail = body?.error || body?.detail || detail;
      } catch {}
      throw new Error(detail);
    }

    const data = await res.json();
    placeholder.remove();
    appendMessage({
      role: 'assistant',
      content: data.reply,
      meta: data.mode ? `mode: ${data.mode}` : null
    });
    history.push({ role: 'assistant', content: data.reply, mode: data.mode });
  } catch (error) {
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

const init = () => {
  initEnterPreference();
  refreshStatus();
  appendMessage({
    role: 'assistant',
    content:
      'Ask: "ปีไหนมีคำพิพากษาเกี่ยวกับ..."\nCommands:\n- /deka stats\n- /stats\n\nIf evidence is available, the answer will cite DEKA sources.'
  });
};

init();
