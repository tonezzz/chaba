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
  } catch {}
  return 'default';
};

const userId = resolveUserId();
const onDevHost = window.location.pathname.startsWith('/test/agents');
const API_PREFIX = onDevHost ? '/test/agents/api' : '/api';
const apiBase = `${API_PREFIX}/users/${encodeURIComponent(userId)}`;
const registryEndpoint = `${API_PREFIX}/agents/registry`;
const userLabel = userId === 'default' ? 'Default workspace' : `${formatUserLabel(userId)} workspace`;

const attachmentIcon = (type = '') => {
  if (type?.startsWith('image/')) return '🖼️';
  if (type?.startsWith('video/')) return '🎞️';
  if (type?.startsWith('audio/')) return '🎧';
  if (type?.includes('pdf')) return '📄';
  if (type?.includes('zip')) return '🗜️';
  return '📎';
};

const $ = (selector) => document.querySelector(selector);
const chatEl = $('#chat');
const activityEl = $('#activity');
const statusEl = $('#status');
const userBadgeEl = $('#userBadge');
const sessionsListEl = $('#sessionsList');
const archivesListEl = $('#archivesList');
const archiveDetailEl = $('#archiveDetail');
const archiveDetailBodyEl = $('#archiveDetailBody');
const refreshArchivesButton = $('#refreshArchivesButton');
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
let archiveSummaries = [];

const renderStatus = (text, ok = false) => {
  if (!statusEl) return;
  statusEl.textContent = text;
  statusEl.classList.toggle('ok', ok);
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

const fetchJSON = async (url, options = {}) => {
  const response = await fetch(url, options);
  if (!response.ok) {
    const detail = await response.text();
    throw new Error(detail || `HTTP ${response.status}`);
  }
  if (response.status === 204) {
    return null;
  }
  return response.json();
};

const setInteractionState = (disabled, label = null) => {
  if (sendButton) {
    sendButton.disabled = disabled;
    sendButton.textContent = disabled && label ? label : defaultButtonLabel;
  }
  if (messageInput) {
    messageInput.disabled = disabled;
  }
};

const renderAttachmentsList = () => {
  if (!attachmentsList) return;
  attachmentsList.innerHTML = '';
  pendingAttachments.forEach((file) => {
    const chip = document.createElement('span');
    chip.className = 'attachment-chip';
    chip.textContent = `${attachmentIcon(file.type)} ${file.name} (${Math.round(file.size / 1024)} KB)`;
    attachmentsList.appendChild(chip);
  });
};

const handleAttachmentInput = () => {
  if (!attachmentInput) return;
  const files = Array.from(attachmentInput.files || []);
  pendingAttachments = files;
  renderAttachmentsList();
};

const buildAttachmentMetadata = () =>
  pendingAttachments.map((file) => ({
    name: file.name,
    size: file.size,
    mime: file.type || 'application/octet-stream'
  }));

const renderArchives = () => {
  if (!archivesListEl) {
    return;
  }
  archivesListEl.innerHTML = '';
  if (!archiveSummaries.length) {
    const empty = document.createElement('div');
    empty.className = 'session-empty';
    empty.textContent = 'No archives yet. Archive a session to preview its summary.';
    archivesListEl.appendChild(empty);
    return;
  }

  archiveSummaries.forEach((archive) => {
    const card = document.createElement('button');
    card.type = 'button';
    card.className = 'archive-card';
    card.dataset.archiveId = archive.archiveId;
    const summary = document.createElement('p');
    summary.className = 'archive-card__summary';
    summary.textContent = archive.summary || `(Archive ${archive.archiveId.slice(0, 6)})`;
    const meta = document.createElement('div');
    meta.className = 'archive-card__meta';
    const deletedAt = document.createElement('span');
    deletedAt.textContent = `🕒 ${formatTimestamp(archive.deletedAt)}`;
    const agents = document.createElement('span');
    agents.textContent = `🤖 ${Array.isArray(archive.agents) ? archive.agents.join(', ') : 'n/a'}`;
    const messages = document.createElement('span');
    messages.textContent = `💬 ${archive.messageCount ?? 0} msgs`;
    meta.append(deletedAt, agents, messages);
    card.append(summary, meta);
    card.addEventListener('click', () => previewArchiveDetail(archive.archiveId));
    archivesListEl.appendChild(card);
  });
};

const previewArchiveDetail = async (archiveId) => {
  if (!archiveDetailEl || !archiveDetailBodyEl) {
    return;
  }
  archiveDetailEl.open = true;
  archiveDetailBodyEl.textContent = 'Loading archive details…';
  try {
    const data = await fetchJSON(`${apiBase}/archives/${archiveId}`);
    const archive = data?.archive;
    if (!archive) {
      archiveDetailBodyEl.textContent = 'Archive not found.';
      return;
    }
    const payload = {
      archiveId: archive.archiveId,
      sessionId: archive.sessionId,
      summary: archive.summary,
      deletedAt: archive.deletedAt,
      agents: archive.agents,
      messageCount: archive.messageCount,
      storedMessages: archive.storedMessages || []
    };
    archiveDetailBodyEl.textContent = JSON.stringify(payload, null, 2);
  } catch (error) {
    console.error('Archive detail failed', error);
    archiveDetailBodyEl.textContent = 'Failed to load archive detail.';
  }
};

const loadArchives = async () => {
  if (!archivesListEl) {
    return;
  }
  archivesListEl.textContent = 'Loading archives…';
  try {
    const data = await fetchJSON(`${apiBase}/archives?limit=20`);
    archiveSummaries = Array.isArray(data?.archives) ? data.archives : [];
    renderArchives();
  } catch (error) {
    console.error('Failed to load archives', error);
    archivesListEl.textContent = 'Failed to load archives.';
  }
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
    const res = await fetchJSON(`${apiBase}/sessions/${sessionId}`, {
      method: 'DELETE',
      headers: {
        'Content-Type': 'application/json',
        'x-session-deleted-by': 'chat_panel'
      },
      body: JSON.stringify({ reason: 'chat_panel_manual_delete' })
    });
    addActivity(
      `Session ${sessionId.slice(0, 6)} archived${res?.archivePath ? ` → ${res.archivePath}` : ''}.`,
      'info'
    );
    if (currentSession?.id === sessionId) {
      currentSession = null;
      closeStream();
    }
    await Promise.all([loadSessions(), loadArchives()]);
    setInteractionState(false, 'Session archived');
  } catch (error) {
    console.error('Delete session failed', error);
    setInteractionState(false, 'Session archive failed');
    addActivity('Failed to archive session.', 'error');
  }
};

