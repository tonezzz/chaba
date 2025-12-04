const attachmentIcon = (type = '') => {
  if (type?.startsWith('image/')) return '🖼️';
  if (type?.startsWith('video/')) return '🎞️';
  if (type?.startsWith('audio/')) return '🎧';
  if (type?.includes('pdf')) return '📄';
  if (type?.includes('zip')) return '🗜️';
  return '📎';
};

const renderAttachments = () => {
  if (!attachmentsList) return;
  attachmentsList.innerHTML = '';
  pendingAttachments.forEach((file, index) => {
    const chip = document.createElement('span');
    chip.className = 'attachment-chip';
    chip.dataset.status = file.status || 'ready';
    const label = document.createElement('span');
    label.textContent = `${attachmentIcon(file.type)} ${file.name}`;
    chip.appendChild(label);
    if (file.status === 'uploading') {
      const status = document.createElement('span');
      status.className = 'attachment-chip__status';
      status.textContent = 'Uploading…';
      chip.appendChild(status);
    } else if (file.status === 'error') {
      const status = document.createElement('span');
      status.className = 'attachment-chip__status attachment-chip__status--error';
      status.textContent = 'Failed';
      chip.appendChild(status);
    }
    const removeBtn = document.createElement('button');
    removeBtn.type = 'button';
    removeBtn.textContent = '✕';
    removeBtn.addEventListener('click', () => {
      pendingAttachments.splice(index, 1);
      renderAttachments();
    });
    chip.appendChild(removeBtn);
    attachmentsList.appendChild(chip);
  });
};

const fileToBase64 = (file) =>
  new Promise((resolve, reject) => {
    const reader = new FileReader();
    reader.onload = () => resolve(reader.result);
    reader.onerror = reject;
    reader.readAsDataURL(file);
  });

const uploadAttachment = async (file) => {
  const dataUrl = await fileToBase64(file);
  const base64 = typeof dataUrl === 'string' && dataUrl.includes(',') ? dataUrl.split(',')[1] : dataUrl;
  const res = await fetch('/api/attachments', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ name: file.name, type: file.type || 'application/octet-stream', data: base64 })
  });
  if (!res.ok) {
    const detail = await res.text();
    throw new Error(detail || 'attachment_upload_failed');
  }
  const data = await res.json();
  return data?.attachment;
};

const handleFilesSelected = async (files) => {
  for (const file of files) {
    const entry = {
      name: file.name,
      type: file.type || 'application/octet-stream',
      status: 'uploading'
    };
    pendingAttachments.push(entry);
    renderAttachments();
    try {
      const uploaded = await uploadAttachment(file);
      Object.assign(entry, uploaded, { status: 'ready' });
      addActivity(`${file.name} uploaded`, 'success');
    } catch (error) {
      entry.status = 'error';
      entry.error = error.message || 'Upload failed';
      addActivity(`Upload failed for ${file.name}`, 'error');
    }
    renderAttachments();
  }
};

const initAttachmentControls = () => {
  if (!attachButton || !attachmentInput) {
    return;
  }
  attachButton.addEventListener('click', () => attachmentInput.click());
  attachmentInput.addEventListener('change', (event) => {
    const files = Array.from(event.target.files || []);
    if (files.length) {
      handleFilesSelected(files);
    }
    attachmentInput.value = '';
  });
};
const $ = (selector) => document.querySelector(selector);
const chatEl = $('#chat');
const activityEl = $('#activity');
const statusEl = $('#status');
const agentPillsEl = $('#agentPills');
const crewSummaryEl = $('#crewSummary');
const attachButton = $('#attachButton');
const attachmentInput = $('#attachmentInput');
const attachmentsList = $('#attachmentsList');
const messageInput = $('#messageInput');
const historyInput = $('#historyLimit');
const form = $('#messageForm');
const autoSendToggle = $('#autoSendToggle');
const autoRetryToggle = $('#autoRetryToggle');
const sendButton = form ? form.querySelector('button[type="submit"]') : null;

const AUTO_SEND_KEY = 'node1_auto_send_enabled';
const AUTO_RETRY_KEY = 'node1_auto_retry_enabled';

