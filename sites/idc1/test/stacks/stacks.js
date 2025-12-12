async function loadStacks() {
  try {
    const res = await fetch('./stacks.json', { cache: 'no-cache' });
    if (!res.ok) {
      throw new Error(`Failed to load manifest (${res.status})`);
    }
    const data = await res.json();
    const container = document.getElementById('stackCards');
    container.innerHTML = '';

    data.services.forEach((svc) => {
      const card = document.createElement('article');
      card.className = 'stack-card';
      card.innerHTML = `
        <h2>
          <span>${svc.label}</span>
          <code>${svc.composeService}</code>
        </h2>
        <p class="tagline">${svc.role}</p>
        <dl>
          <dt>Port</dt>
          <dd>${svc.port}</dd>
          <dt>Endpoint</dt>
          <dd><a href="${svc.endpoint}" target="_blank" rel="noreferrer">${svc.endpoint}</a></dd>
          <dt>Health</dt>
          <dd><a href="${svc.health}" target="_blank" rel="noreferrer">${svc.health}</a></dd>
        </dl>
        <p class="notes">${svc.notes || ''}</p>
      `;
      container.appendChild(card);
    });
  } catch (err) {
    console.error(err);
    const container = document.getElementById('stackCards');
    container.innerHTML = `<div class="stack-card"><p class="notes">Unable to load stack manifest. Check console/logs.</p></div>`;
  }
}

loadStacks();