const updateSessionSummary = (session) => {
  const index = sessionSummaries.findIndex((item) => item.id === session.id);
  if (index === -1) {
    sessionSummaries.push(session);
  } else {
    sessionSummaries[index] = session;
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
  const activeId = currentSession?.id || null;
  sessionSummaries
    .slice()
    .sort((a, b) => new Date(b.updatedAt) - new Date(a.updatedAt))
    .forEach((session) => {
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
      pinBtn.addEventListener('click', async (event) => {
        event.stopPropagation();
        await handlePinToggle(session.id, !session.metadata?.pinned);
      });
      titleRow.append(title, pinBtn);
      const controls = document.createElement('div');
      controls.className = 'session-card__controls';
      const renameBtn = document.createElement('button');
      renameBtn.type = 'button';
      renameBtn.className = 'session-rename';
      renameBtn.textContent = 'Rename';
      renameBtn.addEventListener('click', async (event) => {
        event.stopPropagation();
        const nextTitle = window.prompt('Rename session', resolvedTitle);
        if (nextTitle?.trim()) {
          await updateSessionMetadata(session.id, { title: nextTitle.trim(), autoTitle: false });
        }
      });
      const autoBtn = document.createElement('button');
      autoBtn.type = 'button';
      autoBtn.className = 'session-auto';
      autoBtn.textContent = 'AI title';
      autoBtn.disabled = !session.messageCount;
      autoBtn.addEventListener('click', async (event) => {
        event.stopPropagation();
        await updateSessionMetadata(session.id, { autoTitle: true });
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
      agents.textContent = Array.isArray(session.agents) ? session.agents.join(', ') : 'Orchestrator only';
      card.append(titleRow, controls, meta, agents);
      card.addEventListener('click', () => resumeSession(session.id));
      sessionsListEl.appendChild(card);
    });
};

const updateSessionMetadata = async (sessionId, metadata) => {
  try {
    const data = await fetchJSON(`${apiBase}/sessions/${sessionId}`, {
      method: 'PATCH',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ metadata })
    });
    if (data?.session) {
      updateSessionSummary(data.session);
      if (currentSession?.id === sessionId) {
        currentSession = data.session;
        renderChat();
      }
      renderSessions();
    }
  } catch (error) {
    console.error('Update metadata failed', error);
    addActivity('Failed to update session metadata.', 'error');
  }
};

const handlePinToggle = async (sessionId, nextPinned) => {
  await updateSessionMetadata(sessionId, { pinned: nextPinned });
};

const loadSessions = async () => {
  if (!sessionsListEl) {
    return;
  }
  sessionsListEl.textContent = 'Loading sessions…';
  try {
    const data = await fetchJSON(`${apiBase}/sessions?limit=20`);
    sessionSummaries = Array.isArray(data?.sessions) ? data.sessions : [];
    renderSessions();
    if (!currentSession && sessionSummaries.length) {
      resumeSession(sessionSummaries[0].id);
    }
  } catch (error) {
    console.error('Failed to load sessions', error);
    sessionsListEl.textContent = 'Failed to load sessions.';
  }
};

const ensureSession = async () => {
  if (currentSession) {
    return currentSession;
  }
  const data = await fetchJSON(`${apiBase}/sessions`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ metadata: { autoTitle: true } })
  });
  if (data?.session) {
    currentSession = data.session;
    updateSessionSummary(data.session);
    renderSessions();
    openStream(currentSession.id);
  }
  return currentSession;
};

