// Tony Live — shared family layer (ha-live WebSocket client)
class TonyFamilyApp {
    constructor(options = {}) {
        this.options = options;
        this.config = {};
        this.container = document.getElementById(options.containerId || 'app');
        this.ws = null;
        this.audioCtx = null;
        this.processor = null;
        this.micStream = null;
        this.isRecording = false;
        this.outputQueue = [];
        this.outputCtx = null;
        this.outputNode = null;
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
        this.bindControls();
    }

    renderLayout() {
        const title = this.config?.page?.title || 'Tony Live';
        return `
            <div class="tony-live">
                <header class="tony-header">
                    <h1>${title}</h1>
                    <span id="connection-status" class="status disconnected">Disconnected</span>
                </header>
                <main class="tony-grid">
                    ${this.renderPanel('camera')}
                    ${this.renderPanel('status')}
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
                <div class="panel-content" id="panel-${id}">
                    <div id="transcript-log" class="transcript-log"></div>
                    <div class="controls">
                        <button id="ptt-btn" class="ptt">Hold to talk</button>
                        <button id="query-btn" class="secondary">Status query</button>
                        <button id="reconnect-btn" class="secondary">Reconnect</button>
                    </div>
                    <div id="audio-status" class="audio-status">Ready</div>
                </div>
            </section>
        `;
    }

    bindControls() {
        const ptt = document.getElementById('ptt-btn');
        if (ptt) {
            ptt.addEventListener('mousedown', () => this.startRecording());
            ptt.addEventListener('mouseup', () => this.stopRecording());
            ptt.addEventListener('mouseleave', () => this.stopRecording());
            ptt.addEventListener('touchstart', (e) => { e.preventDefault(); this.startRecording(); });
            ptt.addEventListener('touchend', (e) => { e.preventDefault(); this.stopRecording(); });
        }
        const query = document.getElementById('query-btn');
        if (query) query.addEventListener('click', () => this.sendSilence());
        const reconnect = document.getElementById('reconnect-btn');
        if (reconnect) reconnect.addEventListener('click', () => this.connect());
    }

    connect() {
        const url = this.config?.live?.websocket;
        if (!url) {
            this.log('No websocket configured', 'error');
            return;
        }
        if (this.ws && (this.ws.readyState === WebSocket.CONNECTING || this.ws.readyState === WebSocket.OPEN)) {
            return;
        }
        this.setStatus('Connecting', 'connecting');
        this.log(`Connecting to ${url}`, 'info');
        try {
            this.ws = new WebSocket(url);
            this.ws.onopen = () => this.setStatus('Connected', 'live');
            this.ws.onmessage = (ev) => this.handleMessage(ev.data);
            this.ws.onclose = () => {
                this.setStatus('Disconnected', 'disconnected');
                this.log('ha-live disconnected', 'error');
            };
            this.ws.onerror = () => {
                this.setStatus('Error', 'error');
                this.log('ha-live WebSocket error', 'error');
            };
        } catch (err) {
            this.log(`connect failed: ${err.message}`, 'error');
        }
    }

    handleMessage(data) {
        if (typeof data !== 'string') {
            this.log(`Received binary audio (${data.byteLength || data.size} bytes)`, 'model');
            return;
        }
        let msg;
        try {
            msg = JSON.parse(data);
        } catch (e) {
            this.log(data, 'model');
            return;
        }
        const type = msg.type;
        if (type === 'status') {
            this.log(`Status: ${msg.message}`, 'info');
        } else if (type === 'text') {
            this.log(msg.text, 'model');
        } else if (type === 'audio') {
            this.handleAudio(msg);
        } else if (type === 'done') {
            this.log(`Done: ${msg.text || ''}`, 'info');
            this.stopPlayback();
        } else if (type === 'error') {
            this.log(`Error: ${msg.message}`, 'error');
            this.stopPlayback();
        } else {
            this.log(JSON.stringify(msg), 'model');
        }
    }

    async startRecording() {
        if (this.isRecording) return;
        if (!navigator.mediaDevices) {
            this.log('Microphone unavailable — use HTTPS or localhost', 'error');
            return;
        }
        this.isRecording = true;
        this.setAudioStatus('Recording...');
        try {
            this.micStream = await navigator.mediaDevices.getUserMedia({
                audio: { sampleRate: 16000, channelCount: 1, echoCancellation: true, noiseSuppression: true }
            });
            this.audioCtx = new AudioContext({ sampleRate: 16000 });
            const source = this.audioCtx.createMediaStreamSource(this.micStream);
            this.processor = this.audioCtx.createScriptProcessor(4096, 1, 1);
            this.processor.onaudioprocess = (e) => {
                if (!this.isRecording || !this.ws || this.ws.readyState !== WebSocket.OPEN) return;
                const floats = e.inputBuffer.getChannelData(0);
                const pcm = this.floatToInt16(floats);
                this.ws.send(pcm);
                e.outputBuffer.getChannelData(0).fill(0);
            };
            source.connect(this.processor);
            this.processor.connect(this.audioCtx.destination);
        } catch (err) {
            this.isRecording = false;
            this.setAudioStatus('Mic error');
            this.log(`Mic error: ${err.message}`, 'error');
        }
    }

