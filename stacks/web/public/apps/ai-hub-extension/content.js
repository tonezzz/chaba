function setNativeValue(element, value) {
  if (element.isContentEditable) {
    element.focus();
    document.execCommand('selectAll', false, null);
    document.execCommand('insertText', false, value);
    return;
  }
  const isTextArea = element.tagName === 'TEXTAREA';
  const proto = isTextArea ? window.HTMLTextAreaElement.prototype : window.HTMLInputElement.prototype;
  const descriptor = Object.getOwnPropertyDescriptor(proto, 'value');
  if (descriptor && descriptor.set) {
    descriptor.set.call(element, value);
  } else {
    element.value = value;
  }
  element.dispatchEvent(new Event('input', { bubbles: true }));
  element.dispatchEvent(new Event('change', { bubbles: true }));
}

const adapters = {
  'chatgpt.com': {
    promptSelector: '#prompt-textarea',
    sendSelector: 'button[data-testid="send-button"]'
  },
  'gemini.google.com': {
    promptSelector: 'div[contenteditable="true"], textarea',
    sendSelector: 'button[aria-label="Send message"]'
  },
  'claude.ai': {
    promptSelector: 'div[contenteditable="true"]',
    sendSelector: 'button[aria-label="Send message"], button[aria-label="Send"]'
  },
  'midjourney.com': {
    promptSelector: 'textarea, input[type="text"], div[contenteditable="true"], [data-testid="prompt-input"], [placeholder*="imagine" i]',
    sendSelector: 'button[type="submit"], button[aria-label="Imagine"], button[aria-label="Create"], button[aria-label="Generate"], [data-testid="imagine-button"], [data-testid="generate-button"]'
  }
};

const host = location.hostname;
const site = Object.keys(adapters).find(h => host === h || host.endsWith('.' + h));
const adapter = site ? adapters[site] : null;
if (!adapter) return;

function setPrompt(text) {
  const el = document.querySelector(adapter.promptSelector);
  if (!el) return;
  setNativeValue(el, text);
}

function clickSend() {
  const btn = document.querySelector(adapter.sendSelector);
  if (btn && !btn.disabled) btn.click();
}

function readLastAssistant() {
  if (site === 'midjourney.com') {
    const imgs = document.querySelectorAll('img');
    return `Found ${imgs.length} images on the page.`;
  }
  if (site === 'chatgpt.com') {
    const articles = document.querySelectorAll('article');
    return articles[articles.length - 1]?.innerText || '';
  }
  if (site === 'gemini.google.com') {
    const nodes = document.querySelectorAll('.model-response-text');
    return nodes[nodes.length - 1]?.innerText || '';
  }
  if (site === 'claude.ai') {
    const nodes = document.querySelectorAll('[data-testid="user-message"], .claude-message, .font-claude-message');
    return nodes[nodes.length - 1]?.innerText || '';
  }
  return '';
}

chrome.runtime.onMessage.addListener((request, sender, sendResponse) => {
  if (request.cmd === 'SEND') {
    setPrompt(request.text);
    setTimeout(() => clickSend(), 200);
    sendResponse({ ok: true });
  } else if (request.cmd === 'READ') {
    sendResponse({ text: readLastAssistant() });
  }
  return true;
});

let lastText = '';
setInterval(() => {
  const text = readLastAssistant();
  if (text && text !== lastText) {
    lastText = text;
    chrome.runtime.sendMessage({ cmd: 'RESPONSE', site: location.hostname, text });
  }
}, 3000);
