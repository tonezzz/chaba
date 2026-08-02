/**
 * Shared utilities for chaba.h3 apps.
 * Exports a global `ChabaUtils` object for legacy IIFE pages and
 * attaches to `module.exports` for CommonJS consumers.
 */
(function (global) {
  'use strict';

  const entityMap = {
    '&': '&amp;',
    '<': '&lt;',
    '>': '&gt;',
    '"': '&quot;',
    "'": '&#39;'
  };

  function escapeHtml(str) {
    return String(str).replace(/[&<>"']/g, m => entityMap[m]);
  }

  function copyToClipboard(text) {
    if (navigator.clipboard) return navigator.clipboard.writeText(text);
    const ta = document.createElement('textarea');
    ta.value = text;
    document.body.appendChild(ta);
    ta.select();
    document.execCommand('copy');
    document.body.removeChild(ta);
    return Promise.resolve();
  }

  function download(filename, text, type = 'application/octet-stream') {
    const blob = new Blob([text], { type });
    const a = document.createElement('a');
    a.href = URL.createObjectURL(blob);
    a.download = filename;
    a.click();
    URL.revokeObjectURL(a.href);
  }

  function debounce(fn, wait = 300) {
    let t;
    return function (...args) {
      clearTimeout(t);
      t = setTimeout(() => fn.apply(this, args), wait);
    };
  }

  function throttle(fn, wait = 300) {
    let last = 0;
    return function (...args) {
      const now = Date.now();
      if (now - last >= wait) {
        last = now;
        fn.apply(this, args);
      }
    };
  }

  function formatDate(value, options = {}) {
    const d = value instanceof Date ? value : new Date(value);
    if (isNaN(d.getTime())) return '';
    const opts = Object.assign({ dateStyle: 'medium', timeStyle: 'short' }, options);
    return new Intl.DateTimeFormat(navigator.language || 'en-US', opts).format(d);
  }

  const storage = {
    get(key) {
      try { return localStorage.getItem(key); } catch { return null; }
    },
    set(key, value) {
      try { localStorage.setItem(key, value); } catch {}
    },
    remove(key) {
      try { localStorage.removeItem(key); } catch {}
    },
    getJson(key) {
      const raw = this.get(key);
      if (raw == null) return undefined;
      try { return JSON.parse(raw); } catch { return undefined; }
    },
    setJson(key, value) {
      this.set(key, JSON.stringify(value));
    }
  };

  function $(id, root = document) {
    return root.getElementById(id);
  }

  function onReady(fn) {
    if (document.readyState !== 'loading') {
      fn();
    } else {
      document.addEventListener('DOMContentLoaded', fn);
    }
  }

  const utils = {
    escapeHtml,
    copyToClipboard,
    download,
    debounce,
    throttle,
    formatDate,
    storage,
    $,
    onReady
  };

  if (typeof module !== 'undefined' && module.exports) module.exports = utils;
  if (global) global.ChabaUtils = utils;
})(typeof globalThis !== 'undefined' ? globalThis : window);