const AGENT_INTROS = {
  orchestrator: {
    en: 'Surf Orchestrator: I coordinate the whole crew and turn goals into multi-agent plans.',
    th: 'Surf Orchestrator: ฉันวางแผนและประสานงานทีมเอเจนต์ทั้งหมดให้ไปถึงเป้าหมายของคุณ'
  },
  navigator: {
    en: 'Navigator: I guide deployments and surface scripts, health checks, and control panels.',
    th: 'Navigator: ฉันช่วยนำทางการดีพลอย และชี้สคริปต์กับดัชบอร์ดที่จำเป็น'
  },
  researcher: {
    en: 'Researcher: I dig through docs and code to bring you facts and references.',
    th: 'Researcher: ฉันค้นหาข้อมูลจากเอกสารและโค้ดเพื่อเสริมคำตอบให้แม่นยำ'
  },
  critic: {
    en: 'Critic: I review every plan for risk, policy alignment, and rollback readiness.',
    th: 'Critic: ฉันตรวจทุกแผนเพื่อหาความเสี่ยงและยืนยันว่าพร้อมย้อนกลับได้'
  }
};

let availableAgents = [];
let currentSession = null;
let currentStream = null;
const streamingMessages = new Map();
let lastPrompt = null;
let lastTargets = [];
let retryTimer = null;
const defaultButtonLabel = sendButton ? sendButton.textContent : 'Send & run agents';
let introsVisible = false;
const selectedAgents = new Set();
const agentStatuses = new Map();
let pendingAttachments = [];

const renderStatus = (text, ok = false) => {
  statusEl.textContent = text;
  statusEl.classList.toggle('ok', ok);
};

const renderAgentIntros = () => {
  if (!chatEl || chatEl.querySelector('.message') || introsVisible) {
    return;
  }
  chatEl.innerHTML = '';
  availableAgents.forEach((agent) => {
    const intro = AGENT_INTROS[agent.id];
    if (!intro) {
      return;
    }
    const card = document.createElement('div');
    card.className = 'intro-card';
    const title = document.createElement('strong');
    title.textContent = `${agent.name} (${agent.id})`;
    const en = document.createElement('p');
    en.textContent = intro.en;
    const th = document.createElement('p');
    th.textContent = intro.th;
    card.append(title, en, th);
    chatEl.appendChild(card);
  });
  introsVisible = true;
};

const clearAgentIntros = () => {
  if (!introsVisible) {
    return;
  }
  const cards = chatEl.querySelectorAll('.intro-card');
  cards.forEach((card) => card.remove());
  introsVisible = false;
};

const addActivity = (text, tone = 'info') => {
  if (!activityEl) {
    return;
  }
  const entry = document.createElement('div');
  entry.className = `activity-entry activity-entry--${tone}`;
  entry.textContent = text;
  activityEl.appendChild(entry);
  activityEl.scrollTop = activityEl.scrollHeight;
};

const setInteractionState = (busy, statusText) => {
  if (sendButton) {
    sendButton.disabled = busy;
    sendButton.textContent = busy ? 'Working…' : defaultButtonLabel;
  }
  if (messageInput) {
    messageInput.disabled = busy;
  }
  if (typeof statusText === 'string') {
    renderStatus(statusText, !busy);
  }
};

const ensureStreamingRecord = (agentId) => {
  clearAgentIntros();
  if (streamingMessages.has(agentId)) {
    return streamingMessages.get(agentId);
  }
  const wrapper = document.createElement('div');
  wrapper.className = 'message assistant pending';
  const header = document.createElement('strong');
  header.textContent = agentId;
  const body = document.createElement('p');
  body.textContent = '';
  wrapper.append(header, body);
  chatEl.appendChild(wrapper);
  streamingMessages.set(agentId, { wrapper, body, content: '' });
  return streamingMessages.get(agentId);
};

const appendStreamingDelta = (agentId, delta) => {
  if (!delta) {
    return;
  }
  const record = ensureStreamingRecord(agentId);
  record.content += delta;
  record.body.textContent = record.content;
  chatEl.scrollTop = chatEl.scrollHeight;
};

