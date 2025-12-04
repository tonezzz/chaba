const sanitizeUserId = (value = '') => {
  const trimmed = (value || '').toString().trim().toLowerCase();
  const cleaned = trimmed.replace(/[^a-z0-9-_]/g, '');
  return cleaned || 'default';
};

const formatUserLabel = (value = '') =>
  value
    .split(/[-_]/)
    .filter(Boolean)
    .map((segment) => segment.charAt(0).toUpperCase() + segment.slice(1))
    .join(' ');

const resolveUserId = () => {
  try {
    const params = new URLSearchParams(window.location.search);
    const queryUser = params.get('user');
    if (queryUser) {
      return sanitizeUserId(queryUser);
    }
    const trimmedPath = window.location.pathname.replace(/\/+$/, '');
    const match = trimmedPath.match(/^\/chat(?:\/([^/]+))?/i);
    if (match && match[1]) {
      return sanitizeUserId(match[1]);
    }
  } catch {}
  return 'default';
};

const userId = resolveUserId();
const apiBase = `/api/users/${encodeURIComponent(userId)}`;
const userLabel = userId === 'default' ? 'Default workspace' : `${formatUserLabel(userId)} workspace`;

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
  const res = await fetch(`${apiBase}/attachments`, {
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
const userBadgeEl = $('#userBadge');
const sessionsListEl = $('#sessionsList');
const newSessionButton = $('#newSessionButton');
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
let lastAttachments = [];
let sessionSummaries = [];

const renderStatus = (text, ok = false) => {
  statusEl.textContent = text;
  statusEl.classList.toggle('ok', ok);
};

const initUserBadge = () => {
  if (!userBadgeEl) {
    return;
  }
  userBadgeEl.textContent = `👤 ${userLabel}`;
  if (userId !== 'default') {
    document.title = `${formatUserLabel(userId)} · Multi-agent panel`;
  }
};

const formatTimestamp = (iso) => {
  if (!iso) {
    return 'unknown';
  }
  try {
    return new Date(iso).toLocaleString(undefined, {
      month: 'short',
      day: 'numeric',
      hour: '2-digit',
      minute: '2-digit'
    });
  } catch (error) {
    return iso;
  }
};

const describeSessionAgents = (agents = []) => {
  const filtered = agents.filter((id) => id && id !== 'orchestrator');
  if (!filtered.length) {
    return 'Orchestrator only';
  }
  return filtered.join(', ');
};

const activeSessionId = () => currentSession?.id || null;

const handlePinToggle = async (sessionId, pinned) => {
  try {
    const res = await fetch(`${apiBase}/sessions/${sessionId}`, {
      method: 'PATCH',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ pinned })
    });
    if (!res.ok) {
      throw new Error('pin_failed');
    }
    await loadSessions();
  } catch (error) {
    console.error('Pin toggle failed', error);
    addActivity('Failed to update pin state.', 'error');
  }
};

const handleRename = async (sessionId, title) => {
  try {
    const res = await fetch(`${apiBase}/sessions/${sessionId}`, {
      method: 'PATCH',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ title })
    });
    if (!res.ok) {
      throw new Error('rename_failed');
    }
    await loadSessions();
  } catch (error) {
    console.error('Rename failed', error);
    addActivity('Failed to rename session.', 'error');
  }
};

const handleAutoTitle = async (sessionId) => {
  setInteractionState(true, 'Summarizing title…');
  try {
    const res = await fetch(`${apiBase}/sessions/${sessionId}/auto-title`, { method: 'POST' });
    if (!res.ok) {
      throw new Error('auto_title_failed');
    }
    await loadSessions();
    setInteractionState(false, 'Title updated');
  } catch (error) {
    console.error('Auto-title failed', error);
    setInteractionState(false, 'Auto-title failed');
  }
};

const promptRename = (sessionId, currentTitle) => {
  const nextTitle = window.prompt('Rename session', currentTitle || '');
  if (nextTitle === null) {
    return;
  }
  const trimmed = nextTitle.trim();
  handleRename(sessionId, trimmed || null);
};

