/**
 * Focus Tracker - Strategic Focus Management Dashboard
 * Phase 2: Activity Database Integration and Timeline
 */

console.log('Focus Tracker: Script loaded');

class FocusTracker {
  constructor() {
    console.log('Focus Tracker: Constructor called');
    this.focusData = null;
    this.activityData = null;
    this.healthData = null;
    this.ssotUrl = '/ssot.focus.yml';
    this.activityApiUrl = '/api/focus';
    this.healthApiUrl = '/api/health';
    this.useSampleData = false;
    this.healthDetailsVisible = false;
    this.init();
  }

  async init() {
    try {
      console.log('Focus Tracker: Initializing...');
      
      // Load focus data
      if (this.useSampleData) {
        console.log('Focus Tracker: Using sample focus data');
        this.focusData = this.getSampleFocusData();
      } else {
        await this.loadFocusData();
      }
      
      // Load activity data
      await this.loadActivityData();
      
      // Load health data
      await this.loadHealthData();
      
      console.log('Focus Tracker: Data loaded successfully');
      this.renderCurrentFocus();
      this.renderSharedFocus();
      this.renderBranchFocus();
      this.renderRules();
      this.renderActivityTimeline();
      this.renderActivitySummary();
      this.renderHealthStatus();
      this.updateLastUpdated();
      console.log('Focus Tracker: Rendering complete');
    } catch (error) {
      console.error('Focus Tracker: Error during initialization', error);
      this.showError('Failed to load data: ' + error.message);
    }
  }

  getSampleFocusData() {
    return {
      shared: [
        {
          label: 'GPU Queue & Monitoring System',
          text: 'Cross-project GPU resource management, queue optimization, monitoring enhancements, and process management',
          status: 'active',
          priority: 'high',
          strategic_value: 'Critical infrastructure shared across all projects',
          estimated_duration: 'Ongoing',
          tags: ['infrastructure', 'gpu', 'shared', 'monitoring'],
          dependencies: ['SSOT & Documentation Standards'],
          current_context: 'Job cancellation analysis completed, critical improvements implemented'
        },
        {
          label: 'SSOT & Documentation Standards',
          text: 'SSOT structure, validation, documentation patterns, KB management, and cross-project documentation consistency',
          status: 'completed',
          priority: 'medium',
          strategic_value: 'Foundation for all project documentation and configuration management',
          estimated_duration: 'Ongoing',
          tags: ['documentation', 'ssot', 'shared', 'standards'],
          current_context: 'MCP config sync completed, validation patterns SSOT created'
        }
      ],
      branch: [
        {
          label: 'Chaba Infrastructure Completion',
          text: 'DNS resolution fix, README.md hostname updates, documentation index creation, and infrastructure hardening',
          branch: 'chaba',
          status: 'pending',
          priority: 'high',
          strategic_value: 'Completes foundational infrastructure for chaba project',
          estimated_duration: '1-2 sessions',
          tags: ['infrastructure', 'chaba', 'completion'],
          dependencies: ['SSOT & Documentation Standards']
        },
        {
          label: 'Trade Subagent Implementation',
          text: 'Priority 1 subagents: SSOT Config Manager, Multi-Service Health Monitor, Documentation Cross-Reference Maintainer',
          branch: 'trade',
          status: 'pending',
          priority: 'high',
          strategic_value: 'Leverages existing trade infrastructure for significant efficiency gains',
          estimated_duration: '2-3 weeks',
          tags: ['subagents', 'trade', 'automation'],
          dependencies: ['Subagent Framework & Automation', 'SSOT & Documentation Standards']
        }
      ],
      rules: [
        {
          label: 'Single Active Focus Rule',
          text: 'Maximum 1 shared + 1 per-branch strategic focus active at any time to prevent strategic fragmentation',
          enforcement: 'validation',
          tags: ['rules', 'focus', 'constraints']
        },
        {
          label: 'Strategic Priority Alignment',
          text: 'High-priority strategic focuses take precedence over medium/low priorities across all branches',
          enforcement: 'manual',
          tags: ['rules', 'priority', 'alignment']
        }
      ]
    };
  }