const finalizeStreamingMessage = (agentId, message) => {
  const record = streamingMessages.get(agentId);
  if (!record) {
    return;
  }
  const finalContent = message?.content || record.content;
  record.content = finalContent;
  record.body.textContent = finalContent;
  record.wrapper.classList.remove('pending');
};

const resetStreamingState = () => {
  if (currentStream) {
    currentStream.close();
    currentStream = null;
  }
  streamingMessages.clear();
};

const resetAgentStatuses = () => {
  agentStatuses.clear();
  updatePillStates();
};

const setAgentStatus = (agentId, status) => {
  if (!agentId) {
    return;
  }
  if (status === 'queued') {
    agentStatuses.set(agentId, 'queued');
  } else if (status === 'running') {
    agentStatuses.set(agentId, 'running');
  } else if (status === 'done') {
    agentStatuses.set(agentId, 'done');
  } else if (status === 'error') {
    agentStatuses.set(agentId, 'error');
  } else {
    agentStatuses.delete(agentId);
  }
  updatePillStates();
};

const isAutoSendEnabled = () => {
  return autoSendToggle ? Boolean(autoSendToggle.checked) : true;
};

const initAutoSend = () => {
  if (!autoSendToggle) {
    return;
  }
  const stored = localStorage.getItem(AUTO_SEND_KEY);
  const enabled = stored === null ? true : stored === 'true';
  autoSendToggle.checked = enabled;
  autoSendToggle.addEventListener('change', () => {
    localStorage.setItem(AUTO_SEND_KEY, autoSendToggle.checked ? 'true' : 'false');
  });
};

const addMessage = ({ role, content, agentId }) => {
  clearAgentIntros();
  const wrapper = document.createElement('div');
  wrapper.className = ['message', role === 'assistant' ? 'assistant' : 'user'].join(' ');
  const header = document.createElement('strong');
  header.textContent = role === 'assistant' ? (agentId ? agentId : 'assistant') : 'you';
  const body = document.createElement('p');
  body.textContent = content;
  wrapper.append(header, body);
  if (role === 'user' && arguments[0]?.attachments?.length) {
    const list = document.createElement('div');
    list.className = 'message-attachments';
    arguments[0].attachments.forEach((file) => {
      const chip = document.createElement('span');
      chip.className = 'attachment-chip';
      chip.textContent = `${file.icon} ${file.name}`;
      list.appendChild(chip);
    });
    wrapper.appendChild(list);
  }
  if (role === 'user') {
    const actions = document.createElement('div');
    actions.className = 'message-actions';
    const resendBtn = document.createElement('button');
    resendBtn.type = 'button';
    resendBtn.className = 'resend-btn';
    resendBtn.textContent = 'Resend';
    resendBtn.addEventListener('click', () => resendMessage(content));
    actions.appendChild(resendBtn);
    wrapper.appendChild(actions);
  }
  chatEl.appendChild(wrapper);
  chatEl.scrollTop = chatEl.scrollHeight;
};

const resendMessage = (content) => {
  if (!content || !form || sendButton?.disabled) {
    return;
  }
  messageInput.value = content;
  addActivity('Resending previous prompt…', 'info');
  form.requestSubmit();
};

const loadAgents = async () => {
  const res = await fetch('/api/agents');
  if (!res.ok) {
    throw new Error('agents_api_failed');
  }
  const data = await res.json();
  availableAgents = data.agents || [];
  renderStatus(`Loaded ${availableAgents.length} agents`, true);
  renderAgentPills();
  applyDefaultSelection();
  renderCrewSummary();
  renderAgentIntros();
};

const applyDefaultSelection = () => {
  selectedAgents.clear();
  selectedAgents.add('orchestrator');
  updatePillStates();
};

