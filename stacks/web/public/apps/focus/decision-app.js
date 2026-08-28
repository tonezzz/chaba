const DATA_URL = 'data/decision-tree.json';

async function load() {
  const res = await fetch(DATA_URL);
  if (!res.ok) {
    document.getElementById('tree').innerHTML = `<p style="color:#ef4444">Failed to load ${DATA_URL}: ${res.status}</p>`;
    return;
  }
  const tree = await res.json();
  const container = document.getElementById('tree');

  for (const step of tree) {
    const div = document.createElement('div');
    div.className = 'step';
    div.innerHTML = `
      <h3>Step ${step.step}: ${step.check}</h3>
      <p>
        <span class="outcome yes">Yes</span> <span class="arrow">→</span> ${step.yes}
      </p>
      <p>
        <span class="outcome no">No</span> <span class="arrow">→</span> ${step.no}
      </p>
    `;
    container.appendChild(div);
  }
}

load().catch(e => {
  document.getElementById('tree').innerHTML = `<p style="color:#ef4444">${e.message}</p>`;
});