    stopRecording() {
        if (!this.isRecording) return;
        this.isRecording = false;
        this.setAudioStatus('Processing...');
        if (this.processor) { try { this.processor.disconnect(); } catch (e) {} this.processor = null; }
        if (this.micStream) { this.micStream.getTracks().forEach(t => t.stop()); this.micStream = null; }
        if (this.audioCtx) { this.audioCtx.close(); this.audioCtx = null; }
        if (this.ws && this.ws.readyState === WebSocket.OPEN) {
            this.ws.send(JSON.stringify({ type: 'end' }));
        }
    }

    sendSilence() {
        if (!this.ws || this.ws.readyState !== WebSocket.OPEN) {
            this.log('Not connected', 'error');
            return;
        }
        this.setAudioStatus('Sending status query...');
        const samples = new Int16Array(16000);
        this.ws.send(samples);
        this.ws.send(JSON.stringify({ type: 'end' }));
    }

    handleAudio(msg) {
        const rate = this.parsePcmRate(msg.mime_type) || 24000;
        try {
            const pcm = this.base64ToInt16(msg.data);
            const floats = this.int16ToFloat(pcm);
            this.outputQueue.push(floats);
            if (!this.outputCtx) this.startPlayback(rate);
            this.log(`Audio: ${pcm.length} samples @ ${rate}Hz`, 'model');
        } catch (err) {
            this.log(`Audio decode error: ${err.message}`, 'error');
        }
    }

    startPlayback(sampleRate = 24000) {
        if (this.outputCtx) return;
        this.outputCtx = new AudioContext({ sampleRate });
        this.outputNode = this.outputCtx.createScriptProcessor(4096, 0, 1);
        this.outputNode.onaudioprocess = (e) => {
            const out = e.outputBuffer.getChannelData(0);
            let written = 0;
            while (written < out.length && this.outputQueue.length) {
                const chunk = this.outputQueue[0];
                const take = Math.min(chunk.length, out.length - written);
                out.set(chunk.subarray(0, take), written);
                if (take === chunk.length) {
                    this.outputQueue.shift();
                } else {
                    this.outputQueue[0] = chunk.subarray(take);
                }
                written += take;
            }
            if (written < out.length) out.fill(0, written);
        };
        this.outputNode.connect(this.outputCtx.destination);
    }

    stopPlayback() {
        if (this.outputNode) { try { this.outputNode.disconnect(); } catch (e) {} this.outputNode = null; }
        if (this.outputCtx) { this.outputCtx.close(); this.outputCtx = null; }
        this.outputQueue = [];
    }

    parsePcmRate(mime) {
        if (!mime) return null;
        const m = mime.match(/rate=(\d+)/);
        return m ? parseInt(m[1], 10) : null;
    }

    floatToInt16(floats) {
        const out = new Int16Array(floats.length);
        for (let i = 0; i < floats.length; i++) {
            const s = Math.max(-1, Math.min(1, floats[i]));
            out[i] = s < 0 ? Math.round(s * 0x8000) : Math.round(s * 0x7FFF);
        }
        return out;
    }

    int16ToFloat(int16) {
        const out = new Float32Array(int16.length);
        for (let i = 0; i < int16.length; i++) {
            out[i] = int16[i] / 0x7FFF;
        }
        return out;
    }

    base64ToInt16(b64) {
        const bin = atob(b64);
        const out = new Int16Array(bin.length / 2);
        const view = new DataView(new ArrayBuffer(bin.length));
        for (let i = 0; i < bin.length; i++) view.setUint8(i, bin.charCodeAt(i));
        for (let i = 0; i < out.length; i++) out[i] = view.getInt16(i * 2, true);
        return out;
    }

    setStatus(text, cls) {
        const el = document.getElementById('connection-status');
        if (!el) return;
        el.textContent = text;
        el.className = 'status ' + cls;
    }

    setAudioStatus(text) {
        const el = document.getElementById('audio-status');
        if (el) el.textContent = text;
    }

    log(text, cls = 'model') {
        const el = document.getElementById('transcript-log');
        if (!el) return;
        const line = document.createElement('div');
        line.className = 'log-entry ' + cls;
        line.innerHTML = `<span class="ts">[${new Date().toLocaleTimeString()}]</span> ${this.esc(String(text))}`;
        el.appendChild(line);
        el.scrollTop = el.scrollHeight;
    }

    esc(s) {
        return s.replace(/[&<>"]/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;'}[c]));
    }
}
