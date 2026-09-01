// Tony Live — shared family layer
class TonyFamilyApp {
    constructor(options = {}) {
        this.options = options;
        this.config = {};
        this.container = document.getElementById(options.containerId || 'app');
        this.ws = null;
        this.init();
    }

    async init() {
        try {
            await this.loadConfig();
            this.render();
            this.connect();
        } catch (err) {
            console.error('TonyFamilyApp init failed:', err);
            if (this.container) {
                this.container.innerHTML = `<div class="error">Failed to initialise: ${err.message}</div>`;
            }
        }
    }

    async loadConfig() {
        const [base, page] = await Promise.all([
            this.fetchYaml('ssot.ui.tony-family.yml'),
            this.fetchYaml(this.options.pageConfig || 'ssot.ui.tony-live.yml')
        ]);
        this.config = { ...base, ...page };
    }

    async fetchYaml(file) {
        const res = await fetch(file + '?v=1');
        if (!res.ok) throw new Error(`${file}: ${res.status}`);
        return jsyaml.load(await res.text()) || {};
    }

    render() {
        if (!this.container) return;
        this.container.innerHTML = this.renderLayout();
    }

    renderLayout() {
        const title = this.config?.page?.title || 'Tony Live';
        const panels = this.config?.live?.panels || ['status', 'camera'];
        return `
            <div class="tony-live">
                <header class="tony-header">
                    <h1>${title}</h1>
                    <span id="connection-status" class="status disconnected">Disconnected</span>
                </header>
                <main class="tony-grid">
                    ${panels.map(id => this.renderPanel(id)).join('')}
                </main>
                <footer class="tony-footer">${title}</footer>
            </div>
        `;
    }

    renderPanel(id) {
        if (id === 'camera') {
            const cam = this.config?.live?.camera || {};
            return `
                <section class="panel" data-panel="camera">
                    <h2>${cam.name || 'Camera'}</h2>
                    <div class="panel-content" id="panel-camera">
                        <img src="${cam.thumbnail || ''}" alt="camera" class="cam-thumb" loading="lazy" onerror="this.style.display='none'">
                        <a href="${cam.player || '#'}" target="_blank" class="cam-link">Open HD stream</a>
                    </div>
                </section>
            `;
        }
        return `
            <section class="panel" data-panel="${id}">
                <h2 id="title-${id}">${id}</h2>
                <div class="panel-content" id="panel-${id}">--</div>
            </section>
        `;
    }

    connect() {
        const url = this.config?.live?.websocket;
        if (!url) {
            this.log('No websocket configured');
            return;
        }
        this.log(`Connecting to ${url}...`);
        try {
            this.ws = new WebSocket(url);
            this.ws.onopen = () => {
                this.setStatus('Connected', 'live');
                this.log('ha-live connected');
            };
            this.ws.onmessage = (ev) => {
                this.log('message: ' + ev.data);
            };
            this.ws.onclose = () => {
                this.setStatus('Disconnected', 'disconnected');
                this.log('ha-live disconnected');
            };
            this.ws.onerror = () => {
                this.setStatus('Error', 'error');
                this.log('ha-live error');
            };
        } catch (err) {
            this.log(`connect failed: ${err.message}`);
        }
    }

    setStatus(text, cls) {
        const el = document.getElementById('connection-status');
        if (!el) return;
        el.textContent = text;
        el.className = 'status ' + cls;
    }

    log(msg) {
        const el = document.getElementById('panel-status');
        if (!el) return;
        const line = document.createElement('div');
        line.textContent = `[${new Date().toLocaleTimeString()}] ${msg}`;
        el.appendChild(line);
        el.scrollTop = el.scrollHeight;
    }
}