const renderAgentPills = () => {
  if (!agentPillsEl) {
    return;
  }
  agentPillsEl.innerHTML = '';
  availableAgents.forEach((agent) => {
    const pill = document.createElement('button');
    pill.type = 'button';
    pill.className = 'agent-pill';
    pill.dataset.agentId = agent.id;
    pill.innerHTML = `<span class="agent-pill__name">${agent.name}</span><span class="agent-pill__id">${agent.id}</span>`;
    pill.addEventListener('click', () => toggleAgentSelection(agent.id));
    agentPillsEl.appendChild(pill);
  });
  updatePillStates();
};

const toggleAgentSelection = (agentId) => {
  if (!agentId) {
    return;
  }
  if (agentId === 'orchestrator') {
    selectedAgents.add(agentId);
  } else if (selectedAgents.has(agentId)) {
    selectedAgents.delete(agentId);
  } else {
    selectedAgents.add(agentId);
  }
  if (!selectedAgents.size) {
    selectedAgents.add('orchestrator');
  }
  updatePillStates();
  renderCrewSummary();
};

const updatePillStates = () => {
  if (!agentPillsEl) {
    return;
  }
  const pills = agentPillsEl.querySelectorAll('.agent-pill');
  pills.forEach((pill) => {
    const id = pill.dataset.agentId;
    if (selectedAgents.has(id)) {
      pill.classList.add('agent-pill--active');
    } else {
      pill.classList.remove('agent-pill--active');
    }
    pill.classList.remove('agent-pill--running', 'agent-pill--done', 'agent-pill--error');
    const status = agentStatuses.get(id);
    if (status) {
      pill.classList.add(`agent-pill--${status}`);
    }
  });
};

const renderCrewSummary = () => {
  if (!crewSummaryEl) {
    return;
  }
  if (!selectedAgents.size) {
    crewSummaryEl.textContent = 'Select at least one agent to begin.';
    return;
  }
  const pieces = Array.from(selectedAgents).map((id) => {
    const agent = availableAgents.find((item) => item.id === id);
    return agent ? agent.name : id;
  });
  crewSummaryEl.textContent = `Current crew: ${pieces.join(' · ')}`;
};

const ensureSession = async (forceNew = false) => {
  if (forceNew) {
    currentSession = null;
  }
  if (currentSession) {
    return currentSession;
  }
  if (!selectedAgents.size) {
    selectedAgents.add('orchestrator');
  }
  if (!selectedAgents.has('orchestrator')) {
    selectedAgents.add('orchestrator');
  }
  const agentIds = Array.from(selectedAgents);
  if (!agentIds.length) {
    throw new Error('select_at_least_one_agent');
  }
  const res = await fetch('/api/sessions', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ agents: agentIds })
  });
  if (!res.ok) {
    const detail = await res.text();
    throw new Error(detail || 'session_create_failed');
  }
  const data = await res.json();
  currentSession = data.session;
  return currentSession;
};

const postUserMessage = async (sessionId, agentTargets, content) => {
  const res = await fetch(`/api/sessions/${sessionId}/messages`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ role: 'user', content, agentTargets })
  });
  if (!res.ok) {
    const detail = await res.text();
    throw new Error(detail || 'message_post_failed');
  }
  return res.json();
};

const beginStreaming = (sessionId, agentTargets) => {
  if (!sessionId || !agentTargets.length) {
    return;
  }
  resetStreamingState();
  resetAgentStatuses();
  const params = new URLSearchParams();
  params.set('agents', agentTargets.join(','));
  const source = new EventSource(`/api/sessions/${sessionId}/stream?${params.toString()}`);
  currentStream = source;
  setAgentStatus('orchestrator', 'running');
  addActivity('Orchestrator is planning...', 'info');
  agentTargets.forEach((agentId) => {
    if (agentId !== 'orchestrator') {
      setAgentStatus(agentId, 'queued');
    }
  });

  source.addEventListener('token', (event) => {
    try {
      const payload = JSON.parse(event.data || '{}');
      if (payload?.agentId && payload?.delta) {
        appendStreamingDelta(payload.agentId, payload.delta);
        if (payload.agentId !== 'orchestrator') {
          setAgentStatus(payload.agentId, 'running');
        }
      }
    } catch {}
  });

  source.addEventListener('complete', (event) => {
    try {
      const payload = JSON.parse(event.data || '{}');
      if (payload?.agentId) {
        setAgentStatus(payload.agentId, 'done');
        if (payload.agentId === 'orchestrator') {
          addActivity('Orchestrator delegation ready.', 'success');
        } else {
          addActivity(`${payload.agentId} responded.`, 'success');
        }
        finalizeStreamingMessage(payload.agentId, payload.message);
      }
    } catch {}
  });

  source.addEventListener('stream-error', (event) => {
    try {
      const payload = JSON.parse(event.data || '{}');
      if (payload?.agentId) {
        setAgentStatus(payload.agentId, 'error');
      }
      handleStreamFailure(payload);
    } catch (error) {
      handleStreamFailure({ error: 'stream_error_parse_failed' });
    }
  });

  source.addEventListener('error', () => {
    handleStreamFailure({ error: 'connection_error', message: 'Stream connection lost.' });
  });

  source.addEventListener('done', () => {
    if (currentStream) {
      currentStream.close();
      currentStream = null;
    }
    setInteractionState(false, 'Agents responded');
  });
};