const handleDeleteSession = async (sessionId) => {
  if (!sessionId) {
    return;
  }
  const confirmed = window.confirm('Archive and delete this session? A summary will be saved for reference.');
  if (!confirmed) {
    return;
  }
  setInteractionState(true, 'Archiving session…');
  try {
    const res = await fetch(`${apiBase}/sessions/${sessionId}`, {
      method: 'DELETE',
      headers: {
        'Content-Type': 'application/json',
        'x-session-deleted-by': 'chat_panel'
      },
      body: JSON.stringify({ reason: 'chat_panel_manual_delete' })
    });
    if (!res.ok) {
      const detail = await res.text();
      throw new Error(detail || 'session_delete_failed');
    }
    const data = await res.json();
    addActivity(
      `Session ${sessionId.slice(0, 6)} archived${data?.archivePath ? ` → ${data.archivePath}` : ''}.`,
      'info'
    );
    if (currentSession?.id === sessionId) {
      startFreshSession();
    } else {
      setInteractionState(false, 'Session archived');
    }
    await loadSessions();
  } catch (error) {
    console.error('Delete session failed', error);
    setInteractionState(false, 'Session archive failed');
    addActivity('Failed to archive session.', 'error');
  }
};

const renderSessions = () => {
  if (!sessionsListEl) {
    return;
  }
  sessionsListEl.innerHTML = '';
  if (!sessionSummaries.length) {
    const emptyState = document.createElement('div');
    emptyState.className = 'session-empty';
    emptyState.textContent = 'No saved sessions yet. Send a message to create one.';
    sessionsListEl.appendChild(emptyState);
    return;
  }
  const activeId = activeSessionId();
  sessionSummaries.forEach((session) => {
    const card = document.createElement('button');
    card.type = 'button';
    card.className = 'session-card';
    card.dataset.sessionId = session.id;
    if (session.id === activeId) {
      card.classList.add('session-card--active');
    }
    const titleRow = document.createElement('div');
    titleRow.className = 'session-card__row';
    const title = document.createElement('div');
    title.className = 'session-card__title';
    const resolvedTitle = session.metadata?.title || `Session ${session.id.slice(0, 6)}`;
    title.textContent = resolvedTitle;
    const pinBtn = document.createElement('button');
    pinBtn.type = 'button';
    pinBtn.className = 'session-pin';
    pinBtn.textContent = session.metadata?.pinned ? '★' : '☆';
    pinBtn.title = session.metadata?.pinned ? 'Unpin session' : 'Pin session';
    pinBtn.addEventListener('click', (event) => {
      event.stopPropagation();
      handlePinToggle(session.id, !session.metadata?.pinned);
    });
    titleRow.append(title, pinBtn);
    const controls = document.createElement('div');
    controls.className = 'session-card__controls';
    const renameBtn = document.createElement('button');
    renameBtn.type = 'button';
    renameBtn.className = 'session-rename';
    renameBtn.textContent = 'Rename';
    renameBtn.addEventListener('click', (event) => {
      event.stopPropagation();
      promptRename(session.id, resolvedTitle);
    });
    const autoBtn = document.createElement('button');
    autoBtn.type = 'button';
    autoBtn.className = 'session-auto';
    autoBtn.textContent = 'AI title';
    autoBtn.disabled = !session.messageCount;
    autoBtn.addEventListener('click', (event) => {
      event.stopPropagation();
      handleAutoTitle(session.id);
    });
    const deleteBtn = document.createElement('button');
    deleteBtn.type = 'button';
    deleteBtn.className = 'session-delete';
    deleteBtn.textContent = 'Archive';
    deleteBtn.addEventListener('click', (event) => {
      event.stopPropagation();
      handleDeleteSession(session.id);
    });
    controls.append(renameBtn, autoBtn, deleteBtn);
    const meta = document.createElement('div');
    meta.className = 'session-card__meta';
    meta.textContent = `${formatTimestamp(session.updatedAt)} · ${session.messageCount} messages`;
    const agents = document.createElement('div');
    agents.className = 'session-card__agents';
    agents.textContent = describeSessionAgents(session.agents);
    card.append(titleRow, controls, meta, agents);
    card.addEventListener('click', () => resumeSession(session.id));
    sessionsListEl.appendChild(card);
  });
};

const loadSessions = async () => {
  if (!sessionsListEl) {
    return;
  }
  sessionsListEl.textContent = 'Loading sessions…';
  try {
    const res = await fetch(`${apiBase}/sessions?limit=20`);
    if (!res.ok) {
      throw new Error('sessions_fetch_failed');
    }
    const data = await res.json();
    sessionSummaries = Array.isArray(data?.sessions) ? data.sessions : [];
    renderSessions();
  } catch (error) {
    console.error('Failed to load sessions', error);
    sessionsListEl.textContent = 'Failed to load sessions.';
  }
};

const resetTranscript = () => {
  resetStreamingState();
  chatEl.innerHTML = '';
  introsVisible = false;
};