const startFreshSession = async () => {
  setInteractionState(true, 'Creating session…');
  try {
    const data = await fetchJSON(`${apiBase}/sessions`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ metadata: { autoTitle: true } })
    });
    if (data?.session) {
      currentSession = data.session;
      updateSessionSummary(data.session);
      renderSessions();
      renderChat();
      openStream(currentSession.id);
      addActivity(`Started session ${currentSession.id.slice(0, 6)}.`, 'info');
    }
  } catch (error) {
    console.error('Failed to start session', error);
    addActivity('Failed to create new session.', 'error');
  } finally {
    setInteractionState(false);
  }
};

const closeStream = () => {
  if (currentStream) {
    currentStream.close();
    currentStream = null;
  }
  if (retryTimer) {
    clearTimeout(retryTimer);
    retryTimer = null;
  }
};

const scheduleStreamRetry = () => {
  if (!autoRetryToggle?.checked) return;
  if (retryTimer) clearTimeout(retryTimer);
  retryTimer = setTimeout(() => {
    if (currentSession) {
      openStream(currentSession.id);
    }
  }, 3000);
};

const applyAgentStatus = (agent, status) => {
  agentStatuses.set(agent, status);
  const pill = agentPillsEl?.querySelector(`[data-agent="${agent}"]`);
  if (!pill) return;
  pill.classList.remove('agent-pill--running', 'agent-pill--done', 'agent-pill--queued', 'agent-pill--error');
  if (status === 'running') pill.classList.add('agent-pill--running');
  if (status === 'done') pill.classList.add('agent-pill--done');
  if (status === 'queued') pill.classList.add('agent-pill--queued');
  if (status === 'error') pill.classList.add('agent-pill--error');
};

const handleAgentUpdate = (payload) => {
  const { agent, status, content } = payload || {};
  if (!agent) return;
  applyAgentStatus(agent, status || 'running');
  if (content) {
    streamingMessages.set(agent, content);
    addAgentMessage(agent, content);
  }
};

const handleRunStatus = (payload) => {
  if (payload?.status === 'running') {
    renderStatus('Agents running…', false);
  } else if (payload?.status === 'done') {
    renderStatus('All agents done', true);
  }
};

