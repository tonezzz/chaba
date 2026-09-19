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

if (window.__aiHubInjected) {
  return;
}
window.__aiHubInjected = true;

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
  },
  'aistudio.google.com': {
    promptSelector: 'textarea, div[contenteditable="true"], ms-prompt-input-wrapper textarea',
    sendSelector: 'button[aria-label*="Run" i], button[title*="Run" i], button[data-testid="run-button"], .run-button'
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
  if (site === 'aistudio.google.com') {
    const turns = document.querySelectorAll('ms-chat-turn[data-turn-role="Model"], ms-chat-turn, .chat-turn-container');
    const last = turns[turns.length - 1];
    const node = last?.querySelector('.markdown, ms-cmark-node') || last;
    return node?.innerText?.trim() || '';
  }
  return '';
}

function getCssPath(el) {
  if (!el) return '';
  const parts = [];
  while (el && el.nodeType === Node.ELEMENT_NODE) {
    let name = el.nodeName.toLowerCase();
    if (el.id) {
      name += '#' + el.id;
      parts.unshift(name);
      break;
    }
    let sib = el;
    let nth = 1;
    while (sib = sib.previousElementSibling) {
      if (sib.nodeName.toLowerCase() === name) nth++;
    }
    if (nth > 1 || el.nextElementSibling) name += `:nth-of-type(${nth})`;
    parts.unshift(name);
    el = el.parentElement;
  }
  return parts.join(' > ');
}

function getDebugInfo() {
  const el = document.querySelector(adapter.promptSelector);
  const btn = document.querySelector(adapter.sendSelector);
  return {
    site: location.hostname,
    prompt: {
      found: !!el,
      selector: getCssPath(el),
      html: el ? el.outerHTML.slice(0, 500) : '',
      rect: el ? el.getBoundingClientRect().toJSON() : null
    },
    send: {
      found: !!btn,
      selector: getCssPath(btn),
      html: btn ? btn.outerHTML.slice(0, 500) : '',
      rect: btn ? btn.getBoundingClientRect().toJSON() : null
    }
  };
}

chrome.runtime.onMessage.addListener((request, sender, sendResponse) => {
  if (request.cmd === 'SEND') {
    setPrompt(request.text);
    setTimeout(() => clickSend(), 200);
    sendResponse({ ok: true });
  } else if (request.cmd === 'READ') {
    sendResponse({ text: readLastAssistant() });
  } else if (request.cmd === 'GET_DEBUG') {
    sendResponse(getDebugInfo());
  } else if (request.cmd === 'PING') {
    sendResponse({ ok: true });
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