const hydrateSession = (session) => {
  if (!session) {
    return;
  }
  currentSession = session;
  resetTranscript();
  const sessionAgents = Array.isArray(session.agents) ? session.agents : [];
  if (sessionAgents.length) {
    selectedAgents.clear();
    sessionAgents.forEach((id) => selectedAgents.add(id));
    if (!selectedAgents.has('orchestrator')) {
      selectedAgents.add('orchestrator');
    }
    updatePillStates();
    renderCrewSummary();
  }
  const messages = Array.isArray(session.messages) ? session.messages : [];
  if (!messages.length) {
    renderAgentIntros();
  } else {
    messages.forEach((message) => {
      if (message.role === 'assistant') {
        addMessage({ role: 'assistant', content: message.content, agentId: message.agentId || 'assistant' });
      } else {
        addMessage({ role: 'user', content: message.content, attachments: message.attachments || [] });
      }
    });
  }
  addActivity(`Resumed session ${session.id}`, 'info');
  renderSessions();
};

const resumeSession = async (sessionId) => {
  if (!sessionId) {
    return;
  }
  setInteractionState(true, 'Loading session…');
  try {
    const res = await fetch(`${apiBase}/sessions/${sessionId}`);
    if (!res.ok) {
      throw new Error('session_fetch_failed');
    }
    const data = await res.json();
    hydrateSession(data.session);
    setInteractionState(false, 'Session ready');
  } catch (error) {
    console.error('Failed to resume session', error);
    setInteractionState(false, 'Failed to load session');
  }
};

const startFreshSession = () => {
  currentSession = null;
  lastPrompt = null;
  lastTargets = [];
  lastAttachments = [];
  pendingAttachments = [];
  renderAttachments();
  resetTranscript();
  applyDefaultSelection();
  renderCrewSummary();
  renderAgentIntros();
  renderSessions();
  addActivity('Ready for a fresh conversation.', 'info');
  setInteractionState(false, 'New session ready');
};

const initSessionsPanel = () => {
  if (newSessionButton) {
    newSessionButton.addEventListener('click', startFreshSession);
  }
  loadSessions().catch((error) => console.error('Failed to load sessions', error));
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

const addMessage = ({ role, content, agentId, attachments }) => {
  clearAgentIntros();
  const wrapper = document.createElement('div');
  wrapper.className = ['message', role === 'assistant' ? 'assistant' : 'user'].join(' ');
  const header = document.createElement('strong');
  header.textContent = role === 'assistant' ? (agentId ? agentId : 'assistant') : 'you';
  const body = document.createElement('p');
  body.textContent = content;
  wrapper.append(header, body);
  if (role === 'user' && Array.isArray(attachments) && attachments.length) {
    const list = document.createElement('div');
    list.className = 'message-attachments';
    attachments.forEach((file) => {
      const chip = document.createElement('span');
      chip.className = 'attachment-chip';
      const icon = attachmentIcon(file.type);
      chip.textContent = `${icon} ${file.name || file.id || 'attachment'}`;
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
  const res = await fetch(`${apiBase}/sessions`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({
      agents: agentIds,
      metadata: {
        origin: 'chat-panel',
        userLabel
      }
    })
  });
  if (!res.ok) {
    const detail = await res.text();
    throw new Error(detail || 'session_create_failed');
  }
  const data = await res.json();
  currentSession = data.session;
  loadSessions().catch((error) => console.error('Failed to refresh sessions', error));
  return currentSession;
};

const postUserMessage = async (sessionId, agentTargets, content, attachments = []) => {
  const res = await fetch(`${apiBase}/sessions/${sessionId}/messages`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({
      role: 'user',
      content,
      agentTargets,
      attachments: attachments.length ? attachments : undefined
    })
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
  const source = new EventSource(`${apiBase}/sessions/${sessionId}/stream?${params.toString()}`);
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
  const readyAttachments = pendingAttachments
    .filter((file) => file.status === 'ready')
    .map(({ id, name, type, url, size }) => ({ id, name, type, url, size }));

  addMessage({ role: 'user', content, attachments: readyAttachments });
  messageInput.value = '';
  pendingAttachments = [];
  renderAttachments();
  setInteractionState(true, 'Dispatching orchestrator plan…');
  lastPrompt = content;
  lastTargets = [...targetAgents];
  lastAttachments = [...readyAttachments];
  try {
    const session = await ensureSession();
    await postUserMessage(session.id, targetAgents, content, readyAttachments);
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
      await postUserMessage(session.id, lastTargets, lastPrompt, lastAttachments);
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
    initAttachmentControls();
    initUserBadge();
    initSessionsPanel();
    renderAttachments();
    await loadAgents();
  } catch (error) {
    console.error('Failed to init panel', error);
    renderStatus('Failed to load agents', false);
  }
});
