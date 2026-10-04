async function load() {
  const meta = document.getElementById("meta");
  const summary = document.getElementById("summary");
  const report = document.getElementById("report");

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

load();
