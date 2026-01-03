const $ = (id) => document.getElementById(id);

const backendStatus = $('backendStatus');
const refreshBtn = $('refreshBtn');
const filterInput = $('filterInput');
const toolSelect = $('toolSelect');
const argsInput = $('argsInput');
const callBtn = $('callBtn');
const copyBtn = $('copyBtn');
const resultEl = $('result');
const statusEl = $('status');

const pmPrefixEl = $('pmPrefix');
const pmToolCountEl = $('pmToolCount');
const pmStatusEl = $('pmStatus');
const pmListTasksBtn = $('pmListTasksBtn');
const pmLoadListTasksBtn = $('pmLoadListTasksBtn');
const pmCreateTaskBtn = $('pmCreateTaskBtn');
const pmLoadCreateTaskBtn = $('pmLoadCreateTaskBtn');
const pmTitle = $('pmTitle');
const pmDescription = $('pmDescription');
const pmPriority = $('pmPriority');
const pmTaskStatus = $('pmTaskStatus');

let allTools = [];

let pmTools = [];
let pmPrefix = '';

const setStatus = (text) => {
  statusEl.textContent = text;
};

const setPmStatus = (text) => {
  if (pmStatusEl) pmStatusEl.textContent = text;
};

const pretty = (value) => {
  try {
    return JSON.stringify(value, null, 2);
  } catch {
    return String(value);
  }
};

const detectProjectManagerTools = () => {
  pmTools = allTools.filter((tool) => {
    const name = (tool?.name || '').toLowerCase();
    return name.includes('project') || name.includes('project-manager') || name.includes('pm');
  });

  const prefixes = new Map();
  for (const tool of pmTools) {
    const name = tool?.name || '';
    const idx = name.indexOf('_');
    const prefix = idx > 0 ? name.slice(0, idx) : '';
    if (prefix) prefixes.set(prefix, (prefixes.get(prefix) || 0) + 1);
  }

  let best = '';
  let bestCount = 0;
  for (const [key, value] of prefixes.entries()) {
    if (value > bestCount) {
      best = key;
      bestCount = value;
    }
  }

  pmPrefix = best;
  if (pmPrefixEl) pmPrefixEl.textContent = pmPrefix || '(unknown)';
  if (pmToolCountEl) pmToolCountEl.textContent = String(pmTools.length);

  const enabled = pmTools.length > 0;
  if (pmListTasksBtn) pmListTasksBtn.disabled = !enabled;
  if (pmLoadListTasksBtn) pmLoadListTasksBtn.disabled = !enabled;
  if (pmCreateTaskBtn) pmCreateTaskBtn.disabled = !enabled;
  if (pmLoadCreateTaskBtn) pmLoadCreateTaskBtn.disabled = !enabled;

  setPmStatus(enabled ? 'Ready.' : 'No Project Manager tools detected yet.');
};

const findToolByHint = (hints) => {
  const candidates = pmTools.length ? pmTools : allTools;
  const normalizedHints = (hints || []).map((h) => String(h || '').toLowerCase()).filter(Boolean);
  for (const tool of candidates) {
    const name = (tool?.name || '').toLowerCase();
    if (normalizedHints.every((hint) => name.includes(hint))) {
      return tool?.name || '';
    }
  }
  return '';
};

const loadIntoEditor = ({ name, args }) => {
  if (name) {
    toolSelect.value = name;
  }
  argsInput.value = pretty(args || {});
};

const updateToolOptions = () => {
  const filter = (filterInput.value || '').trim().toLowerCase();
  const tools = filter
    ? allTools.filter((tool) => (tool?.name || '').toLowerCase().includes(filter))
    : allTools;

  toolSelect.innerHTML = '';
  tools.forEach((tool) => {
    const opt = document.createElement('option');
    opt.value = tool.name;
    opt.textContent = tool.name;
    toolSelect.appendChild(opt);
  });

  if (!tools.length) {
    const opt = document.createElement('option');
    opt.value = '';
    opt.textContent = '(no tools found)';
    toolSelect.appendChild(opt);
  }
};

const fetchTools = async () => {
  setStatus('Fetching tools…');
  backendStatus.textContent = 'Loading…';
  refreshBtn.disabled = true;
  callBtn.disabled = true;

  try {
    const response = await fetch('/test/project/api/tools');
    const data = await response.json();
    if (!response.ok) {
      backendStatus.textContent = 'Error';
      resultEl.textContent = pretty(data);
      setStatus(`Failed to fetch tools (HTTP ${response.status}).`);
      return;
    }

    allTools = Array.isArray(data?.tools) ? data.tools : [];
    backendStatus.textContent = 'OK';
    updateToolOptions();
    detectProjectManagerTools();
    setStatus(`Loaded ${allTools.length} tool(s).`);
    resultEl.textContent = pretty(data);
  } catch (err) {
    backendStatus.textContent = 'Error';
    resultEl.textContent = pretty({ error: err?.message || String(err) });
    setStatus('Failed to fetch tools (network error).');
  } finally {
    refreshBtn.disabled = false;
    callBtn.disabled = false;
  }
};

