/* GPU Dispatch Web UI — vanilla JS, same-origin /api/* only. */
"use strict";

const $ = (sel) => document.querySelector(sel);
const state = { data: null, timer: null };

function esc(s) {
  return String(s ?? "").replace(/[&<>"']/g, (c) =>
    ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
}

function fmtTime(iso) {
  if (!iso) return "—";
  const d = new Date(iso);
  return isNaN(d) ? String(iso) : d.toLocaleString();
}

function fmtMb(mb) {
  if (mb == null) return "—";
  return mb >= 1024 ? (mb / 1024).toFixed(1) + " GB" : mb + " MB";
}

function toast(msg, ok = true) {
  const el = $("#toast");
  el.textContent = msg;
  el.className = "gd-toast " + (ok ? "ok" : "err");
  el.hidden = false;
  clearTimeout(toast._t);
  toast._t = setTimeout(() => { el.hidden = true; }, 5000);
}

function actor() {
  return $("#actor").value.trim() || "webui";
}

async function api(path, opts) {
  const res = await fetch(path, opts);
  const body = await res.json().catch(() => ({ ok: false, error: "bad response" }));
  if (!res.ok) throw Object.assign(new Error(body.error || res.statusText), { body, status: res.status });
  return body;
}

async function refresh() {
  const conn = $("#conn-status");
  const rs = $("#refresh-status");
  try {
    const body = await api("/api/state");
    state.data = body.state;
    render();
    conn.textContent = "live";
    conn.className = "gd-conn ok";
    rs.textContent = "";
    rs.className = "";
  } catch (e) {
    conn.textContent = "offline: " + e.message;
    conn.className = "gd-conn err";
    rs.textContent = "refresh failed";
    rs.className = "gd-refresh-status err";
  }
  $("#last-updated").textContent = "Last updated: " + new Date().toLocaleTimeString();
}

function render() {
  const s = state.data;
  if (!s) return;
  renderStrip(s);
  renderGpu(s.gpu.hosts, s.queue.stats.reservations || []);
  renderJobs(s.jobs, s.queue.stats, s.queue.fairshare || {});
  renderAudit(s.audit || []);
}

function badge(text, cls) {
  return `<span class="gd-badge ${cls}">${esc(text)}</span>`;
}

function renderStrip(s) {
  const units = s.scheduler || {};
  for (const [key, id] of [["dispatch-scheduler", "sched-scheduler"], ["sidecar-collector", "sched-sidecar"]]) {
    const u = units[key] || {};
    const ok = u.active === "active";
    $("#" + id).innerHTML = badge(
      ok ? `active · pid ${esc(u.pid)}` : (u.active || "unknown"),
      ok ? "ok" : "err");
    $("#" + id).title = `since ${u.since || "?"} · restarts ${u.restarts || "?"}`;
  }
  const st = s.queue.stats || {};
  $("#stat-queued").textContent = st.total_queued ?? 0;
  $("#stat-processing").textContent = st.processing ?? 0;
  $("#stat-completed").textContent = st.completed ?? 0;
  $("#stat-failed").textContent = st.failed ?? 0;
  $("#stat-dlq").textContent = st.dlq ?? (s.queue.dlq || []).length;
  $("#stat-resv").textContent = (st.reservations || []).length;
  const fs = Object.entries(s.queue.fairshare || {})
    .map(([k, v]) => `${k}:${v}`).join("  ");
  $("#fairshare").textContent = fs ? "fairshare " + fs : "";
}

function renderGpu(hosts, holds) {
  const holdMap = {};
  for (const h of holds) holdMap[`${h.host}:${h.gpu_index}`] = h;
  const tb = $("#gpu-table tbody");
  let totalFree = 0, gpuHosts = 0, rows = "";
  for (const h of hosts) {
    const name = h.hostname || h._key.replace("sidecar:", "");
    const tags = Array.isArray(h.tags) ? h.tags.join(",") : String(h.tags || "");
    const sidecar = h.stale
      ? `<span class="gd-stale">stale ${h.metric_age_sec ?? "?"}s</span>`
      : `<span class="gd-dim">${h.metric_age_sec ?? "?"}s ago</span>`;
    const hostCells = (gpuCell) => `
      <td class="gd-jobid">${esc(name)}</td>${gpuCell}
      <td class="num">${pct(h.cpu_pct)}</td>
      <td class="num">${pct(h.mem_pct)}</td>
      <td class="num">${num(h.load1)}</td>
      <td class="num">${pct(h.disk_pct)}</td>
      <td class="gd-dim">${esc(tags)}</td><td>${sidecar}</td>`;
    const gpus = Array.isArray(h.gpus) ? h.gpus : [];
    if (!gpus.length) {
      rows += `<tr>${hostCells(`<td class="gd-dim">(no GPU)</td><td></td><td></td><td></td><td></td><td></td>`)}</tr>`;
      continue;
    }
    gpuHosts++;
    for (const g of gpus) {
      const idx = g.index;
      const hold = holdMap[`${name}:${idx}`];
      const holdCell = hold
        ? `<span class="gd-hold" title="${esc(hold.reservation_id)} until ${fmtTime(hold.expires_at)}">${esc(hold.job_id || "RESERVED")}</span>`
        : `<span class="gd-dim">—</span>`;
      const totalMb = (g.mem_used_mb || 0) + (g.mem_free_mb || 0);
      totalFree += g.mem_free_mb || 0;
      rows += `<tr>${hostCells(`
        <td class="gd-trunc" title="${esc(g.name)}">${esc(g.name)}</td>
        <td class="num">${fmtMb(totalMb)}</td>
        <td class="num">${fmtMb(g.mem_used_mb)}</td>
        <td class="num">${fmtMb(g.mem_free_mb)}</td>
        <td class="num">${num(g.util_pct)}%</td>
        <td class="num">${num(g.temp_c)}°C</td>
        <td>${holdCell}</td>`)}</tr>`;
    }
  }
  tb.innerHTML = rows || `<tr><td colspan="14" class="gd-empty">no sidecar metrics yet</td></tr>`;
  $("#gpu-summary").textContent =
    `${gpuHosts} GPU host(s) · ${fmtMb(totalFree)} free VRAM fleet-wide`;
}

function pct(v) { return v == null ? "—" : Number(v).toFixed(0) + "%"; }
function num(v) { return v == null ? "—" : Number(v); }

function jobHost(job) {
  return (job.dispatch && job.dispatch.host) || job.worker || "—";
}

function renderJobs(jobs, stats, fairshare) {
  const tb = $("#job-table tbody");
  if (!jobs.length) {
    tb.innerHTML = `<tr><td colspan="9" class="gd-empty">queue is empty — enqueue a job below</td></tr>`;
    return;
  }
  const byPri = (stats.by_priority && Object.keys(stats.by_priority).length)
    ? Object.entries(stats.by_priority).sort((a, b) => a[0] - b[0])
        .map(([p, c]) => `p${p}:${c}`).join(" ")
    : "";
  tb.innerHTML = jobs.map((j) => {
    const id = j.job_id || "?";
    const status = j.status || "unknown";
    const tags = Array.isArray(j.job_require_tags) && j.job_require_tags.length
      ? j.job_require_tags.join(",") : "";
    let actions = `<button class="gd-btn gd-btn-sm" data-act="detail" data-id="${esc(id)}">Detail</button>`;
    if (status === "queued" || status === "waiting") {
      actions += ` <button class="gd-btn gd-btn-sm gd-btn-danger" data-act="cancel" data-id="${esc(id)}">Cancel</button>`;
    }
    if (["failed", "dead_letter", "cancelled", "completed"].includes(status)) {
      actions += ` <button class="gd-btn gd-btn-sm" data-act="requeue" data-id="${esc(id)}">Requeue</button>`;
    }
    return `<tr>
      <td class="gd-jobid" title="${esc(tags)}">${esc(id)}</td>
      <td>${badge(status, "st-" + status)}</td>
      <td class="num">${esc(j.priority ?? "?")}</td>
      <td>${esc(j.user || "?")}</td>
      <td class="gd-trunc" title="${esc(j.job_image)}">${esc(j.job_image)}</td>
      <td class="num">${esc(j.job_gpus ?? "?")}</td>
      <td class="gd-dim">${fmtTime(j.created_at)}</td>
      <td class="gd-dim">${esc(jobHost(j))}</td>
      <td><div class="gd-actions">${actions}</div></td>
    </tr>`;
  }).join("");
}

function renderAudit(entries) {
  const tb = $("#audit-table tbody");
  const rows = [...entries].reverse(); // newest first
  tb.innerHTML = rows.length ? rows.map((a) => `<tr>
    <td class="gd-dim">${esc(fmtTime(a.ts))}</td>
    <td>${esc(a.actor)}</td>
    <td>${badge(a.action, a.action === "enqueue" ? "info" : "warn")}</td>
    <td class="gd-jobid">${esc(a.job_id)}</td>
    <td class="gd-dim gd-trunc" title="${esc(JSON.stringify(a.result))}">${esc(JSON.stringify(a.result))}</td>
  </tr>`).join("") : `<tr><td colspan="5" class="gd-empty">no mutations yet</td></tr>`;
}

// ─── Mutations ─────────────────────────────────────────────────────────

async function post(path, payload, confirmText) {
  if (confirmText && !window.confirm(confirmText)) return null;
  const body = await api(path, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ ...payload, confirm: true, actor: actor() }),
  });
  return body;
}

