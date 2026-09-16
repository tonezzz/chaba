const SITES = [
  { host: 'chatgpt.com', url: 'https://chatgpt.com/' },
  { host: 'gemini.google.com', url: 'https://gemini.google.com/app' },
  { host: 'claude.ai', url: 'https://claude.ai/chat' }
];

chrome.action.onClicked.addListener(() => {
  chrome.sidePanel.open({ windowId: chrome.windows.WINDOW_ID_CURRENT });
});

chrome.runtime.onMessage.addListener((request, sender, sendResponse) => {
  if (request.cmd === 'BROADCAST_PROMPT') {
    broadcast(request)
      .then(() => sendResponse({ ok: true }))
      .catch(err => sendResponse({ ok: false, error: err.message }));
    return true;
  }
  return false;
});

async function broadcast({ text, targets }) {
  const list = targets?.length
    ? SITES.filter(s => targets.includes(s.host))
    : SITES;

  for (const site of list) {
    const tabs = await chrome.tabs.query({ url: `https://${site.host}/*` });
    const tab = tabs[0] || await chrome.tabs.create({ url: site.url, active: false });
    await waitForTab(tab.id);
    try {
      await chrome.tabs.sendMessage(tab.id, { cmd: 'SEND', text });
    } catch (err) {
      console.error(`Failed to message ${site.host}:`, err);
    }
  }
}

function waitForTab(tabId) {
  return new Promise(resolve => {
    const listener = (id, info) => {
      if (id === tabId && info.status === 'complete') {
        chrome.tabs.onUpdated.removeListener(listener);
        setTimeout(resolve, 500);
      }
    };
    chrome.tabs.onUpdated.addListener(listener);
  });
}