const handleRunComplete = async (payload) => {
  renderStatus('Idle', true);
  addActivity(`Run complete: ${payload?.summary || 'no summary'}`, 'success');
  await loadSessions();
  if (currentSession) {
    const refreshed = sessionSummaries.find((session) => session.id === currentSession.id);
    if (refreshed) {
      currentSession = refreshed;
      renderChat();
    }
  }
};

const openStream = (sessionId) => {
  closeStream();
  if (!sessionId) return;
  const streamUrl = `${apiBase}/sessions/${sessionId}/stream`;
  currentStream = new EventSource(streamUrl);
  currentStream.addEventListener('run_status', (event) => {
    handleRunStatus(JSON.parse(event.data));
  });
  currentStream.addEventListener('agent_update', (event) => {
    handleAgentUpdate(JSON.parse(event.data));
  });
  currentStream.addEventListener('run_complete', (event) => {
    handleRunComplete(JSON.parse(event.data));
  });
  currentStream.addEventListener('error', () => {
    addActivity('Stream disconnected. Will retry shortly.', 'error');
    closeStream();
    scheduleStreamRetry();
  });
};

const renderCrewSummary = () => {
  if (!crewSummaryEl) return;
  const entries = Array.from(selectedAgents)
    .map((agentId) => AGENT_INTROS[agentId]?.en || agentId)
    .join(' · ');
  crewSummaryEl.textContent = entries
    ? `Crew ready: ${entries}`
    : 'Select at least one specialist to join the orchestrator.';
};

const renderAgentPills = () => {
  if (!agentPillsEl) return;
  agentPillsEl.innerHTML = '';
  availableAgents.forEach((agent) => {
    const pill = document.createElement('button');
    pill.type = 'button';
    pill.className = 'agent-pill';
    pill.dataset.agent = agent.id;
    if (selectedAgents.has(agent.id)) {
      pill.classList.add('agent-pill--active');
    }
    const name = document.createElement('span');
    name.className = 'agent-pill__name';
    name.textContent = agent.name;
    const idTag = document.createElement('span');
    idTag.className = 'agent-pill__id';
    idTag.textContent = agent.id;
    pill.append(name, idTag);
    pill.addEventListener('click', () => {
      if (selectedAgents.has(agent.id)) {
        selectedAgents.delete(agent.id);
      } else {
        selectedAgents.add(agent.id);
      }
      renderAgentPills();
      renderCrewSummary();
    });
    agentPillsEl.appendChild(pill);
  });
  renderCrewSummary();
};

const loadAgents = async () => {
  renderStatus('Loading agents…');
  try {
    const data = await fetchJSON(registryEndpoint);
    availableAgents = Array.isArray(data?.agents) ? data.agents : [];
    if (!selectedAgents.size && availableAgents.length) {
      // Default to orchestrator or first agent
      selectedAgents.add('orchestrator');
    }
    renderAgentPills();
    renderStatus('Ready', true);
  } catch (error) {
    console.error('Failed to load agents', error);
    renderStatus('Failed to load agents', false);
    addActivity('Unable to load agent registry.', 'error');
  }
};

const addAgentMessage = (agent, content) => {
  if (!chatEl) return;
  const message = document.createElement('article');
  message.className = 'message assistant';
  const header = document.createElement('strong');
  header.textContent = agent ? agent.toUpperCase() : 'ASSISTANT';
  const body = document.createElement('p');
  body.textContent = content;
  message.append(header, body);
  chatEl.appendChild(message);
  chatEl.scrollTop = chatEl.scrollHeight;
};

