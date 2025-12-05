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
    const res = await fetch(`${apiBase}/archives/${archiveId}`);
    if (!res.ok) {
      throw new Error('archive_fetch_failed');
    }
    const data = await res.json();
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
    const res = await fetch(`${apiBase}/archives?limit=20`);
    if (!res.ok) {
      throw new Error('archives_fetch_failed');
    }
    const data = await res.json();
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
    await Promise.all([loadSessions(), loadArchives()]);
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
  const activeId = currentSession?.id || null;
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
    agents.textContent = Array.isArray(session.agents) ? session.agents.join(', ') : 'Orchestrator only';
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

/* remaining existing logic from previous main.js should follow (agent selection, streaming, etc.) */
