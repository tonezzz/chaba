class HealthCheckDashboard {
  constructor() {
    this.config = null;
    this.services = [];
    this.recoveryActions = {};
    this.autoRefreshInterval = null;
    this.currentFilter = 'all';
    this.location = 'auto'; // auto, home, mobile
    this.configs = {
      home: '/ssot.health.home.yml',
      mobile: '/ssot.health.mobile.yml'
    };
    this.detectedLocation = null;
    this.init();
  }

  async init() {
    this.bindEvents();
    await this.loadConfig();
    await this.runHealthChecks();
    this.startAutoRefresh();

    // Ensure location selector is updated after everything is loaded
    setTimeout(() => {
      const location = this.location === 'auto' ? this.detectedLocation : this.location;
      this.updateLocationSelector(location);
    }, 100);

    // Check if Yomi tab is active on load
    const yomiTab = document.querySelector('.health-tab[data-tab="yomi"]');
    if (yomiTab && yomiTab.classList.contains('health-tab-active')) {
      this.checkYomiStatus();
    }
  }

  bindEvents() {
    document.getElementById('btn-refresh').addEventListener('click', () => this.runHealthChecks());
    document.getElementById('auto-refresh').addEventListener('change', (e) => {
      if (e.target.checked) {
        this.startAutoRefresh();
      } else {
        this.stopAutoRefresh();
      }
    });
    document.getElementById('category-filter').addEventListener('change', (e) => {
      this.currentFilter = e.target.value;
      this.renderServices();
    });
    
    // Location selector
    const locationSelector = document.getElementById('location-selector');
    if (locationSelector) {
      locationSelector.addEventListener('change', (e) => {
        this.location = e.target.value;
        this.loadConfig();
      });
    }

    // Tab switching
    const tabs = document.querySelectorAll('.health-tab');
    tabs.forEach(tab => {
      tab.addEventListener('click', () => {
        const tabName = tab.dataset.tab;
        this.switchTab(tabName);
      });
    });
  }

  switchTab(tabName) {
    // Update tab buttons
    document.querySelectorAll('.health-tab').forEach(tab => {
      tab.classList.remove('health-tab-active');
      if (tab.dataset.tab === tabName) {
        tab.classList.add('health-tab-active');
      }
    });

    // Update tab content
    document.querySelectorAll('.health-tab-content').forEach(content => {
      content.classList.remove('health-tab-active');
      if (content.id === `tab-${tabName}`) {
        content.classList.add('health-tab-active');
      }
    });

    // Load Yomi status when switching to Yomi tab
    if (tabName === 'yomi') {
      this.checkYomiStatus();
    }

    // Load GPU status when switching to GPU tab
    if (tabName === 'gpu') {
      this.checkGPUStatus();
    }
  }

  async detectLocation() {
    // Try to reach local endpoints to determine location
    // Use relative URLs since we're on the same domain
    const homeEndpoints = [
      '/api/health'
    ];

    for (const endpoint of homeEndpoints) {
      try {
        const response = await fetch(endpoint);
        if (response.ok) {
          this.detectedLocation = 'home';
          return 'home';
        }
      } catch (error) {
        // Try next endpoint
        continue;
      }
    }

    // If no home endpoint reachable, assume mobile
    this.detectedLocation = 'mobile';
    return 'mobile';
  }

  async loadConfig() {
    try {
      let location = this.location;

      if (location === 'auto') {
        location = await this.detectLocation();
      }

      const configFile = this.configs[location] || this.configs.home;

      const response = await fetch(configFile);
      if (!response.ok) {
        throw new Error(`HTTP ${response.status}: ${response.statusText}`);
      }

      const yamlText = await response.text();
      this.config = jsyaml.load(yamlText);
      this.services = this.config.services || [];
      this.recoveryActions = this.config.recovery_actions || {};

      // Update location selector
      this.updateLocationSelector(location);

    } catch (error) {
      console.error('Failed to load health config:', error);
      this.showError(`Failed to load health configuration: ${error.message}`);
    }
  }

  updateLocationSelector(location) {
    // Retry if elements aren't ready yet
    const update = () => {
      const selector = document.getElementById('location-selector');
      if (selector) {
        // Keep selector at current location setting
        selector.value = this.location;

        // Update status indicator
        const statusIndicator = document.getElementById('location-status');
        if (statusIndicator) {
          const detectedText = this.location === 'auto' && this.detectedLocation ? ` (${this.detectedLocation})` : '';
          statusIndicator.textContent = `Using: ${location}${detectedText}`;
          statusIndicator.className = `location-status location-${location}`;
        }
      } else {
        setTimeout(update, 100);
      }
    };
    update();
  }

  async runHealthChecks() {
    this.setRefreshStatus('refreshing');
    const results = await Promise.all(
      this.services.map(service => this.checkService(service))
    );
    
    this.services = this.services.map((service, index) => ({
      ...service,
      status: results[index]
    }));

    this.renderOverallStatus();
    this.renderServices();
    this.renderRecoveryActions();
    this.updateLastUpdated();
    this.setRefreshStatus('success');
  }

  async checkYomiStatus() {
    const container = document.getElementById('yomi-status');
    container.innerHTML = '<div class="health-loading">Checking Yomi status...</div>';

    try {
      // Check Yomi API health endpoint
      const response = await fetch('/api/yomi/health');
      const apiHealth = await response.json();

      // Get last updated timestamp
      const lastUpdatedResponse = await fetch('/api/yomi/last-updated');
      const lastUpdatedData = await lastUpdatedResponse.json();

      // Get conversation count
      const conversationsResponse = await fetch('/api/yomi/conversations');
      const conversationsData = await conversationsResponse.json();

      // Get summarization status
      const summarizationResponse = await fetch('/api/yomi/summarization-status');
      const summarizationData = await summarizationResponse.json();

      // Get activity status
      const activityResponse = await fetch('/api/yomi/activity-status');
      const activityData = await activityResponse.json();

      const status = {
        api: apiHealth.ok ? 'healthy' : 'unhealthy',
        lastUpdated: lastUpdatedData.lastUpdated,
        conversationCount: conversationsData.conversations?.length || 0,
        generatedAt: conversationsData.generatedAt,
        summarization: summarizationData,
        activity: activityData
      };

      this.renderYomiStatus(status);
    } catch (error) {
      container.innerHTML = `
        <div class="health-yomi-error">
          <div class="health-yomi-status unhealthy">Disconnected</div>
          <div class="health-yomi-message">Unable to connect to Yomi API: ${error.message}</div>
          <div class="health-yomi-note">Yomi may not be running or MCP server is not connected</div>
        </div>
      `;
    }
  }

  async checkGPUStatus() {
    const container = document.getElementById('gpu-status');
    container.innerHTML = '<div class="health-loading">Checking GPU status...</div>';

    try {
      // Get GPU status from status-api
      const gpuResponse = await fetch('/api/gpu/status');
      const gpuData = await gpuResponse.json();

      // Get GPU queue status
      const queueResponse = await fetch('/api/gpu-queue/status');
      const queueData = await queueResponse.json();

      // Get GPU service health
      const [imagen2Health, thaiLegalHealth, txt2vidHealth] = await Promise.all([
        fetch('http://tony-omen.local:8000/health').then(r => r.json()).catch(() => ({ status: 'error' })),
        fetch('http://tony-omen.local:8001/health').then(r => r.json()).catch(() => ({ status: 'error' })),
        fetch('http://tony-omen.local:8002/health').then(r => r.json()).catch(() => ({ status: 'error' }))
      ]);

      const status = {
        gpu: gpuData,
        queue: queueData,
        services: {
          imagen2: imagen2Health,
          thaiLegal: thaiLegalHealth,
          txt2vid: txt2vidHealth
        }
      };

      this.renderGPUStatus(status);
    } catch (error) {
      container.innerHTML = `
        <div class="health-gpu-error">
          <div class="health-gpu-status unhealthy">Error</div>
          <div class="health-gpu-message">Unable to connect to GPU APIs: ${error.message}</div>
          <div class="health-gpu-note">GPU services may not be running</div>
        </div>
      `;
    }
  }

  renderYomiStatus(status) {
    const container = document.getElementById('yomi-status');
    const lastUpdated = status.lastUpdated ? new Date(status.lastUpdated).toLocaleString() : 'Never';
    const timeSinceUpdate = status.lastUpdated 
      ? this.formatTimeSince(new Date(status.lastUpdated)) 
      : 'Unknown';

    const sum = status.summarization || {};
    const summaryCoverage = sum.conversations?.total > 0 
      ? Math.round((sum.conversations?.withMeaningfulSummary / sum.conversations?.total) * 100) 
      : 0;
    const categoryCoverage = sum.conversations?.total > 0 
      ? Math.round((sum.conversations?.withCategory / sum.conversations?.total) * 100) 
      : 0;
    const avgQuality = sum.conversations?.avgSummaryQuality || 0;

    const activity = status.activity || {};
    const process = activity.process || {};
    const metrics = activity.metrics || {};
    const recentActivity = activity.recentActivity || [];
    const processStatus = activity.processStatus || {};

    // Check if initial render or error state
    const isInitialRender = container.innerHTML.includes('health-loading') || 
                           container.innerHTML.includes('health-yomi-error');

    if (isInitialRender) {
      container.innerHTML = `
        <div class="health-yomi-overview">
          <div class="health-yomi-stat">
            <div class="health-yomi-status ${status.api}" data-field="api-status">${status.api === 'healthy' ? 'Connected' : 'Disconnected'}</div>
            <div class="health-yomi-label">API Status</div>
          </div>
          <div class="health-yomi-stat">
            <div class="health-yomi-value" data-field="conversation-count">${status.conversationCount}</div>
            <div class="health-yomi-label">Conversations</div>
          </div>
          <div class="health-yomi-stat">
            <div class="health-yomi-value" data-field="time-since">${timeSinceUpdate}</div>
            <div class="health-yomi-label">Last Update</div>
          </div>
        </div>
        
        <div class="health-yomi-section">
          <h3 class="health-yomi-section-title">Current Activity</h3>
          <div class="health-yomi-activity">
            <div class="health-yomi-activity-status">
              <div class="health-yomi-activity-indicator ${processStatus.status === 'processing' || processStatus.status === 'processing_batch' ? 'busy' : 'active'}"></div>
              <div class="health-yomi-activity-text">${this.getProcessStatusText(processStatus)}</div>
            </div>
            <div class="health-yomi-activity-metrics">
              <div class="health-yomi-activity-metric">
                <span class="health-yomi-activity-label">Uptime:</span>
                <span class="health-yomi-activity-value">${this.formatUptime(process.uptime || 0)}</span>
              </div>
              <div class="health-yomi-activity-metric">
                <span class="health-yomi-activity-label">Memory:</span>
                <span class="health-yomi-activity-value">${this.formatMemory(process.memory?.rss || 0)}</span>
              </div>
              <div class="health-yomi-activity-metric">
                <span class="health-yomi-activity-label">Updates (1h):</span>
                <span class="health-yomi-activity-value">${metrics.database?.updates_last_hour || 0}</span>
              </div>
            </div>
            ${processStatus.status && processStatus.status !== 'idle' ? `
              <div class="health-yomi-progress">
                <div class="health-yomi-progress-bar">
                  <div class="health-yomi-progress-fill" style="width: ${this.getProgressPercent(processStatus)}%"></div>
                </div>
                <div class="health-yomi-progress-text">${this.getProgressText(processStatus)}</div>
              </div>
            ` : ''}
          </div>
        </div>

        <div class="health-yomi-section">
          <h3 class="health-yomi-section-title">Recent Activity</h3>
          <div class="health-yomi-activity-feed">
            ${recentActivity.slice(0, 5).map(item => `
              <div class="health-yomi-activity-item">
                <div class="health-yomi-activity-item-name">${item.name}</div>
                <div class="health-yomi-activity-item-time">${this.formatTimeSince(new Date(item.updated_at))} ago</div>
                <div class="health-yomi-activity-item-quality">Quality: ${item.summary_quality || 'N/A'}</div>
              </div>
            `).join('')}
          </div>
        </div>
        
        <div class="health-yomi-section">
          <h3 class="health-yomi-section-title">Summarization Status</h3>
          <div class="health-yomi-overview">
            <div class="health-yomi-stat">
              <div class="health-yomi-value" data-field="summary-coverage">${summaryCoverage}%</div>
              <div class="health-yomi-label">Meaningful Summary Coverage</div>
            </div>
            <div class="health-yomi-stat">
              <div class="health-yomi-value" data-field="category-coverage">${categoryCoverage}%</div>
              <div class="health-yomi-label">Category Coverage</div>
            </div>
            <div class="health-yomi-stat">
              <div class="health-yomi-value" data-field="avg-quality">${avgQuality}</div>
              <div class="health-yomi-label">Avg Summary Quality</div>
            </div>
            <div class="health-yomi-stat">
              <div class="health-yomi-value" data-field="daily-summaries">${sum.dailySummaries?.totalSummaries || 0}</div>
              <div class="health-yomi-label">Daily Summaries</div>
            </div>
          </div>
        </div>

        <div class="health-yomi-details">
          <div class="health-yomi-detail">
            <span class="health-yomi-detail-label">Last updated:</span>
            <span class="health-yomi-detail-value" data-field="last-updated">${lastUpdated}</span>
          </div>
          <div class="health-yomi-detail">
            <span class="health-yomi-detail-label">Data generated at:</span>
            <span class="health-yomi-detail-value" data-field="generated-at">${status.generatedAt ? new Date(status.generatedAt).toLocaleString() : 'Unknown'}</span>
          </div>
          <div class="health-yomi-detail">
            <span class="health-yomi-detail-label">Latest summary date:</span>
            <span class="health-yomi-detail-value" data-field="latest-summary">${sum.dailySummaries?.latestSummaryDate || 'None'}</span>
          </div>
        </div>
      `;
    } else {
      // Update values in-place
      const apiStatusEl = container.querySelector('[data-field="api-status"]');
      if (apiStatusEl) {
        const oldStatus = apiStatusEl.className;
        apiStatusEl.className = `health-yomi-status ${status.api}`;
        apiStatusEl.textContent = status.api === 'healthy' ? 'Connected' : 'Disconnected';
        
        if (oldStatus !== `health-yomi-status ${status.api}`) {
          apiStatusEl.classList.add('status-updated');
          setTimeout(() => apiStatusEl.classList.remove('status-updated'), 1000);
        }
      }

      const countEl = container.querySelector('[data-field="conversation-count"]');
      if (countEl) {
        const oldCount = countEl.textContent;
        countEl.textContent = status.conversationCount;
        if (oldCount !== String(status.conversationCount)) {
          countEl.classList.add('stat-updated');
          setTimeout(() => countEl.classList.remove('stat-updated'), 500);
        }
      }

      const timeEl = container.querySelector('[data-field="time-since"]');
      if (timeEl) {
        timeEl.textContent = timeSinceUpdate;
      }

      const lastUpdatedEl = container.querySelector('[data-field="last-updated"]');
      if (lastUpdatedEl) {
        lastUpdatedEl.textContent = lastUpdated;
      }

      const generatedAtEl = container.querySelector('[data-field="generated-at"]');
      if (generatedAtEl) {
        generatedAtEl.textContent = status.generatedAt ? new Date(status.generatedAt).toLocaleString() : 'Unknown';
      }

      // Update summarization stats
      const summaryCoverageEl = container.querySelector('[data-field="summary-coverage"]');
      if (summaryCoverageEl) {
        const oldVal = summaryCoverageEl.textContent;
        summaryCoverageEl.textContent = `${summaryCoverage}%`;
        if (oldVal !== `${summaryCoverage}%`) {
          summaryCoverageEl.classList.add('stat-updated');
          setTimeout(() => summaryCoverageEl.classList.remove('stat-updated'), 500);
        }
      }

      const categoryCoverageEl = container.querySelector('[data-field="category-coverage"]');
      if (categoryCoverageEl) {
        categoryCoverageEl.textContent = `${categoryCoverage}%`;
      }

      const avgQualityEl = container.querySelector('[data-field="avg-quality"]');
      if (avgQualityEl) {
        avgQualityEl.textContent = avgQuality;
      }

      const dailySummariesEl = container.querySelector('[data-field="daily-summaries"]');
      if (dailySummariesEl) {
        const oldVal = dailySummariesEl.textContent;
        dailySummariesEl.textContent = sum.dailySummaries?.totalSummaries || 0;
        if (oldVal !== String(sum.dailySummaries?.totalSummaries || 0)) {
          dailySummariesEl.classList.add('stat-updated');
          setTimeout(() => dailySummariesEl.classList.remove('stat-updated'), 500);
        }
      }

      const latestSummaryEl = container.querySelector('[data-field="latest-summary"]');
      if (latestSummaryEl) {
        latestSummaryEl.textContent = sum.dailySummaries?.latestSummaryDate || 'None';
      }

      // Update progress bar if present
      const progressFillEl = container.querySelector('.health-yomi-progress-fill');
      const progressTextEl = container.querySelector('.health-yomi-progress-text');
      const activityTextEl = container.querySelector('.health-yomi-activity-text');
      const activityIndicatorEl = container.querySelector('.health-yomi-activity-indicator');
      
      if (processStatus.status && processStatus.status !== 'idle') {
        if (progressFillEl) {
          progressFillEl.style.width = `${this.getProgressPercent(processStatus)}%`;
        }
        if (progressTextEl) {
          progressTextEl.textContent = this.getProgressText(processStatus);
        }
        if (activityTextEl) {
          activityTextEl.textContent = this.getProcessStatusText(processStatus);
        }
        if (activityIndicatorEl) {
          activityIndicatorEl.className = `health-yomi-activity-indicator ${processStatus.status === 'processing' || processStatus.status === 'processing_batch' ? 'busy' : 'active'}`;
        }
      } else {
        if (progressFillEl) {
          progressFillEl.style.width = '0%';
        }
        if (progressTextEl) {
          progressTextEl.textContent = '';
        }
        if (activityTextEl) {
          activityTextEl.textContent = 'Idle - Monitoring active';
        }
        if (activityIndicatorEl) {
          activityIndicatorEl.className = 'health-yomi-activity-indicator active';
        }
      }
    }
  }

  formatUptime(seconds) {
    if (seconds < 60) return `${Math.floor(seconds)}s`;
    if (seconds < 3600) return `${Math.floor(seconds / 60)}m`;
    if (seconds < 86400) return `${Math.floor(seconds / 3600)}h`;
    return `${Math.floor(seconds / 86400)}d`;
  }

  formatMemory(bytes) {
    const mb = bytes / (1024 * 1024);
    if (mb < 1024) return `${mb.toFixed(1)}MB`;
    return `${(mb / 1024).toFixed(1)}GB`;
  }

  getProcessStatusText(status) {
    if (!status || status.status === 'idle') return 'Idle - Monitoring active';
    if (status.status === 'starting') return 'Starting...';
    if (status.status === 'processing') return `Processing: ${status.currentChat}`;
    if (status.status === 'processing_batch') return `Processing batch ${status.batch}/${status.totalBatches}`;
    if (status.status === 'batch_complete') return 'Batch complete';
    if (status.status === 'complete') return 'Complete';
    return status.status || 'Unknown';
  }

  getProgressPercent(status) {
    if (!status || !status.total) return 0;
    return Math.round((status.completed / status.total) * 100);
  }

  getProgressText(status) {
    if (!status || !status.total) return '';
    const completed = status.completed || 0;
    const total = status.total || 0;
    const successCount = status.successCount || 0;
    return `${completed}/${total} processed (${successCount} succeeded)`;
  }

  renderGPUStatus(status) {
    const container = document.getElementById('gpu-status');
    const gpu = status.gpu;
    const queue = status.queue;
    const services = status.services || {};

    // Check if initial render or error state
    const isInitialRender = container.innerHTML.includes('health-loading') ||
                           container.innerHTML.includes('health-gpu-error');

    if (isInitialRender) {
      // Extract GPU info
      const gpuInfo = gpu.gpus && gpu.gpus.length > 0 ? gpu.gpus[0] : null;
      const processes = gpu.processes || [];
      const queueStatus = queue.status || {};
      const runningJob = queue.running || null;
      const jobTypeBreakdown = queue.jobTypeBreakdown || {};
      const recentJobs = queue.recentJobs || [];
      const priorityDistribution = queue.priorityDistribution || {};

      if (gpu.error) {
        container.innerHTML = `
          <div class="health-gpu-error">
            <div class="health-gpu-status unhealthy">GPU Error</div>
            <div class="health-gpu-message">${gpu.error}</div>
            <div class="health-gpu-note">GPU may not be available or container is not running</div>
          </div>
        `;
        return;
      }

      if (!gpuInfo) {
        container.innerHTML = `
          <div class="health-gpu-error">
            <div class="health-gpu-status unhealthy">No GPU Found</div>
            <div class="health-gpu-message">No GPU information available</div>
          </div>
        `;
        return;
      }

      const vramPercent = Math.round((gpuInfo.memory_used_mb / gpuInfo.memory_total_mb) * 100);
      const vramUsedGB = (gpuInfo.memory_used_mb / 1024).toFixed(1);
      const vramTotalGB = (gpuInfo.memory_total_mb / 1024).toFixed(1);
      const utilizationPercent = gpuInfo.utilization_percent || 0;
      const temperatureC = gpuInfo.temperature_c || null;

      // Build processes list
      const processesHtml = processes.length > 0 ? processes.map(p => `
        <div class="health-gpu-process">
          <span class="health-gpu-process-name">${p.name}</span>
          <span class="health-gpu-process-memory">${(p.memory_used_mb / 1024).toFixed(1)} GB</span>
        </div>
      `).join('') : '<div class="health-gpu-process health-gpu-process-empty">No GPU processes running</div>';

      // Build queue status
      const pendingCount = queueStatus.pending || 0;
      const runningCount = queueStatus.running || 0;
      const completedCount = queueStatus.completed || 0;
      const failedCount = queueStatus.failed || 0;
      const cancelledCount = queueStatus.cancelled || 0;

      // Calculate job duration for running job
      const runningJobDuration = runningJob && runningJob.started_at 
        ? this.formatTimeSince(new Date(runningJob.started_at)) 
        : null;

      const runningJobHtml = runningJob ? `
        <div class="health-gpu-running-job">
          <div class="health-gpu-job-info">
            <span class="health-gpu-job-type">${runningJob.type}</span>
            <span class="health-gpu-job-id">#${runningJob.id}</span>
          </div>
          <div class="health-gpu-job-time">Started: ${new Date(runningJob.started_at).toLocaleTimeString()}</div>
          ${runningJobDuration ? `<div class="health-gpu-job-duration">Running for: ${runningJobDuration}</div>` : ''}
        </div>
      ` : '<div class="health-gpu-running-job health-gpu-job-empty">No job currently running</div>';

      // Build GPU service health
      const imagen2Status = services.imagen2?.status === 'ok' ? 'healthy' : 'unhealthy';
      const thaiLegalStatus = services.thaiLegal?.status === 'ok' ? 'healthy' : 'unhealthy';
      const txt2vidStatus = services.txt2vid?.status === 'ok' ? 'healthy' : 'unhealthy';

      const imagen2Model = services.imagen2?.model || 'Unknown';
      const txt2vidModel = services.txt2vid?.model || 'Unknown';

      // Build job type breakdown
      const jobTypeHtml = Object.keys(jobTypeBreakdown).length > 0 ? Object.entries(jobTypeBreakdown).map(([type, statuses]) => `
        <div class="health-gpu-job-type-item">
          <span class="health-gpu-job-type-name">${type}</span>
          <span class="health-gpu-job-type-statuses">
            ${Object.entries(statuses).map(([status, count]) => `
              <span class="health-gpu-job-type-status health-gpu-job-type-${status}">${status}: ${count}</span>
            `).join('')}
          </span>
        </div>
      `).join('') : '<div class="health-gpu-job-type-empty">No job history</div>';

      // Build recent jobs
      const recentJobsHtml = recentJobs.length > 0 ? recentJobs.map(job => `
        <div class="health-gpu-recent-job">
          <span class="health-gpu-recent-job-type">${job.type}</span>
          <span class="health-gpu-recent-job-id">#${job.id}</span>
          <span class="health-gpu-recent-job-status health-gpu-recent-${job.status}">${job.status}</span>
          <span class="health-gpu-recent-job-time">${this.formatTimeSince(new Date(job.completed_at || job.created_at))} ago</span>
        </div>
      `).join('') : '<div class="health-gpu-recent-empty">No recent jobs</div>';

      // Build priority distribution
      const priorityHtml = Object.keys(priorityDistribution).length > 0 ? Object.entries(priorityDistribution).map(([priority, count]) => {
        const priorityNames = { '4': 'embedding', '3': 'txt2vid/cogvideo', '2': 'imagen2', '1': 'llama' };
        return `
          <div class="health-gpu-priority-item">
            <span class="health-gpu-priority-level">P${priority}</span>
            <span class="health-gpu-priority-name">${priorityNames[priority] || 'unknown'}</span>
            <span class="health-gpu-priority-count">${count}</span>
          </div>
        `;
      }).join('') : '<div class="health-gpu-priority-empty">No pending jobs</div>';

      container.innerHTML = `
        <div class="health-gpu-overview">
          <div class="health-gpu-stat">
            <div class="health-gpu-value" data-field="gpu-name">${gpuInfo.name}</div>
            <div class="health-gpu-label">GPU Model</div>
          </div>
          <div class="health-gpu-stat">
            <div class="health-gpu-value" data-field="vram-usage">${vramUsedGB} / ${vramTotalGB} GB</div>
            <div class="health-gpu-label">VRAM Usage</div>
          </div>
          <div class="health-gpu-stat">
            <div class="health-gpu-value" data-field="vram-percent">${vramPercent}%</div>
            <div class="health-gpu-label">VRAM Used</div>
          </div>
          <div class="health-gpu-stat">
            <div class="health-gpu-value" data-field="gpu-util">${utilizationPercent}%</div>
            <div class="health-gpu-label">GPU Utilization</div>
          </div>
          ${temperatureC !== null ? `
          <div class="health-gpu-stat">
            <div class="health-gpu-value" data-field="gpu-temp">${temperatureC}°C</div>
            <div class="health-gpu-label">Temperature</div>
          </div>
          ` : ''}
        </div>

        <div class="health-gpu-section">
          <h3 class="health-gpu-section-title">GPU Service Health</h3>
          <div class="health-gpu-services">
            <div class="health-gpu-service">
              <div class="health-gpu-service-status ${imagen2Status}" data-field="service-imagen2">${imagen2Status === 'healthy' ? '✓' : '✗'}</div>
              <div class="health-gpu-service-info">
                <span class="health-gpu-service-name">Imagen2</span>
                <span class="health-gpu-service-model">${imagen2Model}</span>
              </div>
            </div>
            <div class="health-gpu-service">
              <div class="health-gpu-service-status ${thaiLegalStatus}" data-field="service-thai-legal">${thaiLegalStatus === 'healthy' ? '✓' : '✗'}</div>
              <div class="health-gpu-service-info">
                <span class="health-gpu-service-name">Thai Legal</span>
                <span class="health-gpu-service-model">LLM</span>
              </div>
            </div>
            <div class="health-gpu-service">
              <div class="health-gpu-service-status ${txt2vidStatus}" data-field="service-txt2vid">${txt2vidStatus === 'healthy' ? '✓' : '✗'}</div>
              <div class="health-gpu-service-info">
                <span class="health-gpu-service-name">Txt2Vid</span>
                <span class="health-gpu-service-model">${txt2vidModel}</span>
              </div>
            </div>
          </div>
        </div>

        <div class="health-gpu-section">
          <h3 class="health-gpu-section-title">VRAM Usage</h3>
          <div class="health-gpu-progress">
            <div class="health-gpu-progress-bar" data-field="vram-bar" style="width: ${vramPercent}%"></div>
          </div>
        </div>

        <div class="health-gpu-section">
          <h3 class="health-gpu-section-title">GPU Processes (${processes.length})</h3>
          <div class="health-gpu-processes" data-field="gpu-processes">
            ${processesHtml}
          </div>
        </div>

        <div class="health-gpu-section">
          <h3 class="health-gpu-section-title">GPU Queue Status</h3>
          <div class="health-gpu-queue-overview">
            <div class="health-gpu-queue-stat">
              <div class="health-gpu-queue-value" data-field="queue-pending">${pendingCount}</div>
              <div class="health-gpu-queue-label">Pending</div>
            </div>
            <div class="health-gpu-queue-stat">
              <div class="health-gpu-queue-value" data-field="queue-running">${runningCount}</div>
              <div class="health-gpu-queue-label">Running</div>
            </div>
            <div class="health-gpu-queue-stat">
              <div class="health-gpu-queue-value" data-field="queue-completed">${completedCount}</div>
              <div class="health-gpu-queue-label">Completed</div>
            </div>
            <div class="health-gpu-queue-stat">
              <div class="health-gpu-queue-value" data-field="queue-failed">${failedCount}</div>
              <div class="health-gpu-queue-label">Failed</div>
            </div>
            <div class="health-gpu-queue-stat">
              <div class="health-gpu-queue-value" data-field="queue-cancelled">${cancelledCount}</div>
              <div class="health-gpu-queue-label">Cancelled</div>
            </div>
          </div>
          <div class="health-gpu-running-job-container">
            <h4 class="health-gpu-job-title">Currently Running</h4>
            <div class="health-gpu-running-jobs" data-field="running-job">
              ${runningJobHtml}
            </div>
          </div>
        </div>

        <div class="health-gpu-section">
          <h3 class="health-gpu-section-title">Job Type Breakdown</h3>
          <div class="health-gpu-job-types" data-field="job-types">
            ${jobTypeHtml}
          </div>
        </div>

        <div class="health-gpu-section">
          <h3 class="health-gpu-section-title">Recent Jobs (Last 5)</h3>
          <div class="health-gpu-recent-jobs" data-field="recent-jobs">
            ${recentJobsHtml}
          </div>
        </div>

        ${Object.keys(priorityDistribution).length > 0 ? `
        <div class="health-gpu-section">
          <h3 class="health-gpu-section-title">Pending Priority Distribution</h3>
          <div class="health-gpu-priority" data-field="priority">
            ${priorityHtml}
          </div>
        </div>
        ` : ''}

        <div class="health-gpu-links">
          <a href="/apps/gpu-queue/" target="_blank" class="health-gpu-link">GPU Queue UI</a>
          <a href="/apps/netdata/" target="_blank" class="health-gpu-link">Netdata Dashboard</a>
        </div>
      `;
    } else {
      // Update values in-place for auto-refresh
      const gpuInfo = gpu.gpus && gpu.gpus.length > 0 ? gpu.gpus[0] : null;
      if (!gpuInfo) return;

      const vramPercent = Math.round((gpuInfo.memory_used_mb / gpuInfo.memory_total_mb) * 100);
      const vramUsedGB = (gpuInfo.memory_used_mb / 1024).toFixed(1);
      const vramTotalGB = (gpuInfo.memory_total_mb / 1024).toFixed(1);
      const utilizationPercent = gpuInfo.utilization_percent || 0;
      const temperatureC = gpuInfo.temperature_c || null;

      // Update VRAM usage
      const vramUsageEl = container.querySelector('[data-field="vram-usage"]');
      if (vramUsageEl) {
        vramUsageEl.textContent = `${vramUsedGB} / ${vramTotalGB} GB`;
      }

      const vramPercentEl = container.querySelector('[data-field="vram-percent"]');
      if (vramPercentEl) {
        vramPercentEl.textContent = `${vramPercent}%`;
      }

      const vramBarEl = container.querySelector('[data-field="vram-bar"]');
      if (vramBarEl) {
        vramBarEl.style.width = `${vramPercent}%`;
      }

      // Update GPU utilization
      const gpuUtilEl = container.querySelector('[data-field="gpu-util"]');
      if (gpuUtilEl) {
        gpuUtilEl.textContent = `${utilizationPercent}%`;
      }

      // Update temperature
      const gpuTempEl = container.querySelector('[data-field="gpu-temp"]');
      if (gpuTempEl && temperatureC !== null) {
        gpuTempEl.textContent = `${temperatureC}°C`;
      }

      // Update processes
      const processesEl = container.querySelector('[data-field="gpu-processes"]');
      if (processesEl && gpu.processes) {
        const processesHtml = gpu.processes.length > 0 ? gpu.processes.map(p => `
          <div class="health-gpu-process">
            <span class="health-gpu-process-name">${p.name}</span>
            <span class="health-gpu-process-memory">${(p.memory_used_mb / 1024).toFixed(1)} GB</span>
          </div>
        `).join('') : '<div class="health-gpu-process health-gpu-process-empty">No GPU processes running</div>';
        processesEl.innerHTML = processesHtml;
      }

      // Update queue status
      const queueStatus = queue.status || {};
      const pendingCount = queueStatus.pending || 0;
      const runningCount = queueStatus.running || 0;
      const completedCount = queueStatus.completed || 0;
      const failedCount = queueStatus.failed || 0;
      const cancelledCount = queueStatus.cancelled || 0;

      const pendingEl = container.querySelector('[data-field="queue-pending"]');
      if (pendingEl) pendingEl.textContent = pendingCount;

      const runningEl = container.querySelector('[data-field="queue-running"]');
      if (runningEl) runningEl.textContent = runningCount;

      const completedEl = container.querySelector('[data-field="queue-completed"]');
      if (completedEl) completedEl.textContent = completedCount;

      const failedEl = container.querySelector('[data-field="queue-failed"]');
      if (failedEl) failedEl.textContent = failedCount;

      const cancelledEl = container.querySelector('[data-field="queue-cancelled"]');
      if (cancelledEl) cancelledEl.textContent = cancelledCount;

      // Update running job
      const runningJobEl = container.querySelector('[data-field="running-job"]');
      if (runningJobEl) {
        const runningJob = queue.running || null;
        const runningJobDuration = runningJob && runningJob.started_at 
          ? this.formatTimeSince(new Date(runningJob.started_at)) 
          : null;
        const runningJobHtml = runningJob ? `
          <div class="health-gpu-running-job">
            <div class="health-gpu-job-info">
              <span class="health-gpu-job-type">${runningJob.type}</span>
              <span class="health-gpu-job-id">#${runningJob.id}</span>
            </div>
            <div class="health-gpu-job-time">Started: ${new Date(runningJob.started_at).toLocaleTimeString()}</div>
            ${runningJobDuration ? `<div class="health-gpu-job-duration">Running for: ${runningJobDuration}</div>` : ''}
          </div>
        ` : '<div class="health-gpu-running-job health-gpu-job-empty">No job currently running</div>';
        runningJobEl.innerHTML = runningJobHtml;
      }

      // Update GPU service health
      const imagen2Status = services.imagen2?.status === 'ok' ? 'healthy' : 'unhealthy';
      const thaiLegalStatus = services.thaiLegal?.status === 'ok' ? 'healthy' : 'unhealthy';
      const txt2vidStatus = services.txt2vid?.status === 'ok' ? 'healthy' : 'unhealthy';

      const imagen2El = container.querySelector('[data-field="service-imagen2"]');
      if (imagen2El) {
        imagen2El.className = `health-gpu-service-status ${imagen2Status}`;
        imagen2El.textContent = imagen2Status === 'healthy' ? '✓' : '✗';
      }

      const thaiLegalEl = container.querySelector('[data-field="service-thai-legal"]');
      if (thaiLegalEl) {
        thaiLegalEl.className = `health-gpu-service-status ${thaiLegalStatus}`;
        thaiLegalEl.textContent = thaiLegalStatus === 'healthy' ? '✓' : '✗';
      }

      const txt2vidEl = container.querySelector('[data-field="service-txt2vid"]');
      if (txt2vidEl) {
        txt2vidEl.className = `health-gpu-service-status ${txt2vidStatus}`;
        txt2vidEl.textContent = txt2vidStatus === 'healthy' ? '✓' : '✗';
      }

      // Update job type breakdown
      const jobTypesEl = container.querySelector('[data-field="job-types"]');
      if (jobTypesEl && queue.jobTypeBreakdown) {
        const jobTypeBreakdown = queue.jobTypeBreakdown;
        const jobTypeHtml = Object.keys(jobTypeBreakdown).length > 0 ? Object.entries(jobTypeBreakdown).map(([type, statuses]) => `
          <div class="health-gpu-job-type-item">
            <span class="health-gpu-job-type-name">${type}</span>
            <span class="health-gpu-job-type-statuses">
              ${Object.entries(statuses).map(([status, count]) => `
                <span class="health-gpu-job-type-status health-gpu-job-type-${status}">${status}: ${count}</span>
              `).join('')}
            </span>
          </div>
        `).join('') : '<div class="health-gpu-job-type-empty">No job history</div>';
        jobTypesEl.innerHTML = jobTypeHtml;
      }

      // Update recent jobs
      const recentJobsEl = container.querySelector('[data-field="recent-jobs"]');
      if (recentJobsEl && queue.recentJobs) {
        const recentJobs = queue.recentJobs;
        const recentJobsHtml = recentJobs.length > 0 ? recentJobs.map(job => `
          <div class="health-gpu-recent-job">
            <span class="health-gpu-recent-job-type">${job.type}</span>
            <span class="health-gpu-recent-job-id">#${job.id}</span>
            <span class="health-gpu-recent-job-status health-gpu-recent-${job.status}">${job.status}</span>
            <span class="health-gpu-recent-job-time">${this.formatTimeSince(new Date(job.completed_at || job.created_at))} ago</span>
          </div>
        `).join('') : '<div class="health-gpu-recent-empty">No recent jobs</div>';
        recentJobsEl.innerHTML = recentJobsHtml;
      }

      // Update priority distribution
      const priorityEl = container.querySelector('[data-field="priority"]');
      if (priorityEl && queue.priorityDistribution) {
        const priorityDistribution = queue.priorityDistribution;
        const priorityHtml = Object.keys(priorityDistribution).length > 0 ? Object.entries(priorityDistribution).map(([priority, count]) => {
          const priorityNames = { '4': 'embedding', '3': 'txt2vid/cogvideo', '2': 'imagen2', '1': 'llama' };
          return `
            <div class="health-gpu-priority-item">
              <span class="health-gpu-priority-level">P${priority}</span>
              <span class="health-gpu-priority-name">${priorityNames[priority] || 'unknown'}</span>
              <span class="health-gpu-priority-count">${count}</span>
            </div>
          `;
        }).join('') : '<div class="health-gpu-priority-empty">No pending jobs</div>';
        priorityEl.innerHTML = priorityHtml;
      }
    }
  }

  formatTimeSince(date) {
    const seconds = Math.floor((new Date() - date) / 1000);
    
    if (seconds < 60) return 'Just now';
    if (seconds < 3600) return `${Math.floor(seconds / 60)}m ago`;
    if (seconds < 86400) return `${Math.floor(seconds / 3600)}h ago`;
    if (seconds < 604800) return `${Math.floor(seconds / 86400)}d ago`;
    return `${Math.floor(seconds / 604800)}w ago`;
  }

  async checkService(service) {
    const startTime = Date.now();
    
    try {
      if (service.type === 'http') {
        return await this.checkHttp(service, startTime);
      } else if (service.type === 'container') {
        return await this.checkContainer(service, startTime);
      } else {
        return { status: 'unknown', error: 'Unknown service type' };
      }
    } catch (error) {
      return {
        status: 'unhealthy',
        error: error.message,
        responseTime: Date.now() - startTime
      };
    }
  }

  async checkHttp(service, startTime) {
    const controller = new AbortController();
    const timeout = setTimeout(() => controller.abort(), service.timeout * 1000);

    try {
      const response = await fetch(service.url, {
        method: 'GET',
        signal: controller.signal
      });
      clearTimeout(timeout);

      const responseTime = Date.now() - startTime;

      if (response.status === service.expected_status) {
        return {
          status: 'healthy',
          responseTime,
          statusCode: response.status
        };
      } else {
        return {
          status: 'degraded',
          responseTime,
          statusCode: response.status,
          error: `Expected ${service.expected_status}, got ${response.status}`
        };
      }
    } catch (error) {
      clearTimeout(timeout);
      if (error.name === 'AbortError') {
        return {
          status: 'unhealthy',
          error: 'Request timeout'
        };
      }
      return {
        status: 'unhealthy',
        error: error.message
      };
    }
  }

  async checkContainer(service, startTime) {
    try {
      // Use status-api to check container status
      const response = await fetch(`/api/container/${service.container}`);
      const data = await response.json();

      if (data.state === service.expected_state) {
        return {
          status: 'healthy',
          state: data.state,
          responseTime: Date.now() - startTime
        };
      } else {
        return {
          status: 'unhealthy',
          state: data.state,
          error: `Expected ${service.expected_state}, got ${data.state}`
        };
      }
    } catch (error) {
      // Fallback: try direct container check via status-api health
      try {
        const response = await fetch('/api/status');
        const data = await response.json();
        
        if (data.containers && data.containers[service.container]) {
          const containerState = data.containers[service.container].state;
          if (containerState === service.expected_state) {
            return { status: 'healthy', state: containerState };
          } else {
            return { 
              status: 'unhealthy', 
              state: containerState,
              error: `Expected ${service.expected_state}, got ${containerState}`
            };
          }
        }
      } catch (fallbackError) {
        // Ignore fallback error
      }
      
      return {
        status: 'unknown',
        error: 'Cannot determine container status'
      };
    }
  }

  renderOverallStatus() {
    const overall = this.calculateOverallStatus();
    const container = document.getElementById('overall-status');
    
    const stats = {
      total: this.services.length,
      healthy: this.services.filter(s => s.status?.status === 'healthy').length,
      degraded: this.services.filter(s => s.status?.status === 'degraded').length,
      unhealthy: this.services.filter(s => s.status?.status === 'unhealthy').length,
      unknown: this.services.filter(s => s.status?.status === 'unknown').length
    };

    // Check if initial render
    const isInitialRender = container.innerHTML.includes('health-loading');

    if (isInitialRender) {
      container.innerHTML = `
        <div class="health-stat">
          <div class="health-stat-value ${overall.class}" data-field="overall">${overall.label}</div>
          <div class="health-stat-label">Overall Status</div>
        </div>
        <div class="health-stat">
          <div class="health-stat-value healthy" data-field="healthy">${stats.healthy}</div>
          <div class="health-stat-label">Healthy</div>
        </div>
        <div class="health-stat">
          <div class="health-stat-value degraded" data-field="degraded">${stats.degraded}</div>
          <div class="health-stat-label">Degraded</div>
        </div>
        <div class="health-stat">
          <div class="health-stat-value unhealthy" data-field="unhealthy">${stats.unhealthy}</div>
          <div class="health-stat-label">Unhealthy</div>
        </div>
        <div class="health-stat">
          <div class="health-stat-value unknown" data-field="unknown">${stats.unknown}</div>
          <div class="health-stat-label">Unknown</div>
        </div>
      `;
    } else {
      // Update values in-place
      this.updateStatValue(container, 'overall', overall.label, overall.class);
      this.updateStatValue(container, 'healthy', stats.healthy, 'healthy');
      this.updateStatValue(container, 'degraded', stats.degraded, 'degraded');
      this.updateStatValue(container, 'unhealthy', stats.unhealthy, 'unhealthy');
      this.updateStatValue(container, 'unknown', stats.unknown, 'unknown');
    }
  }

  updateStatValue(container, field, value, className) {
    const el = container.querySelector(`[data-field="${field}"]`);
    if (el) {
      const oldValue = el.textContent;
      el.textContent = value;
      el.className = `health-stat-value ${className}`;
      
      // Flash animation if value changed
      if (oldValue !== String(value)) {
        el.classList.add('stat-updated');
        setTimeout(() => el.classList.remove('stat-updated'), 500);
      }
    }
  }

  calculateOverallStatus() {
    const healthy = this.services.filter(s => s.status?.status === 'healthy').length;
    const total = this.services.length;
    const unhealthy = this.services.filter(s => s.status?.status === 'unhealthy').length;
    const degraded = this.services.filter(s => s.status?.status === 'degraded').length;

    if (unhealthy > 0) {
      return { label: 'Unhealthy', class: 'unhealthy' };
    } else if (degraded > 0) {
      return { label: 'Degraded', class: 'degraded' };
    } else if (healthy === total) {
      return { label: 'Healthy', class: 'healthy' };
    } else {
      return { label: 'Unknown', class: 'unknown' };
    }
  }

  renderServices() {
    const container = document.getElementById('services-grid');
    const filteredServices = this.currentFilter === 'all' 
      ? this.services 
      : this.services.filter(s => s.category === this.currentFilter);

    if (filteredServices.length === 0) {
      container.innerHTML = '<div class="health-loading">No services in this category</div>';
      return;
    }

    // Check if this is initial render or update
    const isInitialRender = container.innerHTML.includes('health-loading') || 
                           container.children.length === 0;

    if (isInitialRender) {
      container.innerHTML = filteredServices.map(service => 
        this.renderServiceCard(service)).join('');
    } else {
      // Update existing cards in-place
      filteredServices.forEach(service => {
        this.updateServiceCard(service);
      });
    }
  }

  updateServiceCard(service) {
    const existingCard = document.getElementById(`service-${service.id}`);
    if (!existingCard) {
      // Card doesn't exist, append it
      const container = document.getElementById('services-grid');
      container.insertAdjacentHTML('beforeend', this.renderServiceCard(service));
      return;
    }

    const status = service.status || { status: 'unknown' };
    const statusClass = status.status || 'unknown';
    const responseTime = status.responseTime ? `${status.responseTime}ms` : 'N/A';
    const statusCode = status.statusCode || 'N/A';
    const state = status.state || 'N/A';

    // Update status badge
    const statusBadge = existingCard.querySelector('.health-service-status');
    const oldStatus = statusBadge.className;
    statusBadge.className = `health-service-status ${statusClass}`;
    statusBadge.textContent = status.status || 'Unknown';

    // Add flash animation if status changed
    if (oldStatus !== `health-service-status ${statusClass}`) {
      statusBadge.classList.add('status-updated');
      setTimeout(() => statusBadge.classList.remove('status-updated'), 1000);
    }

    // Update response time
    const responseTimeEl = existingCard.querySelector('.health-service-detail-value[data-field="responseTime"]');
    if (responseTimeEl) {
      responseTimeEl.textContent = responseTime;
    }

    // Update status code for HTTP services
    if (service.type === 'http') {
      const statusCodeEl = existingCard.querySelector('.health-service-detail-value[data-field="statusCode"]');
      if (statusCodeEl) {
        statusCodeEl.textContent = statusCode;
      }
    }

    // Update state for container services
    if (service.type === 'container') {
      const stateEl = existingCard.querySelector('.health-service-detail-value[data-field="state"]');
      if (stateEl) {
        stateEl.textContent = state;
      }
    }

    // Update error if present
    const errorEl = existingCard.querySelector('.health-service-detail-value[data-field="error"]');
    if (status.error) {
      if (!errorEl) {
        const detailsDiv = existingCard.querySelector('.health-service-details');
        detailsDiv.insertAdjacentHTML('beforeend', `
          <div class="health-service-detail">
            <span class="health-service-detail-label">Error:</span>
            <span class="health-service-detail-value" style="color: var(--health-error)" data-field="error">${status.error}</span>
          </div>
        `);
      } else {
        errorEl.textContent = status.error;
      }
    } else if (errorEl) {
      errorEl.parentElement.remove();
    }
  }

  renderServiceCard(service) {
    const status = service.status || { status: 'unknown' };
    const statusClass = status.status || 'unknown';
    const responseTime = status.responseTime ? `${status.responseTime}ms` : 'N/A';
    const statusCode = status.statusCode || 'N/A';
    const state = status.state || 'N/A';

    return `
      <div class="health-service" id="service-${service.id}">
        <div class="health-service-header">
          <span class="health-service-name">${service.name}</span>
          <span class="health-service-status ${statusClass}">${status.status || 'Unknown'}</span>
        </div>
        <div class="health-service-details">
          <div class="health-service-detail">
            <span class="health-service-detail-label">Type:</span>
            <span class="health-service-detail-value">${service.type}</span>
          </div>
          <div class="health-service-detail">
            <span class="health-service-detail-label">Response Time:</span>
            <span class="health-service-detail-value" data-field="responseTime">${responseTime}</span>
          </div>
          ${service.type === 'http' ? `
            <div class="health-service-detail">
              <span class="health-service-detail-label">Status Code:</span>
              <span class="health-service-detail-value" data-field="statusCode">${statusCode}</span>
            </div>
          ` : ''}
          ${service.type === 'container' ? `
            <div class="health-service-detail">
              <span class="health-service-detail-label">State:</span>
              <span class="health-service-detail-value" data-field="state">${state}</span>
            </div>
          ` : ''}
          ${status.error ? `
            <div class="health-service-detail">
              <span class="health-service-detail-label">Error:</span>
              <span class="health-service-detail-value" style="color: var(--health-error)" data-field="error">${status.error}</span>
            </div>
          ` : ''}
          <div class="health-service-category">${service.category || 'uncategorized'}</div>
        </div>
      </div>
    `;
  }

  renderRecoveryActions() {
    const container = document.getElementById('recovery-actions');
    
    if (!this.recoveryActions || Object.keys(this.recoveryActions).length === 0) {
      container.innerHTML = '<div class="health-loading">No recovery actions configured</div>';
      return;
    }

    container.innerHTML = Object.entries(this.recoveryActions).map(([key, actions]) => `
      <div class="health-recovery-section">
        <h3>${this.formatKey(key)}</h3>
        <div class="health-recovery-actions">
          ${actions.map(action => `
            <div class="health-recovery-action">${action}</div>
          `).join('')}
        </div>
      </div>
    `).join('');
  }

  formatKey(key) {
    return key.split('_').map(word => word.charAt(0).toUpperCase() + word.slice(1)).join(' ');
  }

  updateLastUpdated() {
    const now = new Date();
    document.getElementById('last-updated').textContent = `Last updated: ${now.toLocaleTimeString()}`;
  }

  setRefreshStatus(status) {
    const element = document.getElementById('refresh-status');
    element.className = `health-refresh-status ${status}`;
    
    switch (status) {
      case 'refreshing':
        element.textContent = 'Refreshing...';
        break;
      case 'success':
        element.textContent = 'Refreshed';
        setTimeout(() => element.textContent = '', 2000);
        break;
      case 'error':
        element.textContent = 'Refresh failed';
        break;
    }
  }

  showError(message) {
    const container = document.getElementById('services-grid');
    container.innerHTML = `<div class="health-loading" style="color: var(--health-error)">${message}</div>`;
  }

  startAutoRefresh() {
    this.stopAutoRefresh();
    this.autoRefreshInterval = setInterval(() => {
      this.runHealthChecks();
      
      // Also refresh Yomi status if Yomi tab is active
      const yomiTab = document.querySelector('.health-tab[data-tab="yomi"]');
      if (yomiTab && yomiTab.classList.contains('health-tab-active')) {
        this.checkYomiStatus();
      }
    }, 30000); // 30 seconds
  }

  stopAutoRefresh() {
    if (this.autoRefreshInterval) {
      clearInterval(this.autoRefreshInterval);
      this.autoRefreshInterval = null;
    }
  }
}

// Initialize dashboard when DOM is ready
document.addEventListener('DOMContentLoaded', () => {
  window.dashboard = new HealthCheckDashboard();
});