const renderChat = () => {
  if (!chatEl) return;
  chatEl.innerHTML = '';
  const session = currentSession;
  if (!session || !Array.isArray(session.messages)) {
    const intro = document.createElement('div');
    intro.className = 'intro-card';
    intro.textContent = 'No messages yet. Describe what you want the crew to investigate.';
    chatEl.appendChild(intro);
    return;
  }
  session.messages.forEach((msg) => {
    const wrapper = document.createElement('article');
    wrapper.className = `message ${msg.role || 'assistant'}`;
    const header = document.createElement('strong');
    header.textContent = msg.agent ? `${msg.agent.toUpperCase()}` : msg.role || 'assistant';
    const body = document.createElement('p');
    body.textContent = msg.content;
    wrapper.append(header, body);
    chatEl.appendChild(wrapper);
  });
  chatEl.scrollTop = chatEl.scrollHeight;
};

const resumeSession = (sessionId) => {
  const session = sessionSummaries.find((item) => item.id === sessionId);
  if (!session) {
    addActivity('Session not found.', 'error');
    return;
  }
  currentSession = session;
  renderSessions();
  renderChat();
  openStream(sessionId);
};

const handleSendMessage = async (event) => {
  event.preventDefault();
  if (!messageInput) return;
  const prompt = messageInput.value.trim();
  if (!prompt) {
    messageInput.focus();
    return;
  }
  const historyLimit = Number(historyInput?.value) || 20;
  const targets = selectedAgents.size ? Array.from(selectedAgents) : ['orchestrator'];
  lastPrompt = prompt;
  lastTargets = targets;
  setInteractionState(true, 'Sending…');
  try {
    const session = await ensureSession();
    if (!session) {
      throw new Error('session_missing');
    }
    const payload = {
      prompt,
      agents: targets,
      historyLimit,
      attachments: buildAttachmentMetadata(),
      locale: navigator.language || 'en-US',
      metadata: { autoTitle: true }
    };
    const data = await fetchJSON(`${apiBase}/sessions/${session.id}/messages`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(payload)
    });
    addActivity(`Queued run ${data?.runId || ''} with ${targets.join(', ')}.`, 'info');
    pendingAttachments = [];
    renderAttachmentsList();
    messageInput.value = '';
    await loadSessions();
    openStream(session.id);
  } catch (error) {
    console.error('Send failed', error);
    addActivity('Message failed to send.', 'error');
  } finally {
    setInteractionState(false);
  }
};

const initAutos = () => {
  if (autoSendToggle) {
    const stored = localStorage.getItem(AUTO_SEND_KEY);
    autoSendToggle.checked = stored !== 'false';
    autoSendToggle.addEventListener('change', () => {
      localStorage.setItem(AUTO_SEND_KEY, autoSendToggle.checked ? 'true' : 'false');
    });
  }
  if (autoRetryToggle) {
    const stored = localStorage.getItem(AUTO_RETRY_KEY);
    autoRetryToggle.checked = stored !== 'false';
    autoRetryToggle.addEventListener('change', () => {
      localStorage.setItem(AUTO_RETRY_KEY, autoRetryToggle.checked ? 'true' : 'false');
    });
  }
};

const initForm = () => {
  if (!form) return;
  form.addEventListener('submit', handleSendMessage);
  if (messageInput && autoSendToggle) {
    messageInput.addEventListener('keydown', (event) => {
      if (event.key === 'Enter' && !event.shiftKey && autoSendToggle.checked) {
        event.preventDefault();
        form.dispatchEvent(new Event('submit', { cancelable: true, bubbles: true }));
      }
    });
  }
};

const initArchivesPanel = () => {
  if (refreshArchivesButton) {
    refreshArchivesButton.addEventListener('click', () => loadArchives());
  }
  loadArchives().catch((error) => console.error('Failed to load archives', error));
};

const initSessionsPanel = () => {
  if (newSessionButton) {
    newSessionButton.addEventListener('click', startFreshSession);
  }
  loadSessions().catch((error) => console.error('Failed to load sessions', error));
};

const initAttachments = () => {
  if (attachButton && attachmentInput) {
    attachButton.addEventListener('click', () => attachmentInput.click());
    attachmentInput.addEventListener('change', handleAttachmentInput);
  }
};

const init = () => {
  initUserBadge();
  initAutos();
  initForm();
  initAttachments();
  initSessionsPanel();
  initArchivesPanel();
  loadAgents();
};

document.addEventListener('DOMContentLoaded', init);
