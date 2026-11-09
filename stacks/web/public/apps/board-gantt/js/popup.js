// popup.js — frappe-gantt popup renderer (click a bar -> card summary).
// The popup option receives ctx; ctx.task is the task object we built,
// which carries _card (raw card id). We resolve details from the card map.

function esc(s) {
  return String(s ?? '').replace(/[&<>"']/g, (ch) =>
    ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[ch]));
}

export function makePopup(cardById) {
  return function popup(ctx) {
    const t = ctx && ctx.task;
    if (!t || !t._card) return false;              // group headers: no popup
    const c = cardById.get(t._card);
    if (!c) return false;
    const lines = [
      `<div class="title">${esc(c.title)}</div>`,
      `<div class="subtitle">${esc(c.id)} · <b>${esc(c.column)}</b>` +
        (c.program ? ` · ${esc(c.program)}` : '') + `</div>`,
    ];
    if (c.brief) lines.push(`<div class="details">${esc(c.brief)}</div>`);
    if (c.firstAt || c.lastAt) {
      lines.push(`<div class="details">${esc(c.firstAt || '?')} → ${esc(c.lastAt || 'today')}</div>`);
    }
    if (c.lastComm && c.lastComm.text) {
      lines.push(`<div class="details">last: ${esc(c.lastComm.from || '?')} — ${esc(c.lastComm.text).slice(0, 140)}</div>`);
    }
    return lines.join('');
  };
}
