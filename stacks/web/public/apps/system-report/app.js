async function load() {
  const meta = document.getElementById("meta");
  const summary = document.getElementById("summary");
  const report = document.getElementById("report");
  summary.innerHTML = "";

  try {
    const yml = await fetch("data/system-report.yml", { cache: "no-store" });
    if (yml.ok) {
      const doc = jsyaml.load(await yml.text());
      meta.textContent = `Generated: ${doc.generated_at || "unknown"} — ${doc.node_count} nodes`;
      const counts = doc.status_counts || {};
      const order = ["error", "missing", "stale", "delta", "warn", "ok"];
      for (const k of order.concat(Object.keys(counts).filter((x) => !order.includes(x)))) {
        if (!(k in counts)) continue;
        const cls = k === "ok" ? "ok" : (k === "error" || k === "missing" ? "fail" : "warn");
        summary.innerHTML += `<div class="card"><div class="value ${cls}">${counts[k]}</div><div class="label">${k}</div></div>`;
      }
    }
  } catch (e) {
    meta.textContent = `summary unavailable: ${e.message}`;
  }

  try {
    const r = await fetch("data/SYSTEM-REPORT.md", { cache: "no-store" });
    if (!r.ok) throw new Error(`HTTP ${r.status}`);
    const md = await r.text();
    report.innerHTML = typeof marked !== "undefined"
      ? marked.parse(md)
      : `<pre>${md.replace(/</g, "&lt;")}</pre>`;
  } catch (e) {
    report.innerHTML = `<p class="err-text">Failed to load report: ${e.message}. Generated daily by chaba-system-report.timer (~06:45).</p>`;
  }
}

// Refresh button -> POST api/refresh starts the full L1->L3 chain on
// tony-dell (per-host audits, fleet rollup, this report — so the top
// level refreshes every linked layer). Poll /status until the run ends.
async function refresh() {
  const btn = document.getElementById("refresh");
  const status = document.getElementById("refresh-status");
  btn.disabled = true;
  try {
    const r = await fetch("api/refresh", { method: "POST" });
    if (r.status === 403) {
      status.textContent = "refresh needs a tailnet login";
      return;
    }
    if (r.status !== 202 && r.status !== 409) {
      const b = await r.json().catch(() => ({}));
      status.textContent = `refresh failed: ${b.error || "HTTP " + r.status}`;
      return;
    }
    status.textContent = r.status === 409 ? "already running…" : "generating (~5–10 min)…";
    const deadline = Date.now() + 16 * 60 * 1000;
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
  }
}

document.getElementById("refresh").addEventListener("click", refresh);
load();