const callTool = async () => {
  const name = toolSelect.value;
  if (!name) {
    setStatus('Select a tool first.');
    return;
  }

  let args = {};
  try {
    const raw = (argsInput.value || '').trim();
    args = raw ? JSON.parse(raw) : {};
  } catch (err) {
    setStatus(`Arguments JSON invalid: ${err?.message || String(err)}`);
    return;
  }

  setStatus(`Calling ${name}…`);
  callBtn.disabled = true;

  try {
    const response = await fetch('/test/project/api/call', {
      method: 'POST',
      headers: { 'content-type': 'application/json' },
      body: JSON.stringify({ name, arguments: args })
    });
    const data = await response.json();
    resultEl.textContent = pretty(data);
    if (!response.ok) {
      setStatus(`Tool call failed (HTTP ${response.status}).`);
      return;
    }
    setStatus('Done.');
  } catch (err) {
    resultEl.textContent = pretty({ error: err?.message || String(err) });
    setStatus('Tool call failed (network error).');
  } finally {
    callBtn.disabled = false;
  }
};

const buildCreateTaskArgs = () => {
  const title = (pmTitle?.value || '').trim();
  const description = (pmDescription?.value || '').trim();
  const priorityValue = (pmPriority?.value || '').trim();
  const statusValue = (pmTaskStatus?.value || '').trim();

  const args = {};
  if (title) args.title = title;
  if (description) args.description = description;
  if (priorityValue) args.priority = priorityValue;
  if (statusValue) args.status = statusValue;

  return args;
};

const wirePmButtons = () => {
  const callViaApi = async ({ name, args }) => {
    toolSelect.value = name;
    argsInput.value = pretty(args || {});
    await callTool();
  };

  const listToolName = () => findToolByHint(['list', 'tasks']) || findToolByHint(['tasks', 'list']);
  const createToolName = () => findToolByHint(['create', 'task']) || findToolByHint(['task', 'create']);

  if (pmListTasksBtn) {
    pmListTasksBtn.disabled = true;
    pmListTasksBtn.addEventListener('click', async () => {
      const toolName = listToolName();
      if (!toolName) {
        setPmStatus('Could not find a list-tasks tool. Use the generic tool list below.');
        return;
      }
      setPmStatus(`Calling ${toolName}…`);
      await callViaApi({ name: toolName, args: {} });
      setPmStatus('Done.');
    });
  }

  if (pmLoadListTasksBtn) {
    pmLoadListTasksBtn.disabled = true;
    pmLoadListTasksBtn.addEventListener('click', () => {
      const toolName = listToolName();
      if (!toolName) {
        setPmStatus('Could not find a list-tasks tool.');
        return;
      }
      loadIntoEditor({ name: toolName, args: {} });
      setPmStatus('Loaded into editor.');
    });
  }

  if (pmCreateTaskBtn) {
    pmCreateTaskBtn.disabled = true;
    pmCreateTaskBtn.addEventListener('click', async () => {
      const toolName = createToolName();
      if (!toolName) {
        setPmStatus('Could not find a create-task tool. Use the generic tool list below.');
        return;
      }
      const args = buildCreateTaskArgs();
      if (!Object.keys(args).length) {
        setPmStatus('Provide at least a Title.');
        return;
      }
      setPmStatus(`Calling ${toolName}…`);
      await callViaApi({ name: toolName, args });
      setPmStatus('Done.');
    });
  }

  if (pmLoadCreateTaskBtn) {
    pmLoadCreateTaskBtn.disabled = true;
    pmLoadCreateTaskBtn.addEventListener('click', () => {
      const toolName = createToolName();
      if (!toolName) {
        setPmStatus('Could not find a create-task tool.');
        return;
      }
      const args = buildCreateTaskArgs();
      loadIntoEditor({ name: toolName, args });
      setPmStatus('Loaded into editor.');
    });
  }
};

refreshBtn.addEventListener('click', fetchTools);
filterInput.addEventListener('input', updateToolOptions);
callBtn.addEventListener('click', callTool);
copyBtn.addEventListener('click', async () => {
  try {
    await navigator.clipboard.writeText(resultEl.textContent || '');
    setStatus('Copied result.');
  } catch {
    setStatus('Copy failed.');
  }
});

fetchTools();

wirePmButtons();
