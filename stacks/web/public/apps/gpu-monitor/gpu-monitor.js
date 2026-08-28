// GPU Monitor - Real-time GPU status and monitoring
class GPUMonitor {
  constructor() {
    this.autoRefresh = true;
    this.refreshInterval = 5000; // 5 seconds
    this.refreshTimer = null;
    this.init();
  }

  init() {
    this.bindEvents();
    this.refresh();
  }

  bindEvents() {
    // Auto-refresh checkbox
    document.getElementById('auto-refresh').addEventListener('change', (e) => {
      this.autoRefresh = e.target.checked;
      if (this.autoRefresh) {
        this.startAutoRefresh();
      } else {
        this.stopAutoRefresh();
      }
    });

    // Refresh button
    document.getElementById('btn-refresh').addEventListener('click', () => {
      this.refresh();
    });

    // Hold llama button
    document.getElementById('btn-hold-llama').addEventListener('click', () => {
      this.holdLlama();
    });

    // Resume llama button
    document.getElementById('btn-resume-llama').addEventListener('click', () => {
      this.resumeLlama();
    });
  }

  startAutoRefresh() {
    if (this.refreshTimer) {
      clearInterval(this.refreshTimer);
    }
    this.refreshTimer = setInterval(() => this.refresh(), this.refreshInterval);
  }

  stopAutoRefresh() {
    if (this.refreshTimer) {
      clearInterval(this.refreshTimer);
      this.refreshTimer = null;
    }
  }

  async refresh() {
    const refreshStatus = document.getElementById('refresh-status');
    refreshStatus.textContent = 'Refreshing...';
    refreshStatus.className = 'gpu-refresh-status refreshing';

    try {
      // Fetch GPU status, queue status in parallel
      const [gpuData, queueData] = await Promise.all([
        this.fetchGPUStatus(),
        this.fetchQueueStatus()
      ]);

      this.updateGPUOverview(gpuData);
      this.updateVRAMUsage(gpuData);
      this.updateGPUProcesses(gpuData);
      this.updateQueueStatus(queueData);
      this.updateBackgroundProcessing();

      // Update last updated time
      const now = new Date();
      document.getElementById('last-updated').textContent = 
        `Last updated: ${now.toLocaleTimeString()}`;

      refreshStatus.textContent = '';
      refreshStatus.className = 'gpu-refresh-status';

      // Start auto-refresh if enabled and not already running
      if (this.autoRefresh && !this.refreshTimer) {
        this.startAutoRefresh();
      }
    } catch (error) {
      console.error('Error refreshing GPU data:', error);
      refreshStatus.textContent = 'Error refreshing data';
      refreshStatus.className = 'gpu-refresh-status error';
    }
  }

  async fetchGPUStatus() {
    // Fetch GPU status from status-api
    const response = await fetch('/api/gpu/status');
    if (!response.ok) {
      throw new Error('Failed to fetch GPU status');
    }
    return await response.json();
  }

  async fetchQueueStatus() {
    const response = await fetch('/api/gpu-queue/status');
    if (!response.ok) {
      throw new Error('Failed to fetch queue status');
    }
    return await response.json();
  }

  updateGPUOverview(data) {
    const container = document.getElementById('gpu-overview');
    
    if (!data || !data.gpus || data.gpus.length === 0) {
      container.innerHTML = '<div class="gpu-loading">No GPU data available</div>';
      return;
    }

    const gpu = data.gpus[0];
    const vramPercent = ((gpu.memory_used_mb / gpu.memory_total_mb) * 100).toFixed(1);

    container.innerHTML = `
      <div class="gpu-stat">
        <div class="gpu-stat-label">GPU Name</div>
        <div class="gpu-stat-value">${gpu.name}</div>
      </div>
      <div class="gpu-stat">
        <div class="gpu-stat-label">Total VRAM</div>
        <div class="gpu-stat-value">${gpu.memory_total_mb} MB</div>
      </div>
      <div class="gpu-stat">
        <div class="gpu-stat-label">VRAM Used</div>
        <div class="gpu-stat-value highlight">${gpu.memory_used_mb} MB</div>
      </div>
      <div class="gpu-stat">
        <div class="gpu-stat-label">VRAM Free</div>
        <div class="gpu-stat-value">${gpu.memory_free_mb} MB</div>
      </div>
      <div class="gpu-stat">
        <div class="gpu-stat-label">Usage</div>
        <div class="gpu-stat-value highlight">${vramPercent}%</div>
      </div>
      <div class="gpu-stat">
        <div class="gpu-stat-label">Processes</div>
        <div class="gpu-stat-value">${data.processes ? data.processes.length : 0}</div>
      </div>
    `;
  }

