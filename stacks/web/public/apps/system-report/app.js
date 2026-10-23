const state = { doc: null, statusFilter: null, textFilter: "", sortKey: "status", sortAsc: true };
const STATUS_RANK = { error: 0, missing: 1, unreachable: 2, stale: 3, delta: 4, warn: 5, untracked: 6, remote: 7, ok: 8, planned: 9 };

function esc(s) { return String(s ?? "").replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;"); }

function ageMs(iso) {
  const t = Date.parse(iso);
  return Number.isNaN(t) ? null : Date.now() - t;
}
function fmtAge(iso) {
  const ms = ageMs(iso);
  if (ms === null) return "—";
  const m = Math.floor(ms / 60000);
  if (m < 60) return `${m}m`;
  const h = Math.floor(m / 60);
  if (h < 48) return `${h}h${m % 60 ? `${m % 60}m` : ""}`;
  return `${Math.floor(h / 24)}d${h % 24 ? `${h % 24}h` : ""}`;
}
function ageCls(iso) {
  const ms = ageMs(iso);
  if (ms === null) return "";
  if (ms > 48 * 3600e3) return "old";
  if (ms > 24 * 3600e3) return "mid";
  return "";
}
function pill(status) {
  const s = String(status || "?");
  const cls = STATUS_RANK[s] !== undefined ? s : "planned";
  return `<span class="pill ${cls}">${esc(s)}</span>`;
}

function renderSummary() {
  const el = document.getElementById("summary");
  const counts = state.doc?.status_counts || {};
  const order = ["error", "missing", "unreachable", "stale", "delta", "warn", "untracked", "remote", "ok", "planned"];
  const keys = order.concat(Object.keys(counts).filter((x) => !order.includes(x)));
  let html = `<div class="card${state.statusFilter === null ? " active" : ""}" data-s="">
      <div class="value">${state.doc?.node_count ?? "–"}</div><div class="label">all</div></div>`;
  for (const k of keys) {
    if (!(k in counts)) continue;
    const cls = k === "ok" ? "ok" : (["error", "missing", "unreachable"].includes(k) ? "fail" : "warn");
    html += `<div class="card${state.statusFilter === k ? " active" : ""}" data-s="${k}">
      <div class="value ${cls}">${counts[k]}</div><div class="label">${k}</div></div>`;
  }
  el.innerHTML = html;
  el.querySelectorAll(".card").forEach((c) =>
    c.addEventListener("click", () => {
      const s = c.dataset.s || null;
      state.statusFilter = state.statusFilter === s ? null : s;
      renderSummary(); renderNodes();
    }));
}

function renderNodes() {
  const tb = document.getElementById("nodes");
  let nodes = (state.doc?.nodes || []).slice();
  const q = state.textFilter.toLowerCase();
  if (state.statusFilter) nodes = nodes.filter((n) => n.status === state.statusFilter);
  if (q) nodes = nodes.filter((n) =>
    [n.id, n.status, n.layer, n.summary, n.purpose].join(" ").toLowerCase().includes(q));
  const k = state.sortKey, dir = state.sortAsc ? 1 : -1;
  nodes.sort((a, b) => {
    if (k === "status") return dir * ((STATUS_RANK[a.status] ?? 50) - (STATUS_RANK[b.status] ?? 50));
    if (k === "age" || k === "last_run")
      return dir * ((Date.parse(a.last_run) || 0) - (Date.parse(b.last_run) || 0));
    return dir * String(a[k] ?? "").localeCompare(String(b[k] ?? ""));
  });
  tb.innerHTML = nodes.map((n) => `
    <tr>
      <td>${pill(n.status)}</td>
      <td class="node-id" title="${esc(n.purpose || "")}">${esc(n.id)}</td>
      <td class="muted">${esc(n.layer || "")}</td>
      <td class="muted">${esc((n.last_run || "").replace("T", " ").slice(0, 16))}</td>
      <td class="age ${ageCls(n.last_run)}">${fmtAge(n.last_run)}</td>
      <td class="summary">${esc(n.summary || "")}</td>
    </tr>`).join("");
  document.getElementById("shown-hint").textContent =
    `${nodes.length} of ${state.doc?.nodes?.length || 0} nodes` +
    (state.statusFilter ? ` — filtered: ${state.statusFilter}` : "") +
    (state.textFilter ? ` — matching "${state.textFilter}"` : "");
}

function renderFreshness() {
  const el = document.getElementById("freshness");
  const g = state.doc?.generated_at;
  if (!g) { el.textContent = "data age unknown"; el.className = "warn"; return; }
  el.textContent = `generated ${fmtAge(g)} ago`;
  el.id = "freshness";
  el.className = ageCls(g) || "ok";
}

async function load() {
  const meta = document.getElementById("meta");
  try {
    const yml = await fetch("data/system-report.yml", { cache: "no-store" });
    if (yml.ok) {
      state.doc = jsyaml.load(await yml.text());
      meta.textContent = `Registry: ${state.doc.registry || "ssot.reports.yml"} — generated ${state.doc.generated_at || "unknown"}`;
      try {
        const p = await fetch("api/pending", { cache: "no-store" });
        const pb = await p.json();
        const names = Object.keys(pb.pending || {});
        if (names.length)
          meta.textContent += ` — ⟳ ${names.length} update${names.length > 1 ? "s" : ""} pending (${names.join(", ")})`;
      } catch (e) { /* pending view is optional */ }
      renderFreshness(); renderSummary(); renderNodes();
    } else {
      meta.textContent = `summary unavailable: HTTP ${yml.status}`;
    }
  } catch (e) {
    meta.textContent = `summary unavailable: ${e.message}`;
  }

  try {
    const r = await fetch("data/SYSTEM-REPORT.md", { cache: "no-store" });
    if (!r.ok) throw new Error(`HTTP ${r.status}`);
    const md = await r.text();
    document.getElementById("report").innerHTML = typeof marked !== "undefined"
      ? marked.parse(md)
      : `<pre>${md.replace(/</g, "&lt;")}</pre>`;
    // linkify the report's status cells for scannability
    document.querySelectorAll("#report td").forEach((td) => {
      const t = td.textContent.trim().toLowerCase();
      if (STATUS_RANK[t] !== undefined) td.innerHTML = pill(t);
    });
  } catch (e) {
    document.getElementById("report").innerHTML =
      `<p class="err-text">Failed to load report: ${e.message}. Generated daily by chaba-system-report.timer (~06:45).</p>`;
  }
}

// Refresh button -> POST api/refresh starts the report graph walk
// (dirty nodes only). Deep rescan sends force:true — every runnable
// node re-runs, including the L1 audit-hosts/* host scans (slow).
// Poll /status until done.
async function refresh(force) {
  const btn = document.getElementById("refresh");
  const deep = document.getElementById("deep");
  const status = document.getElementById("refresh-status");
  btn.disabled = true;
  if (deep) deep.disabled = true;
  try {
    const r = await fetch("api/refresh", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ node: "system-report", depth: "subtree",
                             ...(force ? { force: true } : {}) }),
    });
    if (r.status === 403) { status.textContent = "refresh needs a tailnet login"; return; }
    if (r.status !== 202 && r.status !== 409) {
      const b = await r.json().catch(() => ({}));
      status.textContent = `refresh failed: ${b.error || "HTTP " + r.status}`;
      return;
    }
    status.textContent = r.status === 409 ? "already running…"
      : force ? "deep rescan — host audits + reports (~10–20 min)…"
              : "generating (~5–10 min)…";
    const deadline = Date.now() + (force ? 30 : 16) * 60 * 1000;
    while (Date.now() < deadline) {
      await new Promise((res) => setTimeout(res, 10000));
      try {
        const s = await fetch("api/status", { cache: "no-store" });
        const b = await s.json();
        if (!b.running) {
          status.textContent = "done — reloading";
          await load();
          status.textContent = "";
          return;
        }
      } catch (e) { /* transient — keep polling */ }
    }
    status.textContent = "still generating — check back shortly";
  } catch (e) {
    status.textContent = `refresh failed: ${e.message}`;
  } finally {
    btn.disabled = false;
    if (deep) deep.disabled = false;
  }
}

document.getElementById("refresh").addEventListener("click", () => refresh(false));
document.getElementById("deep").addEventListener("click", () => refresh(true));
document.getElementById("filter").addEventListener("input", (e) => {
  state.textFilter = e.target.value.trim();
  renderNodes();
});
document.querySelectorAll("table.nodes th").forEach((th) =>
  th.addEventListener("click", () => {
    const k = th.dataset.k;
    if (state.sortKey === k) state.sortAsc = !state.sortAsc;
    else { state.sortKey = k; state.sortAsc = true; }
    renderNodes();
  }));

load();
setInterval(load, 60000); // monitor page — self-refresh the data every minute
