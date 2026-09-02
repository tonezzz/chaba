// Michael Live — shared family layer
class MichaelFamilyApp {
    constructor(options = {}) {
        this.options = options;
        this.config = {};
        this.data = {};
        this.container = document.getElementById(options.containerId || 'app');
        this.timer = null;
        this.init();
    }

    async init() {
        try {
            await this.loadConfig();
            this.render();
            await this.loadData();
            this.updateValues();
            this.startPolling();
        } catch (err) {
            console.error('MichaelFamilyApp init failed:', err);
            if (this.container) {
                this.container.innerHTML = `<div class="error">Failed to initialise: ${err.message}</div>`;
            }
        }
    }

    async loadConfig() {
        const [base, page] = await Promise.all([
            this.fetchYaml('ssot.ui.michael-family.yml'),
            this.fetchYaml(this.options.pageConfig || 'ssot.ui.michael-live.yml')
        ]);
        this.config = this.mergeDeep(base, page);
    }

    async fetchYaml(file) {
        const res = await fetch(file + '?v=2');
        if (!res.ok) throw new Error(`${file}: ${res.status}`);
        return jsyaml.load(await res.text()) || {};
    }

    mergeDeep(base, page) {
        if (!this.isObject(base) || !this.isObject(page)) return page;
        const output = { ...base };
        for (const key of Object.keys(page)) {
            if (this.isObject(page[key])) {
                output[key] = this.isObject(base[key]) ? this.mergeDeep(base[key], page[key]) : page[key];
            } else {
                output[key] = page[key];
            }
        }
        return output;
    }

    isObject(item) {
        return item && typeof item === 'object' && !Array.isArray(item) && !(item instanceof Date);
    }

    async loadData() {
        const endpoint = this.config?.live?.endpoint_snapshot || './demo-snapshot.json';
        const status = document.getElementById('connection-status');
        if (status) {
            status.textContent = 'Loading';
            status.classList.remove('live', 'error');
            status.classList.add('loading');
        }
        try {
            const res = await fetch(endpoint);
            if (!res.ok) throw new Error(`${res.status}`);
            this.data = await res.json();
            if (this.data.error) throw new Error(this.data.error);
            this.updateValues();
        } catch (err) {
            console.error('loadData failed:', err);
            if (status) {
                status.textContent = 'Error: ' + err.message;
                status.classList.remove('live', 'loading');
                status.classList.add('error');
            }
        }
    }

    render() {
        if (!this.container) return;
        this.container.innerHTML = this.renderLayout();
    }

    renderLayout() {
        const title = this.config?.page?.title || 'Michael Live';
        return `
            <div class="michael-live">
                <header class="michael-header">
                    <h1>${title}</h1>
                    <span id="connection-status" class="status loading">Loading</span>
                </header>
                <main class="michael-grid">${this.renderPanels()}</main>
                <footer class="michael-footer">${title}</footer>
            </div>
        `;
    }

    renderPanels() {
        const panels = this.config?.live?.panels || ['battery', 'solar', 'power'];
        return panels.map(id => `
            <section class="panel" data-panel="${id}">
                <h2 id="title-${id}">${id}</h2>
                <div class="panel-content" id="panel-${id}">--</div>
            </section>
        `).join('');
    }

    updateValues() {
        const status = document.getElementById('connection-status');
        if (status) {
            status.textContent = 'Live' + (this.data?.updated ? ` · ${new Date(this.data.updated).toLocaleTimeString()}` : '');
            status.classList.remove('loading', 'error');
            status.classList.add('live');
        }
        const panels = this.data?.panels || {};
        for (const [id, value] of Object.entries(panels)) {
            const el = document.getElementById(`panel-${id}`);
            if (el) el.textContent = typeof value === 'object' ? JSON.stringify(value, null, 2) : value;
        }
    }

    startPolling() {
        const interval = this.config?.live?.refresh_interval || 5000;
        this.timer = setInterval(() => this.loadData(), interval);
    }
}
