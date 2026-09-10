// Shared layer for the apps/ha device-registry mini apps.
class HaDevicesApp {
    constructor(options = {}) {
        this.container = document.getElementById(options.containerId || 'app');
        this.instance = window.HA_INSTANCE || options.instance || 'overview';
        this.tabs = [
            { id: 'tony-ha', label: 'Tony HA' },
            { id: 'michael-ha', label: 'Michael HA' },
            { id: 'michael-dev', label: 'Michael Dev' },
            { id: 'dossier', label: 'DOSSIER' },
        ];
        this.init();
    }

    async init() {
        try {
            if (this.instance === 'dossier') {
                this.renderDossier();
                return;
            }

            const ui = await this.fetchYaml('/apps/ha/ssot.ui.ha.yml');
            if (this.instance === 'overview') {
                this.renderOverview(ui);
            } else {
                const instance = ui?.instances?.[this.instance];
                if (!instance) {
                    throw new Error(`Unknown HA instance: ${this.instance}`);
                }
                this.renderInstance(instance);
            }
        } catch (err) {
            console.error('HaDevicesApp init failed:', err);
            if (this.container) {
                this.container.innerHTML = `<div class="error">Failed to load: ${this.esc(String(err.message))}</div>`;
            }
        }
    }

    async fetchYaml(file) {
        const res = await fetch(file + '?v=1');
        if (!res.ok) throw new Error(`${file}: ${res.status}`);
        return jsyaml.load(await res.text()) || {};
    }

    renderLayout(activeTab, contentHtml) {
        const nav = this.tabs.map(t => {
            const isActive = t.id === activeTab;
            return `<a class="${isActive ? 'active' : ''}" href="/apps/ha/${t.id}/">${this.esc(t.label)}</a>`;
        }).join('');

        this.container.innerHTML = `
            <div class="app">
                <aside class="sidebar">
                    <nav>${nav}</nav>
                </aside>
                <div class="main">${contentHtml}</div>
            </div>
        `;
    }

    renderOverview(ui) {
        document.title = 'Home Assistant Devices';
        const instances = ui?.instances || {};
        const cards = Object.entries(instances).map(([key, inst]) => {
            const count = (inst.devices || []).length;
            return `
                <a href="/apps/ha/${key}/">
                    <strong>${this.esc(inst.title || key)}</strong>
                    <span>${this.esc(inst.description || '')}</span>
                    <span class="muted">${count} device${count === 1 ? '' : 's'}</span>
                </a>
            `;
        }).join('');
        this.container.innerHTML = `
            <header>
                <h1>Home Assistant Devices</h1>
                <p>Per-instance network and device registry views.</p>
            </header>
            <nav class="grid">${cards}</nav>
        `;
    }

    renderInstance(instance) {
        document.title = this.esc(instance.title || this.instance);
        const network = instance.network || {};
        const networkPill = network.cidr
            ? `<span class="network-pill">${this.esc(network.cidr)} · gateway ${this.esc(network.gateway || 'n/a')}</span>`
            : '';

        const rows = (instance.devices || []).map(d => this.renderRow(d)).join('');

        this.renderLayout(this.instance, `
            <header>
                <h1>${this.esc(instance.title || this.instance)}</h1>
                <p>${this.esc(instance.description || '')}</p>
                ${networkPill}
            </header>
            <main>
                <table>
                    <thead>
                        <tr>
                            <th>Label</th>
                            <th>IP</th>
                            <th>MAC</th>
                            <th>Interface</th>
                            <th>Type</th>
                            <th>Source</th>
                            <th>Status</th>
                        </tr>
                    </thead>
                    <tbody>${rows}</tbody>
                </table>
            </main>
        `);
    }

    renderDossier() {
        document.title = 'DOSSIER';
        this.renderLayout('dossier', `
            <header>
                <h1>DOSSIER</h1>
                <p>Central dossier for HA instance notes and reference material.</p>
            </header>
            <main>
                <p class="muted">Dossier content will be added here.</p>
            </main>
        `);
    }

    renderRow(d) {
        return `
            <tr>
                <td>${this.esc(d.label || '')}</td>
                <td>${d.ip ? this.esc(String(d.ip)) : '<span class="muted">n/a</span>'}</td>
                <td>${d.mac ? this.esc(String(d.mac)) : '<span class="muted">n/a</span>'}</td>
                <td>${this.esc(d.interface_id || '')}</td>
                <td>${this.esc(d.type || '')}</td>
                <td>${this.esc(d.source || '')}</td>
                <td><span class="status ${this.statusClass(d.status)}">${this.esc(d.status || 'unknown')}</span></td>
            </tr>
        `;
    }

    statusClass(status) {
        if (!status) return 'unknown';
        if (['active'].includes(status)) return 'active';
        if (['stale'].includes(status)) return 'stale';
        return 'unknown';
    }

    esc(s) {
        return String(s).replace(/[&<>"]/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;'}[c]));
    }
}

document.addEventListener('DOMContentLoaded', () => {
    new HaDevicesApp();
});