  updateVRAMUsage(data) {
    const container = document.getElementById('vram-usage');
    
    if (!data || !data.gpus || data.gpus.length === 0) {
      container.innerHTML = '<div class="gpu-loading">No VRAM data available</div>';
      return;
    }

    const gpu = data.gpus[0];
    const vramPercent = ((gpu.memory_used_mb / gpu.memory_total_mb) * 100).toFixed(1);
    const isWarning = vramPercent > 80;

    container.innerHTML = `
      <div class="gpu-vram-bar">
        <div class="gpu-vram-fill ${isWarning ? 'warning' : ''}" style="width: ${vramPercent}%">
          ${vramPercent}%
        </div>
      </div>
      <div class="gpu-vram-details">
        <span>Used: ${gpu.memory_used_mb} MB</span>
        <span>Free: ${gpu.memory_free_mb} MB</span>
        <span>Total: ${gpu.memory_total_mb} MB</span>
      </div>
    `;
  }

  updateGPUProcesses(data) {
    const container = document.getElementById('gpu-processes');
    
    if (!data || !data.processes || data.processes.length === 0) {
      container.innerHTML = '<div class="gpu-loading">No GPU processes running</div>';
      return;
    }

    const processList = data.processes.map(proc => `
      <div class="gpu-process-item">
        <div>
          <span class="gpu-process-pid">PID: ${proc.pid}</span>
          <span class="gpu-process-name">${this.truncatePath(proc.name)}</span>
        </div>
        <span class="gpu-process-memory">${proc.memory_used_mb} MB</span>
      </div>
    `).join('');

    container.innerHTML = `<div class="gpu-process-list">${processList}</div>`;
  }

  updateQueueStatus(data) {
    const container = document.getElementById('gpu-queue');
    
    if (!data) {
      container.innerHTML = '<div class="gpu-loading">No queue data available</div>';
      return;
    }

    const { runningJob, pendingJobs } = data;
    
    let statusHTML = '';
    if (runningJob) {
      statusHTML = `
        <div class="gpu-queue-status">
          <span class="gpu-queue-badge running">Running</span>
          <span>${runningJob.type} job #${runningJob.id}</span>
        </div>
        <div class="gpu-queue-job">
          <span class="gpu-queue-job-type">${runningJob.type}</span>
          <span class="gpu-queue-job-meta">Started: ${new Date(runningJob.started_at).toLocaleTimeString()}</span>
        </div>
      `;
    } else {
      statusHTML = `
        <div class="gpu-queue-status">
          <span class="gpu-queue-badge idle">Idle</span>
          <span>No running job</span>
        </div>
      `;
    }

    if (pendingJobs && pendingJobs.length > 0) {
      statusHTML += `
        <div style="margin-top: 0.75rem; font-size: 0.875rem; color: var(--gpu-text-secondary);">
          ${pendingJobs.length} job(s) queued
        </div>
      `;
    }

    container.innerHTML = statusHTML;
  }

