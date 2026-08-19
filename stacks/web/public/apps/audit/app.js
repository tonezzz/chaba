const SUMMARY_URL = 'data/summary.json';

function formatDuration(ms) {
  return ms != null ? ms.toLocaleString() : '-';
}

async function load() {
  const res = await fetch(SUMMARY_URL);
  if (!res.ok) {
    document.getElementById('summary').innerHTML = `<p class="error">Failed to load ${SUMMARY_URL}: ${res.status}</p>`;
    return;
  }
  const data = await res.json();

  const overallClass = data.ok ? 'pass' : 'fail';
  document.getElementById('summary').innerHTML = `
    <div class="summary">
      <div class="card"><div class="value ${overallClass}">${data.ok ? 'PASS' : 'FAIL'}</div><div class="label">Overall</div></div>
      <div class="card"><div class="value">${data.summary?.passed ?? 0}/${data.summary?.total ?? 0}</div><div class="label">Passed</div></div>
      <div class="card"><div class="value">${data.generated ? new Date(data.generated).toLocaleString() : 'unknown'}</div><div class="label">Generated</div></div>
      <div class="card"><div class="value">${data.ssot || '-'}</div><div class="label">SSOT</div></div>
    </div>
  `;

  const tbody = document.querySelector('#results tbody');
  tbody.innerHTML = '';
  for (const r of data.results || []) {
    const row = document.createElement('tr');
    row.innerHTML = `
      <td>${r.name}</td>
      <td class="${r.ok ? 'pass' : 'fail'}" style="cursor:pointer">${r.ok ? 'PASS' : 'FAIL'}</td>
      <td>${formatDuration(r.duration_ms)}</td>
      <td>${r.exit_code}</td>
    `;
    row.querySelector('td:nth-child(2)').addEventListener('click', () => {
      document.getElementById('detail').textContent = `Command: ${r.command}\n\n${r.stdout || r.stderr || '(no output)'}`;
    });
    tbody.appendChild(row);
  }
}

load().catch(e => {
  document.getElementById('summary').innerHTML = `<p class="error">${e.message}</p>`;
});