  async loadActivityData() {
    try {
      console.log('Loading activity data from:', this.activityApiUrl);
      
      // Load recent activities (past 7 days)
      const response = await fetch(`${this.activityApiUrl}/activities/recent?hours=168`);
      if (response.ok) {
        this.activityData = await response.json();
        console.log('Activity data loaded:', this.activityData.length, 'activities');
      } else {
        console.warn('Failed to load activity data:', response.status);
        this.activityData = [];
      }
    } catch (error) {
      console.error('Error loading activity data:', error);
      this.activityData = [];
    }
  }

  async loadHealthData() {
    try {
      console.log('Loading health data from:', this.healthApiUrl);
      const response = await fetch(this.healthApiUrl);
      if (response.ok) {
        this.healthData = await response.json();
        console.log('Health data loaded:', this.healthData);
      } else {
        console.warn('Failed to load health data:', response.status);
        this.healthData = null;
      }
    } catch (error) {
      console.error('Error loading health data:', error);
      this.healthData = null;
    }
  }

  async loadFocusData() {
    try {
      console.log('Loading SSOT from:', this.ssotUrl);
      const response = await fetch(this.ssotUrl);
      console.log('Response status:', response.status);
      
      if (!response.ok) {
        throw new Error(`HTTP ${response.status}: ${response.statusText}`);
      }
      
      const yamlText = await response.text();
      console.log('SSOT content length:', yamlText.length);
      
      this.focusData = this.parseYAML(yamlText);
      console.log('Parsed focus data:', this.focusData);
    } catch (error) {
      console.error('Error loading focus data:', error);
      throw error;
    }
  }