async function jobAction(act, id) {
  try {
    if (act === "cancel") {
      const r = await post(`/api/jobs/${encodeURIComponent(id)}/cancel`, {},
        `Cancel job ${id}?\n\nIt will be removed from the queue and marked cancelled.`);
      if (r === null) return;
      if (r.ok) { toast(`cancelled ${id}`); refresh(); }
      else toast(`${id}: ${r.detail || r.error || "cancel failed"}`, false);
    } else if (act === "requeue") {
      const r = await post(`/api/jobs/${encodeURIComponent(id)}/requeue`, {},
        `Requeue job ${id}?\n\nIt goes back into the queue and the scheduler may dispatch it.`);
      if (r === null) return;
      if (r.ok) { toast(`requeued ${id}`); refresh(); }
      else toast(`${id}: ${r.detail || r.error || "requeue failed"}`, false);
    } else if (act === "detail") {
      const d = await api(`/api/jobs/${encodeURIComponent(id)}`);
      $("#modal-title").textContent = "Job " + id;
      $("#modal-body").textContent = JSON.stringify(d.job, null, 2);
      $("#job-modal").hidden = false;
    }
  } catch (e) {
    toast(`${act} ${id} failed: ${e.message}`, false);
  }
}

function formToJob(fd) {
  const job = {
    job_image: fd.get("job_image").trim(),
    job_cmd: fd.get("job_cmd").trim(),
  };
  const opt = {
    job_id: "job_id", priority: "priority", job_gpus: "job_gpus",
    job_min_vram_gb: "job_min_vram_gb", job_max_load_pct: "job_max_load_pct",
    job_max_mem_pct: "job_max_mem_pct", reserve_gpu_window_sec: "reserve_gpu_window_sec",
    job_timeout_sec: "job_timeout_sec", max_retries: "max_retries",
    target_group: "target_group", user: "user", project: "project",
    container_runtime: "container_runtime",
  };
  for (const [field, name] of Object.entries(opt)) {
    const v = fd.get(name);
    if (v === "" || v == null) continue;
    if (["priority", "job_gpus", "job_min_vram_gb", "job_max_load_pct",
         "job_max_mem_pct", "reserve_gpu_window_sec", "job_timeout_sec",
         "max_retries"].includes(field)) {
      job[field] = parseInt(v, 10);
    } else {
      job[field] = String(v).trim();
    }
  }
  for (const [field, name] of [["job_require_tags", "job_require_tags"], ["job_exclude_tags", "job_exclude_tags"]]) {
    const tags = String(fd.get(name) || "").split(/[\s,]+/).filter(Boolean);
    if (tags.length) job[field] = tags;
  }
  return job;
}