  async updateBackgroundProcessing() {
    const container = document.getElementById('background-processing');
    if (!container) return;

    try {
      const response = await fetch('/api/yomi/activity-status');
      if (!response.ok) {
        throw new Error('Failed to fetch processing status');
      }
      const data = await response.json();
      const processStatus = data.processStatus || {};

      let statusHTML = '';
      
      if (processStatus.status === 'idle' || !processStatus.status) {
        statusHTML = `
          <div class="gpu-processing-status">
            <span class="gpu-processing-badge idle">Idle</span>
            <span>No background processing</span>
          </div>
        `;
      } else if (processStatus.status === 'processing') {
        statusHTML = `
          <div class="gpu-processing-status">
            <span class="gpu-processing-badge active">Processing</span>
            <span>Conversation: ${processStatus.currentChat?.substring(0, 12)}...</span>
          </div>
        `;
      } else if (processStatus.status === 'processing_batch') {
        const progress = processStatus.completed && processStatus.total 
          ? Math.round((processStatus.completed / processStatus.total) * 100) 
          : 0;
        statusHTML = `
          <div class="gpu-processing-status">
            <span class="gpu-processing-badge active">Batch Processing</span>
            <span>Batch ${processStatus.batch}/${processStatus.totalBatches}</span>
          </div>
          <div class="gpu-processing-progress">
            <div class="gpu-processing-progress-bar">
              <div class="gpu-processing-progress-fill" style="width: ${progress}%"></div>
            </div>
            <div class="gpu-processing-progress-text">
              ${processStatus.completed}/${processStatus.total} conversations (${progress}%)
            </div>
          </div>
        `;
      } else if (processStatus.status === 'complete') {
        statusHTML = `
          <div class="gpu-processing-status">
            <span class="gpu-processing-badge success">Complete</span>
            <span>Processed ${processStatus.successCount}/${processStatus.total} conversations</span>
          </div>
          <div class="gpu-processing-meta">
            <span>Avg quality: ${processStatus.avgQuality}/100</span>
          </div>
        `;
      } else {
        statusHTML = `
          <div class="gpu-processing-status">
            <span class="gpu-processing-badge unknown">Unknown</span>
            <span>Status: ${processStatus.status}</span>
          </div>
        `;
      }

      // Add timestamp
      if (processStatus.timestamp) {
        const timeAgo = this.formatTimeAgo(new Date(processStatus.timestamp));
        statusHTML += `
          <div class="gpu-processing-meta">
            <span>Last updated: ${timeAgo}</span>
          </div>
        `;
      }

      container.innerHTML = statusHTML;
    } catch (error) {
      console.error('Error fetching processing status:', error);
      container.innerHTML = '<div class="gpu-loading">Error loading processing status</div>';
    }
  }

  formatTimeAgo(date) {
    const seconds = Math.floor((new Date() - date) / 1000);
    if (seconds < 60) return `${seconds}s ago`;
    if (seconds < 3600) return `${Math.floor(seconds / 60)}m ago`;
    return `${Math.floor(seconds / 3600)}h ago`;
  }

  async holdLlama() {
    const statusEl = document.getElementById('action-status');
    statusEl.textContent = 'Holding llama...';
    statusEl.className = 'gpu-action-status info';

    try {
      const response = await fetch('/api/gpu/hold-llama', { method: 'POST' });
      const result = await response.json();
      
      if (result.success) {
        statusEl.textContent = result.message;
        statusEl.className = 'gpu-action-status success';
        setTimeout(() => this.refresh(), 1000);
      } else {
        statusEl.textContent = result.message || 'Failed to hold llama';
        statusEl.className = 'gpu-action-status error';
      }
    } catch (error) {
      console.error('Error holding llama:', error);
      statusEl.textContent = 'Error holding llama: ' + error.message;
      statusEl.className = 'gpu-action-status error';
    }
  }

  async resumeLlama() {
    const statusEl = document.getElementById('action-status');
    statusEl.textContent = 'Resuming llama...';
    statusEl.className = 'gpu-action-status info';

    try {
      const response = await fetch('/api/gpu/resume-llama', { method: 'POST' });
      const result = await response.json();
      
      if (result.success) {
        statusEl.textContent = result.message;
        statusEl.className = 'gpu-action-status success';
        setTimeout(() => this.refresh(), 1000);
      } else {
        statusEl.textContent = result.message || 'Failed to resume llama';
        statusEl.className = 'gpu-action-status error';
      }
    } catch (error) {
      console.error('Error resuming llama:', error);
      statusEl.textContent = 'Error resuming llama: ' + error.message;
      statusEl.className = 'gpu-action-status error';
    }
  }

  truncatePath(path) {
    if (!path) return 'Unknown';
    if (path.length > 40) {
      return '...' + path.slice(-37);
    }
    return path;
  }
}

// Initialize on DOM ready
document.addEventListener('DOMContentLoaded', () => {
  new GPUMonitor();
});