  parseYAML(yamlText) {
    const lines = yamlText.split('\n');
    const data = {
      shared: [],
      branch: [],
      rules: []
    };

    let currentSection = null;
    let currentItem = null;
    let inDependencies = false;

    for (const line of lines) {
      const trimmed = line.trim();
      const indent = line.search(/\S|$/);

      if (indent === 2 && trimmed.startsWith('- title:')) {
        const title = trimmed.substring(9).trim();
        if (title.includes('Shared Strategic Focus Areas')) {
          currentSection = 'shared';
        } else if (title.includes('Per-Branch Strategic Focus Areas')) {
          currentSection = 'branch';
        } else if (title.includes('Focus Management Rules')) {
          currentSection = 'rules';
        } else {
          currentSection = null;
        }
        currentItem = null;
        inDependencies = false;
        continue;
      }

      if (currentSection && indent === 6 && trimmed.startsWith('- label:')) {
        if (currentItem) {
          data[currentSection].push(currentItem);
        }
        currentItem = {
          label: trimmed.substring(9).trim(),
          status: 'pending',
          priority: 'medium',
          tags: [],
          dependencies: []
        };
        inDependencies = false;
        continue;
      }

      if (currentItem && currentSection && indent === 8) {
        inDependencies = false;
        if (trimmed.startsWith('status:')) {
          currentItem.status = trimmed.substring(7).trim();
        } else if (trimmed.startsWith('priority:')) {
          currentItem.priority = trimmed.substring(9).trim();
        } else if (trimmed.startsWith('text:')) {
          currentItem.text = trimmed.substring(5).trim();
        } else if (trimmed.startsWith('branch:')) {
          currentItem.branch = trimmed.substring(7).trim();
        } else if (trimmed.startsWith('tags:')) {
          currentItem.tags = this.parseArray(trimmed.substring(5).trim());
        } else if (trimmed.startsWith('dependencies:')) {
          inDependencies = true;
        } else if (trimmed.startsWith('current_context:')) {
          currentItem.current_context = trimmed.substring(16).trim().replace(/"/g, '');
        } else if (trimmed.startsWith('strategic_value:')) {
          currentItem.strategic_value = trimmed.substring(17).trim();
        } else if (trimmed.startsWith('estimated_duration:')) {
          currentItem.estimated_duration = trimmed.substring(20).trim();
        } else if (trimmed.startsWith('enforcement:')) {
          currentItem.enforcement = trimmed.substring(11).trim();
        }
        continue;
      }

      if (currentItem && currentSection && inDependencies && indent === 10 && trimmed.startsWith('- ')) {
        currentItem.dependencies.push(trimmed.substring(2).trim());
        continue;
      }
    }

    if (currentItem && currentSection) {
      data[currentSection].push(currentItem);
    }

    return data;
  }

  parseArray(text) {
    if (text.startsWith('[') && text.endsWith(']')) {
      return text.slice(1, -1).split(',').map(item => item.trim());
    }
    return [];
  }

  renderCurrentFocus() {
    console.log('Focus Tracker: Rendering current focus');
    const container = document.getElementById('current-focus-container');
    const activeShared = this.focusData.shared.find(f => f.status === 'active');
    const activeBranch = this.focusData.branch.find(f => f.status === 'active');

    if (!activeShared && !activeBranch) {
      container.innerHTML = `
        <div class="empty-state">
          <div class="empty-state-icon">🎯</div>
          <p>No active focus areas currently set</p>
        </div>
      `;
      return;
    }

    let html = '';
    if (activeShared) {
      html += this.renderFocusCard(activeShared, '🌐 Shared');
    }
    if (activeBranch) {
      html += this.renderFocusCard(activeBranch, '🔀 Branch');
    }

    container.innerHTML = html;
  }

  renderSharedFocus() {
    console.log('Focus Tracker: Rendering shared focus');
    const container = document.getElementById('shared-focus-container');
    const items = this.focusData.shared.filter(f => f.status !== 'active');

    if (items.length === 0) {
      container.innerHTML = `
        <div class="empty-state">
          <div class="empty-state-icon">🌐</div>
          <p>No shared focus areas available</p>
        </div>
      `;
      return;
    }

    container.innerHTML = items.map(item => this.renderFocusCard(item)).join('');
  }

  renderBranchFocus() {
    console.log('Focus Tracker: Rendering branch focus');
    const container = document.getElementById('branch-focus-container');
    const items = this.focusData.branch.filter(f => f.status !== 'active');

    if (items.length === 0) {
      container.innerHTML = `
        <div class="empty-state">
          <div class="empty-state-icon">🔀</div>
          <p>No branch focus areas available</p>
        </div>
      `;
      return;
    }

    container.innerHTML = items.map(item => this.renderFocusCard(item)).join('');
  }

  renderRules() {
    console.log('Focus Tracker: Rendering rules');
    const container = document.getElementById('rules-container');

    if (this.focusData.rules.length === 0) {
      container.innerHTML = `
        <div class="empty-state">
          <div class="empty-state-icon">📋</div>
          <p>No focus rules defined</p>
        </div>
      `;
      return;
    }

    container.innerHTML = this.focusData.rules.map(rule => `
      <div class="focus-card">
        <div class="focus-header">
          <h3 class="focus-title">${rule.label}</h3>
          <div class="focus-badges">
            ${rule.enforcement ? `<span class="badge tag">${rule.enforcement}</span>` : ''}
          </div>
        </div>
        <p class="focus-description">${rule.text || ''}</p>
        ${rule.tags && rule.tags.length > 0 ? `
          <div class="focus-badges">
            ${rule.tags.map(tag => `<span class="badge tag">${tag}</span>`).join('')}
          </div>
        ` : ''}
      </div>
    `).join('');
  }

  renderActivityTimeline() {
    console.log('Focus Tracker: Rendering activity timeline');
    const container = document.getElementById('activity-timeline-container');
    
    if (!this.activityData || this.activityData.length === 0) {
      container.innerHTML = `
        <div class="empty-state">
          <div class="empty-state-icon">📊</div>
          <p>No recent activity data available</p>
        </div>
      `;
      return;
    }

    // Group activities by date
    const groupedByDate = {};
    this.activityData.forEach(activity => {
      const date = new Date(activity.timestamp).toLocaleDateString();
      if (!groupedByDate[date]) {
        groupedByDate[date] = [];
      }
      groupedByDate[date].push(activity);
    });

    // Render timeline
    let html = '';
    Object.keys(groupedByDate).sort().reverse().forEach(date => {
      html += `
        <div class="timeline-date">
          <h3>${date}</h3>
          <div class="timeline-activities">
            ${groupedByDate[date].slice(0, 10).map(activity => this.renderActivityItem(activity)).join('')}
          </div>
        </div>
      `;
    });

    container.innerHTML = html;
  }

  renderActivityItem(activity) {
    const time = new Date(activity.timestamp).toLocaleTimeString();
    const focusArea = activity.focus_area || 'Unassigned';
    const impactScore = activity.details?.impact_score || 0;
    
    return `
      <div class="activity-item">
        <div class="activity-time">${time}</div>
        <div class="activity-content">
          <div class="activity-type">${activity.activity_type}</div>
          <div class="activity-focus">${focusArea}</div>
          ${activity.details?.commit_message ? `
            <div class="activity-message">${activity.details.commit_message}</div>
          ` : ''}
        </div>
        <div class="activity-impact score-${impactScore > 7 ? 'high' : impactScore > 4 ? 'medium' : 'low'}">
          ${impactScore}
        </div>
      </div>
    `;
  }

  renderActivitySummary() {
    console.log('Focus Tracker: Rendering activity summary');
    const container = document.getElementById('activity-summary-container');
    
    if (!this.activityData || this.activityData.length === 0) {
      container.innerHTML = `
        <div class="empty-state">
          <div class="empty-state-icon">📈</div>
          <p>No activity data to summarize</p>
        </div>
      `;
      return;
    }

    // Calculate summary statistics
    const summary = {
      totalActivities: this.activityData.length,
      byFocusArea: {},
      byType: {},
      totalImpact: 0,
      avgImpact: 0
    };

    this.activityData.forEach(activity => {
      const focus = activity.focus_area || 'Unassigned';
      const type = activity.activity_type;
      const impact = activity.details?.impact_score || 0;

      summary.byFocusArea[focus] = (summary.byFocusArea[focus] || 0) + 1;
      summary.byType[type] = (summary.byType[type] || 0) + 1;
      summary.totalImpact += impact;
    });

    summary.avgImpact = (summary.totalImpact / summary.totalActivities).toFixed(1);

    // Render summary
    let html = `
      <div class="summary-stats">
        <div class="stat-card">
          <div class="stat-value">${summary.totalActivities}</div>
          <div class="stat-label">Total Activities</div>
        </div>
        <div class="stat-card">
          <div class="stat-value">${summary.avgImpact}</div>
          <div class="stat-label">Avg Impact Score</div>
        </div>
        <div class="stat-card">
          <div class="stat-value">${Object.keys(summary.byFocusArea).length}</div>
          <div class="stat-label">Focus Areas</div>
        </div>
      </div>
      
      <div class="summary-section">
        <h4>Activities by Focus Area</h4>
        <div class="summary-bars">
          ${Object.entries(summary.byFocusArea)
            .sort((a, b) => b[1] - a[1])
            .map(([focus, count]) => {
              const percentage = (count / summary.totalActivities * 100).toFixed(1);
              return `
                <div class="summary-bar">
                  <div class="bar-label">${focus}</div>
                  <div class="bar-track">
                    <div class="bar-fill" style="width: ${percentage}%"></div>
                  </div>
                  <div class="bar-value">${count} (${percentage}%)</div>
                </div>
              `;
            }).join('')}
        </div>
      </div>
      
      <div class="summary-section">
        <h4>Activities by Type</h4>
        <div class="focus-badges">
          ${Object.entries(summary.byType)
            .sort((a, b) => b[1] - a[1])
            .map(([type, count]) => `
              <span class="badge tag">${type}: ${count}</span>
            `).join('')}
        </div>
      </div>
    `;

    container.innerHTML = html;
  }

  renderHealthStatus() {
    console.log('Focus Tracker: Rendering health status');
    const container = document.getElementById('health-status-container');
    
    if (!this.healthData) {
      container.innerHTML = `
        <div class="empty-state">
          <div class="empty-state-icon">🏥</div>
          <p>Health check not available</p>
        </div>
      `;
      return;
    }

    // Calculate summary statistics
    const summary = {
      total: this.healthData.services?.length || 0,
      healthy: 0,
      degraded: 0,
      error: 0,
      byCategory: {}
    };

    this.healthData.services?.forEach(service => {
      const status = service.status || 'unknown';
      const category = service.category || 'other';
      
      if (status === 'healthy') summary.healthy++;
      else if (status === 'degraded') summary.degraded++;
      else if (status === 'error') summary.error++;
      
      summary.byCategory[category] = summary.byCategory[category] || { healthy: 0, degraded: 0, error: 0, total: 0 };
      summary.byCategory[category][status]++;
      summary.byCategory[category].total++;
    });

    const overallStatus = summary.error > 0 ? 'error' : summary.degraded > 0 ? 'degraded' : 'healthy';
    const statusIcon = overallStatus === 'healthy' ? '✅' : overallStatus === 'degraded' ? '⚠️' : '❌';

    // Update summary badge
    const summaryBadge = document.getElementById('health-summary-badge');
    if (summaryBadge) {
      summaryBadge.textContent = `${summary.healthy}/${summary.total} healthy`;
      summaryBadge.className = `health-summary-badge ${overallStatus}`;
    }

    // Get service type icon
    const getServiceTypeIcon = (type) => {
      switch(type) {
        case 'http': return '🌐';
        case 'container': return '🐳';
        case 'systemd': return '⚙️';
        default: return '❓';
      }
    };

    // Group services by category
    const servicesByCategory = {};
    this.healthData.services?.forEach(service => {
      const category = service.category || 'other';
      if (!servicesByCategory[category]) {
        servicesByCategory[category] = [];
      }
      servicesByCategory[category].push(service);
    });

    // Render health status
    let html = `
      <div class="health-status-grid">
        <div class="health-status-card">
          <div class="health-status-icon health-status-${overallStatus}">${statusIcon}</div>
          <div class="health-status-value health-status-${overallStatus}">${summary.healthy}/${summary.total}</div>
          <div class="health-status-label">Healthy Services</div>
        </div>
        <div class="health-status-card">
          <div class="health-status-icon">⚠️</div>
          <div class="health-status-value health-status-degraded">${summary.degraded}</div>
          <div class="health-status-label">Degraded</div>
        </div>
        <div class="health-status-card">
          <div class="health-status-icon">❌</div>
          <div class="health-status-value health-status-error">${summary.error}</div>
          <div class="health-status-label">Error</div>
        </div>
        <div class="health-status-card">
          <div class="health-status-icon">📊</div>
          <div class="health-status-value">${Object.keys(servicesByCategory).length}</div>
          <div class="health-status-label">Categories</div>
        </div>
      </div>
      
      <div class="health-services-list">
        ${Object.entries(servicesByCategory).map(([category, services]) => `
          <div class="health-category-group">
            <div class="health-category-header">
              <span class="health-category-name">${category.charAt(0).toUpperCase() + category.slice(1)}</span>
              <span class="health-category-count">${services.length}</span>
            </div>
            ${services.map(service => {
              const status = service.status || 'unknown';
              const statusClass = status === 'healthy' ? 'healthy' : status === 'degraded' ? 'degraded' : 'error';
              const typeIcon = getServiceTypeIcon(service.type);
              const responseTime = service.response_time ? `${service.response_time}ms` : '';
              const error = service.error ? `<div class="health-service-error">${service.error}</div>` : '';
              return `
                <div class="health-service-item">
                  <div class="health-service-info">
                    <span class="health-service-type">${typeIcon}</span>
                    <span class="health-service-name">${service.name || service.id}</span>
                  </div>
                  <div class="health-service-meta">
                    <span class="health-service-response-time">${responseTime}</span>
                    <span class="health-service-status ${statusClass}">${status}</span>
                  </div>
                  ${error}
                </div>
              `;
            }).join('')}
          </div>
        `).join('') || '<div class="empty-state">No services configured</div>'}
      </div>
      
      <div class="health-last-checked">
        Last checked: ${this.healthData.checkedAt ? new Date(this.healthData.checkedAt).toLocaleString() : new Date().toLocaleString()}
      </div>
    `;

    container.innerHTML = html;
  }

  async runHealthCheck() {
    console.log('Focus Tracker: Running health check');
    const container = document.getElementById('health-status-container');
    container.innerHTML = `
      <div class="empty-state">
        <div class="empty-state-icon">🔄</div>
        <p>Running health check...</p>
      </div>
    `;
    
    await this.loadHealthData();
    this.renderHealthStatus();
    
    if (this.healthDetailsVisible) {
      this.renderHealthDetails();
    }
  }

  toggleHealthDetails() {
    console.log('Focus Tracker: Toggling health details');
    this.healthDetailsVisible = !this.healthDetailsVisible;
    const container = document.getElementById('health-details-container');
    container.style.display = this.healthDetailsVisible ? 'block' : 'none';
    
    if (this.healthDetailsVisible) {
      this.renderHealthDetails();
    }
  }

  renderHealthDetails() {
    console.log('Focus Tracker: Rendering health details');
    const container = document.getElementById('health-details-container');
    
    if (!this.healthData || !this.healthData.services) {
      container.innerHTML = `
        <div class="empty-state">
          <div class="empty-state-icon">📋</div>
          <p>No health details available</p>
        </div>
      `;
      return;
    }

    // Group services by category
    const byCategory = {};
    this.healthData.services.forEach(service => {
      const category = service.category || 'other';
      if (!byCategory[category]) {
        byCategory[category] = [];
      }
      byCategory[category].push(service);
    });

    // Render detailed view
    let html = '';
    Object.keys(byCategory).sort().forEach(category => {
      html += `
        <div class="focus-card">
          <div class="focus-header">
            <h3 class="focus-title">${category.charAt(0).toUpperCase() + category.slice(1)}</h3>
            <div class="focus-badges">
              <span class="badge tag">${byCategory[category].length} services</span>
            </div>
          </div>
          <div class="health-services-list">
            ${byCategory[category].map(service => {
              const status = service.status || 'unknown';
              const statusClass = status === 'healthy' ? 'healthy' : status === 'degraded' ? 'degraded' : 'error';
              return `
                <div class="health-service-item">
                  <div class="health-service-name">${service.name || service.id}</div>
                  <div class="health-service-status ${statusClass}">${status}</div>
                </div>
                ${service.response_time ? `
                  <div style="font-size: 0.8rem; color: #64748b; padding-left: 12px; margin-top: 4px;">
                    Response time: ${service.response_time}ms
                  </div>
                ` : ''}
                ${service.error ? `
                  <div style="font-size: 0.8rem; color: #991b1b; padding-left: 12px; margin-top: 4px;">
                    Error: ${service.error}
                  </div>
                ` : ''}
              `;
            }).join('')}
          </div>
        </div>
      `;
    });

    container.innerHTML = html;
  }

  renderFocusCard(item, prefix = '') {
    const canActivate = item.status !== 'active' && this.checkDependenciesReady(item);
    const canComplete = item.status !== 'completed';
    const canSwitch = item.status === 'active';
    
    return `
      <div class="focus-card">
        <div class="focus-header">
          <h3 class="focus-title">${prefix ? prefix + ' ' : ''}${item.label}</h3>
          <div class="focus-badges">
            <span class="badge status-${item.status}">${item.status}</span>
            <span class="badge priority-${item.priority}">${item.priority}</span>
          </div>
        </div>
        <p class="focus-description">${item.text || ''}</p>
        
        ${item.strategic_value ? `
          <div class="focus-meta">
            <div class="meta-item">
              <span class="meta-label">Strategic Value:</span>
              <span>${item.strategic_value}</span>
            </div>
          </div>
        ` : ''}
        
        ${item.estimated_duration ? `
          <div class="focus-meta">
            <div class="meta-item">
              <span class="meta-label">Duration:</span>
              <span>${item.estimated_duration}</span>
            </div>
          </div>
        ` : ''}
        
        ${item.branch ? `
          <div class="focus-meta">
            <div class="meta-item">
              <span class="meta-label">Branch:</span>
              <span>${item.branch}</span>
            </div>
          </div>
        ` : ''}
        
        ${item.tags && item.tags.length > 0 ? `
          <div class="focus-badges" style="margin-top: 12px;">
            ${item.tags.map(tag => `<span class="badge tag">${tag}</span>`).join('')}
          </div>
        ` : ''}
        
        ${item.current_context ? `
          <div class="focus-context">
            <strong>Current Context:</strong> ${item.current_context}
          </div>
        ` : ''}
        
        ${item.dependencies && item.dependencies.length > 0 ? `
          <div class="focus-dependencies">
            <strong>Dependencies:</strong>
            <div class="dependency-list">
              ${item.dependencies.map(dep => `<span class="dependency-item">${dep}</span>`).join('')}
            </div>
          </div>
        ` : ''}
        
        <div class="focus-controls">
          ${canActivate ? `<button class="control-button btn-activate" onclick="focusTracker.activateFocus('${item.label}')">▶ Activate</button>` : ''}
          ${canComplete ? `<button class="control-button btn-complete" onclick="focusTracker.completeFocus('${item.label}')">✓ Complete</button>` : ''}
          ${canSwitch ? `<button class="control-button btn-pause" onclick="focusTracker.pauseFocus('${item.label}')">⏸ Pause</button>` : ''}
        </div>
      </div>
    `;
  }

  updateLastUpdated() {
    const timestamp = new Date().toLocaleString();
    document.getElementById('last-updated').textContent = timestamp;
  }

  checkDependenciesReady(item) {
    if (!item.dependencies || item.dependencies.length === 0) {
      return true;
    }
    
    const allFocuses = [...this.focusData.shared, ...this.focusData.branch];
    const blocking = [];
    
    item.dependencies.forEach(dep => {
      const depFocus = allFocuses.find(f => f.label === dep);
      if (!depFocus || depFocus.status !== 'completed') {
        blocking.push(dep);
      }
    });
    
    return blocking.length === 0;
  }

  activateFocus(label) {
    console.log('Activating focus:', label);
    alert('Focus activation not yet implemented: ' + label);
  }

  completeFocus(label) {
    console.log('Completing focus:', label);
    alert('Focus completion not yet implemented: ' + label);
  }

  pauseFocus(label) {
    console.log('Pausing focus:', label);
    alert('Focus pause not yet implemented: ' + label);
  }

  showError(message) {
    const containers = [
      'current-focus-container',
      'shared-focus-container',
      'branch-focus-container',
      'rules-container',
      'activity-timeline-container',
      'activity-summary-container'
    ];

    containers.forEach(id => {
      const container = document.getElementById(id);
      if (container) {
        container.innerHTML = `<div class="error">${message}</div>`;
      }
    });
  }
}

// Initialize immediately with fallback
console.log('Focus Tracker: Attempting immediate initialization');
let focusTracker;
try {
  focusTracker = new FocusTracker();
  window.focusTracker = focusTracker;
} catch (e) {
  console.error('Focus Tracker: Immediate initialization failed', e);
  document.addEventListener('DOMContentLoaded', () => {
    console.log('Focus Tracker: DOMContentLoaded fallback');
    try {
      focusTracker = new FocusTracker();
      window.focusTracker = focusTracker;
    } catch (e2) {
      console.error('Focus Tracker: DOMContentLoaded initialization also failed', e2);
    }
  });
}