// ─── Wiring ────────────────────────────────────────────────────────────

function init() {
  $("#actor").value = localStorage.getItem("gd-actor") || "";
  $("#actor").addEventListener("change", () =>
    localStorage.setItem("gd-actor", $("#actor").value.trim()));

  $("#btn-refresh").addEventListener("click", refresh);
  $("#auto-refresh").addEventListener("change", schedule);

  $("#job-table tbody").addEventListener("click", (e) => {
    const btn = e.target.closest("button[data-act]");
    if (btn) jobAction(btn.dataset.act, btn.dataset.id);
  });

  $("#modal-close").addEventListener("click", () => { $("#job-modal").hidden = true; });
  $("#job-modal").addEventListener("click", (e) => {
    if (e.target.id === "job-modal") $("#job-modal").hidden = true;
  });

  $("#enqueue-form").addEventListener("submit", async (e) => {
    e.preventDefault();
    const st = $("#enqueue-status");
    const job = formToJob(new FormData(e.target));
    const summary = `Enqueue job as ${actor()}?\n\n` +
      `image: ${job.job_image}\ncmd:   ${job.job_cmd}\n` +
      `gpus: ${job.job_gpus ?? 1}, tags: ${JSON.stringify(job.job_require_tags || [])}, ` +
      `priority: ${job.priority ?? 5}\n\nThe scheduler may dispatch it as soon as it is queued.`;
    st.className = "gd-action-status";
    st.textContent = "confirming…";
    try {
      const r = await post("/api/jobs", { job }, summary);
      if (r === null) { st.textContent = ""; return; }
      if (r.ok) {
        st.textContent = "enqueued " + r.job_id;
        st.className = "gd-action-status ok";
        e.target.reset();
        toast(`enqueued ${r.job_id}`);
        refresh();
      } else {
        st.textContent = r.error || "enqueue failed";
        st.className = "gd-action-status err";
      }
    } catch (err) {
      st.textContent = err.message;
      st.className = "gd-action-status err";
    }
  });

  schedule();
  refresh();
}

function schedule() {
  clearInterval(state.timer);
  if ($("#auto-refresh").checked) {
    state.timer = setInterval(() => { if (!document.hidden) refresh(); }, 5000);
  }
}

document.addEventListener("DOMContentLoaded", init);
