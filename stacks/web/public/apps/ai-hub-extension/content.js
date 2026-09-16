const adapters = {
  'chatgpt.com': {
    setPrompt(text) {
      const el = document.querySelector('#prompt-textarea');
      if (!el) return;
      el.focus();
      document.execCommand('selectAll', false, null);
      document.execCommand('insertText', false, text);
    },
    clickSend() {
      const btn = document.querySelector('button[data-testid="send-button"]');
      if (btn && !btn.disabled) btn.click();
    },
    readLastAssistant() {
      const articles = document.querySelectorAll('article');
      return articles[articles.length - 1]?.innerText || '';
    }
  },
  'gemini.google.com': {
    setPrompt(text) {
      const el = document.querySelector('div[contenteditable="true"], textarea');
      if (!el) return;
      el.focus();
      document.execCommand('insertText', false, text);
    },
    clickSend() {
      const btn = document.querySelector('button[aria-label="Send message"]');
      if (btn) btn.click();
    },
    readLastAssistant() {
      const nodes = document.querySelectorAll('.model-response-text');
      return nodes[nodes.length - 1]?.innerText || '';
    }
  },
  'claude.ai': {
    setPrompt(text) {
      const el = document.querySelector('div[contenteditable="true"]');
      if (!el) return;
      el.focus();
      document.execCommand('insertText', false, text);
    },
    clickSend() {
      const btn = document.querySelector('button[aria-label="Send message"], button[aria-label="Send"]');
      if (btn) btn.click();
    },
    readLastAssistant() {
      const nodes = document.querySelectorAll('[data-testid="user-message"], .claude-message, .font-claude-message');
      return nodes[nodes.length - 1]?.innerText || '';
    }
  }
};

const adapter = adapters[location.hostname];
if (!adapter) return;

chrome.runtime.onMessage.addListener((request, sender, sendResponse) => {
  if (request.cmd === 'SEND') {
    adapter.setPrompt(request.text);
    setTimeout(() => adapter.clickSend(), 200);
    sendResponse({ ok: true });
  } else if (request.cmd === 'READ') {
    sendResponse({ text: adapter.readLastAssistant() });
  }
  return true;
});

let lastText = '';
setInterval(() => {
  const text = adapter.readLastAssistant();
  if (text && text !== lastText) {
    lastText = text;
    chrome.runtime.sendMessage({ cmd: 'RESPONSE', site: location.hostname, text });
  }
}, 3000);