const handleSubmit = async (event) => {
  event.preventDefault();
  const content = (messageInput.value || '').trim();
  if (!content) {
    return;
  }
  const targetAgents = Array.from(selectedAgents);
  if (!targetAgents.length) {
    renderStatus('Select at least one agent', false);
    return;
  }
  renderCrewSummary();

  addMessage({ role: 'user', content, attachments: [...pendingAttachments] });
  messageInput.value = '';
  pendingAttachments = [];
  renderAttachments();
  setInteractionState(true, 'Dispatching orchestrator plan…');
  lastPrompt = content;
  lastTargets = [...targetAgents];
  try {
    const session = await ensureSession();
    await postUserMessage(session.id, targetAgents, content);
    beginStreaming(session.id, targetAgents);
  } catch (error) {
    console.error('Panel error', error);
    setInteractionState(false, 'Error: ' + (error.message || error));
  }
};

form.addEventListener('submit', handleSubmit);

messageInput.addEventListener('keydown', (event) => {
  if (event.key === 'Enter' && !event.shiftKey && isAutoSendEnabled()) {
    event.preventDefault();
    form.requestSubmit();
  }
});

const handleStreamFailure = (payload = {}) => {
  if (currentStream) {
    currentStream.close();
    currentStream = null;
  }
  streamingMessages.clear();
  currentSession = null;
  const detail = payload.message || payload.error || 'Stream failed. Please try again.';
  setInteractionState(false, detail);
  addActivity(detail, 'error');
  if (isAutoRetryEnabled()) {
    scheduleAutoRetry();
  }
};

const scheduleAutoRetry = () => {
  if (!lastPrompt || !lastTargets.length) {
    return;
  }
  if (retryTimer) {
    clearTimeout(retryTimer);
  }
  setInteractionState(true, 'Retrying orchestrator plan…');
  retryTimer = setTimeout(async () => {
    retryTimer = null;
    try {
      const session = await ensureSession(true);
      await postUserMessage(session.id, lastTargets, lastPrompt);
      beginStreaming(session.id, lastTargets);
    } catch (error) {
      console.error('Auto-retry failed', error);
      setInteractionState(false, 'Auto-retry failed: ' + (error.message || error));
    }
  }, 1500);
};

const isAutoRetryEnabled = () => {
  return autoRetryToggle ? Boolean(autoRetryToggle.checked) : true;
};

const initAutoRetry = () => {
  if (!autoRetryToggle) {
    return;
  }
  const stored = localStorage.getItem(AUTO_RETRY_KEY);
  const enabled = stored === null ? true : stored === 'true';
  autoRetryToggle.checked = enabled;
  autoRetryToggle.addEventListener('change', () => {
    localStorage.setItem(AUTO_RETRY_KEY, autoRetryToggle.checked ? 'true' : 'false');
  });
};

window.addEventListener('load', async () => {
  try {
    initAutoSend();
    initAutoRetry();
    await loadAgents();
  } catch (error) {
    console.error('Failed to init panel', error);
    renderStatus('Failed to load agents', false);
  }
});
