#!/usr/bin/env node

import http from 'http';
import { execSync } from 'child_process';
import { readFileSync, existsSync, mkdirSync, writeFileSync, readdirSync, renameSync, statSync } from 'fs';
import { join } from 'path';
import { fileURLToPath } from 'url';
import { dirname } from 'path';
import { createRequire } from 'module';

const require = createRequire(import.meta.url);
const yaml = require('js-yaml');
const { Client } = require('/home/tony/CascadeProjects/chaba-tony-dell/mcp-servers/mcp-health/node_modules/@modelcontextprotocol/sdk/dist/cjs/client/index.js');
const { StdioClientTransport } = require('/home/tony/CascadeProjects/chaba-tony-dell/mcp-servers/mcp-health/node_modules/@modelcontextprotocol/sdk/dist/cjs/client/stdio.js');

const REPORT_DIR = '/home/tony/CascadeProjects/chaba-tony-dell/reports';
const REPORT_ARCHIVE_DIR = join(REPORT_DIR, 'archive');
const LOG_DIR = '/home/tony/CascadeProjects/chaba-tony-dell/logs';
const KB_DIR = '/home/tony/CascadeProjects/chaba-yomi/docs/kb';
const REPORT_RETENTION_DAYS = 30;

// Ensure directories exist
if (!existsSync(REPORT_DIR)) mkdirSync(REPORT_DIR, { recursive: true });
if (!existsSync(REPORT_ARCHIVE_DIR)) mkdirSync(REPORT_ARCHIVE_DIR, { recursive: true });
if (!existsSync(LOG_DIR)) mkdirSync(LOG_DIR, { recursive: true });
if (!existsSync(KB_DIR)) mkdirSync(KB_DIR, { recursive: true });

const HOST = 'tony-omen.local';
const now = new Date();
const reportDate = now.toISOString().split('T')[0];
const reportTime = now.toTimeString().split(' ')[0].replace(/:/g, '-');
const reportPath = join(REPORT_DIR, `overnight-assessment-${reportDate}-${reportTime}.md`);
const ssotImprovementsPath = '/home/tony/CascadeProjects/chaba-tony-dell/docs/ssot/ssot.improvements.yml';

let report = `# Overnight System Assessment Report - ${reportDate} ${reportTime}\n\n`;
let criticalIssues = [];
let highIssues = [];
let mediumIssues = [];
let lowIssues = [];
let autoCreatedImprovements = [];

function appendSection(title, content) {
  report += `## ${title}\n\n${content}\n\n`;
}

// MCP Client Setup
async function createMCPClient() {
  try {
    const client = new Client({
      name: 'overnight-assessment',
      version: '1.0.0'
    }, {
      capabilities: {}
    });

    const transport = new StdioClientTransport({
      command: '/usr/bin/node',
      args: ['/home/tony/CascadeProjects/chaba-tony-dell/mcp-servers/mcp-health/server.js'],
      env: {
        HEALTH_CONFIG: '/home/tony/CascadeProjects/chaba-tony-dell/docs/ssot/infrastructure/ssot.health.yml',
        HEALTH_SKILL: '/home/tony/CascadeProjects/chaba-tony-dell/.agents/skills/health-check/SKILL.md'
      }
    });

    await client.connect(transport);
    console.log('MCP client connected successfully');
    return client;
  } catch (error) {
    console.error('Failed to create MCP client:', error.message);
    return null;
  }
}

async function closeMCPClient(client) {
  if (client) {
    try {
      await client.close();
      console.log('MCP client closed successfully');
    } catch (error) {
      console.error('Failed to close MCP client:', error.message);
    }
  }
}

// Performance Baseline Analysis Functions
function loadPerformanceBaselines() {
  const baselinePath = '/home/tony/CascadeProjects/chaba-tony-dell/docs/ssot/infrastructure/performance-baselines.yml';
  
  if (!existsSync(baselinePath)) {
    console.log('Performance baselines file not found, skipping baseline analysis');
    return null;
  }

  try {
    const baselineContent = readFileSync(baselinePath, 'utf8');
    const baselineData = yaml.load(baselineContent);
    return baselineData.baselines || null;
  } catch (error) {
    console.error(`Failed to load performance baselines: ${error.message}`);
    return null;
  }
}

function analyzePerformanceAgainstBaselines(currentHealth, baselines) {
  if (!baselines || !currentHealth) {
    return null;
  }

  const analysis = {
    services_analyzed: 0,
    anomalies: [],
    performance_degradation: [],
    performance_improvement: [],
    within_baseline: []
  };

  Object.keys(currentHealth).forEach(serviceName => {
    const baseline = baselines[serviceName];
    const current = currentHealth[serviceName];

    if (!baseline || !current) {
      return;
    }

    analysis.services_analyzed++;

    // Skip low confidence baselines
    if (baseline.data_quality.confidence === 'low') {
      analysis.within_baseline.push({
        service_name: serviceName,
        reason: 'Low confidence baseline (insufficient data)'
      });
      return;
    }

    // Compare response times
    const baselineMedian = baseline.response_time.median;
    const currentMedian = current.avg_response_time;
    
    if (currentMedian > 0) {
      const deviation = ((currentMedian - baselineMedian) / baselineMedian) * 100;
      
      // Anomaly detection: >50% deviation from baseline
      if (Math.abs(deviation) > 50) {
        analysis.anomalies.push({
          service_name: serviceName,
          baseline_median: baselineMedian,
          current_median: currentMedian,
          deviation: deviation.toFixed(1),
          severity: Math.abs(deviation) > 100 ? 'critical' : 'warning'
        });
      } else if (deviation > 20) {
        analysis.performance_degradation.push({
          service_name: serviceName,
          baseline_median: baselineMedian,
          current_median: currentMedian,
          degradation: deviation.toFixed(1)
        });
      } else if (deviation < -20) {
        analysis.performance_improvement.push({
          service_name: serviceName,
          baseline_median: baselineMedian,
          current_median: currentMedian,
          improvement: Math.abs(deviation).toFixed(1)
        });
      } else {
        analysis.within_baseline.push({
          service_name: serviceName,
          baseline_median: baselineMedian,
          current_median: currentMedian,
          deviation: deviation.toFixed(1)
        });
      }
    }
  });

  return analysis;
}

function generateBaselineAnalysisReport(analysis) {
  if (!analysis) {
    return 'No baseline analysis available - baselines not established or insufficient data.';
  }

  let content = `**Services Analyzed:** ${analysis.services_analyzed}\n\n`;

  if (analysis.anomalies.length > 0) {
    content += '### ⚠️ Performance Anomalies Detected\n\n';
    content += '| Service | Baseline (ms) | Current (ms) | Deviation | Severity |\n';
    content += '|---------|---------------|-------------|-----------|----------|\n';
    analysis.anomalies.forEach(anomaly => {
      const deviation = anomaly.deviation > 0 ? `+${anomaly.deviation}%` : `${anomaly.deviation}%`;
      const severity = anomaly.severity === 'critical' ? '🔴 CRITICAL' : '🟡 WARNING';
      content += `| ${anomaly.service_name} | ${anomaly.baseline_median} | ${anomaly.current_median} | ${deviation} | ${severity} |\n`;
    });
    content += '\n';
  }

  if (analysis.performance_degradation.length > 0) {
    content += '### 📉 Performance Degradation\n\n';
    content += '| Service | Baseline (ms) | Current (ms) | Degradation |\n';
    content += '|---------|---------------|-------------|-------------|\n';
    analysis.performance_degradation.forEach(degradation => {
      content += `| ${degradation.service_name} | ${degradation.baseline_median} | ${degradation.current_median} | +${degradation.degradation}% |\n`;
    });
    content += '\n';
  }

  if (analysis.performance_improvement.length > 0) {
    content += '### 📈 Performance Improvements\n\n';
    content += '| Service | Baseline (ms) | Current (ms) | Improvement |\n';
    content += '|---------|---------------|-------------|-------------|\n';
    analysis.performance_improvement.forEach(improvement => {
      content += `| ${improvement.service_name} | ${improvement.baseline_median} | ${improvement.current_median} | -${improvement.improvement}% |\n`;
    });
    content += '\n';
  }

  if (analysis.within_baseline.length > 0) {
    content += '### ✅ Within Baseline\n\n';
    content += `**${analysis.within_baseline.length} services** performing within expected baselines.\n\n`;
    
    // Show a few examples
    const examples = analysis.within_baseline.slice(0, 5);
    if (examples.length > 0) {
      content += '| Service | Baseline (ms) | Current (ms) | Deviation |\n';
      content += '|---------|---------------|-------------|-----------|\n';
      examples.forEach(example => {
        const deviation = example.deviation > 0 ? `+${example.deviation}%` : `${example.deviation}%`;
        content += `| ${example.service_name} | ${example.baseline_median} | ${example.current_median} | ${deviation} |\n`;
      });
      if (analysis.within_baseline.length > 5) {
        content += `... and ${analysis.within_baseline.length - 5} more\n`;
      }
      content += '\n';
    }
  }

  if (analysis.anomalies.length === 0 && analysis.performance_degradation.length === 0) {
    content += '### ✅ Overall Status: Healthy\n\nAll services are performing within expected baselines. No performance anomalies detected.\n\n';
  }

  return content;
}
// MCP Health Server Integration Functions
async function getMCPHealthHistory(client, days = 7) {
  if (!client) {
    console.log('MCP client not available, skipping historical analysis');
    return null;
  }

  try {
    const cutoffDate = new Date();
    cutoffDate.setDate(cutoffDate.getDate() - days);
    const cutoffTimestamp = cutoffDate.toISOString();

    // Use MCP tool to get health history
    const result = await client.callTool({
      name: 'get_health_history',
      arguments: {
        limit: 1000
      }
    });

    if (result.content && result.content.length > 0) {
      // MCP returns data directly in content array
      let historyData = result.content[0].text ? JSON.parse(result.content[0].text) : [];
      
      // Handle different response formats
      if (!Array.isArray(historyData)) {
        // If it's an object with a history property
        if (historyData.history && Array.isArray(historyData.history)) {
          historyData = historyData.history;
        } else {
          console.log('MCP health history data is not in expected format, skipping historical analysis');
          return null;
        }
      }
      
      const filteredHistory = historyData.filter(check => {
        const checkDate = new Date(check.timestamp);
        return checkDate >= cutoffDate;
      });

      const byService = {};
      filteredHistory.forEach(check => {
        if (!byService[check.service_name]) {
          byService[check.service_name] = {
            service_name: check.service_name,
            total_checks: 0,
            healthy_count: 0,
            error_count: 0,
            degraded_count: 0,
            unknown_count: 0,
            avg_response_time: 0,
            first_check: check.timestamp,
            last_check: check.timestamp,
            status_history: []
          };
        }
        byService[check.service_name].total_checks += 1;
        byService[check.service_name].avg_response_time += (check.response_time || 0);
        
        if (byService[check.service_name].first_check > check.timestamp) {
          byService[check.service_name].first_check = check.timestamp;
        }
        if (byService[check.service_name].last_check < check.timestamp) {
          byService[check.service_name].last_check = check.timestamp;
        }
        
        if (check.status === 'healthy') byService[check.service_name].healthy_count += 1;
        else if (check.status === 'error') byService[check.service_name].error_count += 1;
        else if (check.status === 'degraded') byService[check.service_name].degraded_count += 1;
        else byService[check.service_name].unknown_count += 1;
        
        byService[check.service_name].status_history.push({
          status: check.status,
          avg_response_time: check.response_time,
          check_count: 1
        });
      });

      // Calculate overall averages
      Object.values(byService).forEach(service => {
        if (service.total_checks > 0) {
          service.avg_response_time = service.avg_response_time / service.total_checks;
          service.healthy_percentage = (service.healthy_count / service.total_checks) * 100;
        }
      });

      return byService;
    } else {
      console.log('No MCP health history data found');
      return null;
    }
  } catch (error) {
    console.error(`Failed to read MCP health history: ${error.message}`);
    return null;
  }
}

async function getMCPAlerts(client, days = 7) {
  if (!client) {
    console.log('MCP client not available, skipping alert analysis');
    return null;
  }

  try {
    const cutoffDate = new Date();
    cutoffDate.setDate(cutoffDate.getDate() - days);
    const cutoffTimestamp = cutoffDate.toISOString();

    // Use MCP tool to get alerts
    const result = await client.callTool({
      name: 'get_alerts',
      arguments: {}
    });

    if (result.content && result.content.length > 0) {
      // MCP returns data directly in content array
      let alertsData = result.content[0].text ? JSON.parse(result.content[0].text) : [];
      
      // Handle different response formats
      if (!Array.isArray(alertsData)) {
        // If it's an object with an alerts property
        if (alertsData.alerts && Array.isArray(alertsData.alerts)) {
          alertsData = alertsData.alerts;
        } else {
          console.log('MCP alert data is not in expected format, skipping alert analysis');
          return null;
        }
      }
      
      const filteredAlerts = alertsData.filter(alert => {
        const alertDate = new Date(alert.created_at);
        return alertDate >= cutoffDate;
      });

      const byService = {};
      filteredAlerts.forEach(alert => {
        if (!byService[alert.service_name]) {
          byService[alert.service_name] = {
            service_name: alert.service_name,
            total_alerts: 0,
            resolved_count: 0,
            acknowledged_count: 0,
            unresolved_count: 0,
            first_alert: alert.created_at,
            last_alert: alert.created_at,
            alert_types: {}
          };
        }
        byService[alert.service_name].total_alerts += 1;
        byService[alert.service_name].resolved_count += alert.resolved ? 1 : 0;
        byService[alert.service_name].acknowledged_count += alert.acknowledged ? 1 : 0;
        byService[alert.service_name].unresolved_count += alert.resolved ? 0 : 1;
        
        if (!byService[alert.service_name].alert_types[alert.alert_type]) {
          byService[alert.service_name].alert_types[alert.alert_type] = {
            count: 0,
            severity: alert.severity
          };
        }
        byService[alert.service_name].alert_types[alert.alert_type].count += 1;
      });

      return byService;
    } else {
      console.log('No MCP alert data found');
      return null;
    }
  } catch (error) {
    console.error(`Failed to read MCP alerts: ${error.message}`);
    return null;
  }
}

function generateHistoricalTrendReport(healthHistory, alerts) {
  if (!healthHistory) {
    return 'Historical trend analysis unavailable - MCP health database not found.';
  }

  let content = '## Historical Trend Analysis (Last 7 Days)\n\n';
  
  const services = Object.values(healthHistory);
  const totalServices = services.length;
  const healthyServices = services.filter(s => s.healthy_percentage >= 95).length;
  const degradedServices = services.filter(s => s.healthy_percentage >= 80 && s.healthy_percentage < 95).length;
  const unhealthyServices = services.filter(s => s.healthy_percentage < 80).length;

  content += `### Overall Health Trend\n\n`;
  content += `- **Total Services Monitored:** ${totalServices}\n`;
  content += `- **Healthy (>95% uptime):** ${healthyServices} (${((healthyServices/totalServices)*100).toFixed(1)}%)\n`;
  content += `- **Degraded (80-95% uptime):** ${degradedServices} (${((degradedServices/totalServices)*100).toFixed(1)}%)\n`;
  content += `- **Unhealthy (<80% uptime):** ${unhealthyServices} (${((unhealthyServices/totalServices)*100).toFixed(1)}%)\n\n`;

  content += `### Services with Health Issues\n\n`;
  const problematicServices = services.filter(s => s.healthy_percentage < 95);
  
  if (problematicServices.length === 0) {
    content += 'No significant health issues detected in the last 7 days.\n\n';
  } else {
    problematicServices.forEach(service => {
      content += `#### ${service.service_name}\n`;
      content += `- **Health Score:** ${service.healthy_percentage.toFixed(1)}%\n`;
      content += `- **Total Checks:** ${service.total_checks}\n`;
      content += `- **Healthy:** ${service.healthy_count} | **Error:** ${service.error_count} | **Degraded:** ${service.degraded_count} | **Unknown:** ${service.unknown_count}\n`;
      content += `- **Avg Response Time:** ${service.avg_response_time.toFixed(0)}ms\n`;
      content += `- **Last Check:** ${new Date(service.last_check).toLocaleString()}\n\n`;
    });
  }

  if (alerts) {
    content += `### Alert History (Last 7 Days)\n\n`;
    const alertServices = Object.values(alerts);
    const totalAlerts = alertServices.reduce((sum, s) => sum + s.total_alerts, 0);
    const unresolvedAlerts = alertServices.reduce((sum, s) => sum + s.unresolved_count, 0);

    content += `- **Total Alerts:** ${totalAlerts}\n`;
    content += `- **Resolved:** ${totalAlerts - unresolvedAlerts}\n`;
    content += `- **Unresolved:** ${unresolvedAlerts}\n\n`;

    const criticalAlerts = alertServices.filter(s => s.unresolved_count > 0);
    if (criticalAlerts.length > 0) {
      content += `### Services with Unresolved Alerts\n\n`;
      criticalAlerts.forEach(service => {
        content += `#### ${service.service_name}\n`;
        content += `- **Unresolved Alerts:** ${service.unresolved_count}\n`;
        content += `- **Alert Types:** ${Object.entries(service.alert_types).map(([type, info]) => `${type} (${info.severity})`).join(', ')}\n`;
        content += `- **Last Alert:** ${new Date(service.last_alert).toLocaleString()}\n\n`;
      });
    }
  }

  return content;
}

// Automated Issue Creation Functions
function autoCreateImprovement(label, text, priority, category, relatedFiles = []) {
  const improvement = {
    label: label,
    text: text + ` (Auto-generated by overnight assessment on ${new Date().toISOString()})`,
    status: 'pending',
    priority: priority,
    effort: 'TBD',
    category: category,
    discovered: reportDate,
    assessment_ref: `overnight-assessment-${reportDate}`,
    auto_generated: true,
    related_files: relatedFiles,
    tags: ['auto-generated', category]
  };
  
  // Try to get git info
  try {
    const gitInfo = getGitInfo();
    if (gitInfo.commit) {
      improvement.git_commit = gitInfo.commit;
      improvement.git_branch = gitInfo.branch;
      improvement.git_short_commit = gitInfo.commit.substring(0, 8);
    }
  } catch (e) {
    // Git info not available, skip
  }
  
  autoCreatedImprovements.push(improvement);
  console.log(`Auto-created improvement: ${label} (${priority} priority)`);
  return improvement;
}

function getGitInfo() {
  try {
    const commit = execSync('git rev-parse HEAD', { encoding: 'utf8' }).trim();
    const branch = execSync('git rev-parse --abbrev-ref HEAD', { encoding: 'utf8' }).trim();
    return { commit, branch };
  } catch (e) {
    return { commit: null, branch: null };
  }
}

function improvementExists(label) {
  if (!existsSync(ssotImprovementsPath)) return false;

  try {
    const ssotContent = readFileSync(ssotImprovementsPath, 'utf8');
    const baseLabel = label.replace(/\s*\(\d{4}-\d{2}-\d{2}\)\s*$/, '').trim();
    const escaped = baseLabel.replace(/[.*+?^${}()|[\]\\]/g, '\\$&');
    const regex = new RegExp(`label: ${escaped}(\\s*\\(\\d{4}-\\d{2}-\\d{2}\\))?$`, 'm');
    return regex.test(ssotContent);
  } catch (e) {
    return false;
  }
}

function formatImprovementForSSOT(improvement) {
  let yaml = `  - label: ${improvement.label}\n`;
  yaml += `    text: ${improvement.text}\n`;
  yaml += `    status: ${improvement.status}\n`;
  yaml += `    priority: ${improvement.priority}\n`;
  yaml += `    effort: ${improvement.effort}\n`;
  yaml += `    category: ${improvement.category}\n`;
  yaml += `    discovered: ${improvement.discovered}\n`;
  yaml += `    assessment_ref: ${improvement.assessment_ref}\n`;
  yaml += `    auto_generated: true\n`;
  
  // Add git info if available
  if (improvement.git_commit) {
    yaml += `    git_commit: ${improvement.git_commit}\n`;
    yaml += `    git_branch: ${improvement.git_branch}\n`;
    yaml += `    git_short_commit: ${improvement.git_short_commit}\n`;
  }
  
  if (improvement.related_files && improvement.related_files.length > 0) {
    yaml += `    related_files:\n`;
    improvement.related_files.forEach(file => {
      yaml += `      - ${file}\n`;
    });
  }
  
  if (improvement.tags && improvement.tags.length > 0) {
    yaml += `    tags: [${improvement.tags.map(t => `'${t}'`).join(', ')}]\n`;
  }
  
  return yaml;
}

function appendToSSOTSection(sectionTitle, improvements) {
  if (!existsSync(ssotImprovementsPath)) {
    console.log('SSOT improvements file does not exist, skipping auto-creation');
    return;
  }
  
  try {
    const ssotContent = readFileSync(ssotImprovementsPath, 'utf8');
    const lines = ssotContent.split('\n');
    
    // Find the section to append to
    let sectionIndex = -1;
    for (let i = 0; i < lines.length; i++) {
      if (lines[i].includes(`title: ${sectionTitle}`)) {
        sectionIndex = i;
        break;
      }
    }
    
    if (sectionIndex === -1) {
      console.log(`Section ${sectionTitle} not found in SSOT, skipping auto-creation`);
      return;
    }
    
    // Find the items array in the section
    let itemsIndex = -1;
    for (let i = sectionIndex; i < Math.min(sectionIndex + 20, lines.length); i++) {
      if (lines[i].includes('items:')) {
        itemsIndex = i;
        break;
      }
    }
    
    if (itemsIndex === -1) {
      console.log(`Items array not found in section ${sectionTitle}, skipping auto-creation`);
      return;
    }
    
    // Insert improvements after the items: line
    const newLines = [...lines];
    improvements.forEach(improvement => {
      const improvementYaml = formatImprovementForSSOT(improvement);
      newLines.splice(itemsIndex + 1, 0, improvementYaml);
    });
    
    // Write back to file
    writeFileSync(ssotImprovementsPath, newLines.join('\n'));
    console.log(`Appended ${improvements.length} improvements to SSOT section: ${sectionTitle}`);
    
  } catch (e) {
    console.error(`Failed to append improvements to SSOT: ${e.message}`);
  }
}

function syncAutoCreatedImprovements() {
  if (autoCreatedImprovements.length === 0) {
    console.log('No auto-created improvements to sync');
    return;
  }
  
  // Group by priority section
  const byPriority = {
    'High Priority Improvements': [],
    'Medium Priority Improvements': [],
    'Low Priority Improvements': []
  };
  
  autoCreatedImprovements.forEach(imp => {
    const sectionTitle = imp.priority === 'high' ? 'High Priority Improvements' :
                        imp.priority === 'medium' ? 'Medium Priority Improvements' :
                        'Low Priority Improvements';
    byPriority[sectionTitle].push(imp);
  });
  
  // Append to each section
  for (const [sectionTitle, improvements] of Object.entries(byPriority)) {
    if (improvements.length > 0) {
      appendToSSOTSection(sectionTitle, improvements);
    }
  }
}

// Auto-KB Creation Functions
let autoCreatedKBEntries = [];

function autoCreateKBEntry(title, content, tags = []) {
  const timestamp = new Date().toISOString();
  const filename = `${title.toLowerCase().replace(/\s+/g, '-').replace(/[^a-z0-9-]/g, '')}-${timestamp.split('T')[0]}.md`;
  const kbPath = join(KB_DIR, filename);
  
  const kbEntry = {
    title: title,
    content: content,
    tags: tags,
    filename: filename,
    path: kbPath,
    created: timestamp,
    assessment_ref: `overnight-assessment-${reportDate}`
  };
  
  autoCreatedKBEntries.push(kbEntry);
  console.log(`Auto-created KB entry: ${title}`);
  return kbEntry;
}

function kbEntryExists(title) {
  try {
    const kbFiles = readdirSync(KB_DIR).filter(f => f.endsWith('.md'));
    for (const file of kbFiles) {
      const filePath = join(KB_DIR, file);
      const content = readFileSync(filePath, 'utf8');
      if (content.includes(`# ${title}`) || content.includes(title.toLowerCase())) {
        return true;
      }
    }
    return false;
  } catch (e) {
    return false;
  }
}

function formatKBEntry(entry) {
  let kbContent = `# ${entry.title}\n\n`;
  kbContent += `## Context\n\n`;
  kbContent += `Auto-generated by overnight assessment on ${entry.created}\n`;
  kbContent += `Assessment reference: ${entry.assessment_ref}\n\n`;
  kbContent += `## Problem\n\n`;
  kbContent += `${entry.content}\n\n`;
  kbContent += `## Detection\n\n`;
  kbContent += `Automatically detected during overnight assessment based on pattern matching in system health reports.\n\n`;
  kbContent += `## Related Issues\n\n`;
  kbContent += `- Related critical issues: ${criticalIssues.slice(0, 3).join(', ') || 'None'}\n`;
  kbContent += `- Related high issues: ${highIssues.slice(0, 3).join(', ') || 'None'}\n\n`;
  kbContent += `## Prevention\n\n`;
  kbContent += `This entry was created to document recurring patterns. Review and update with specific prevention measures as they are identified.\n\n`;
  kbContent += `## Related Documentation\n\n`;
  kbContent += `- Overnight assessment report: ${entry.assessment_ref}\n`;
  kbContent += `- SSOT health configuration: docs/ssot/infrastructure/ssot.health.yml\n`;
  kbContent += `- System maintenance: scripts/system-maintenance.mjs\n\n`;
  kbContent += `## Tags\n\n`;
  kbContent += `${entry.tags.map(t => t).join(', ')}\n`;
  kbContent += `auto-generated, overnight-assessment, pattern-detection\n`;
  return kbContent;
}

function syncAutoCreatedKBEntries() {
  if (autoCreatedKBEntries.length === 0) {
    console.log('No auto-created KB entries to sync');
    return;
  }
  
  let created = 0;
  let skipped = 0;
  
  for (const entry of autoCreatedKBEntries) {
    if (kbEntryExists(entry.title)) {
      console.log(`KB entry already exists, skipping: ${entry.title}`);
      skipped++;
      continue;
    }
    
    try {
      const kbContent = formatKBEntry(entry);
      writeFileSync(entry.path, kbContent);
      console.log(`Created KB entry: ${entry.filename}`);
      created++;
    } catch (e) {
      console.error(`Failed to create KB entry ${entry.title}: ${e.message}`);
    }
  }
  
  console.log(`KB creation summary: ${created} created, ${skipped} skipped`);
}

function httpGet(url, timeout = 5000) {
  return new Promise((resolve, reject) => {
    const options = {
      hostname: HOST,
      port: 8080,
      path: url,
      method: 'GET',
      timeout: timeout
    };

    const req = http.request(options, (res) => {
      let data = '';
      res.on('data', chunk => data += chunk);
      res.on('end', () => {
        try {
          resolve({ status: res.statusCode, data: JSON.parse(data) });
        } catch (e) {
          resolve({ status: res.statusCode, data: data });
        }
      });
    });

    req.on('error', reject);
    req.on('timeout', () => {
      req.destroy();
      reject(new Error('Request timeout'));
    });

    req.end();
  });
}

function httpGetCustom(hostname, port, path, timeout = 5000) {
  return new Promise((resolve, reject) => {
    const options = {
      hostname: hostname,
      port: port,
      path: path,
      method: 'GET',
      timeout: timeout
    };

    const req = http.request(options, (res) => {
      let data = '';
      res.on('data', chunk => data += chunk);
      res.on('end', () => {
        try {
          resolve({ status: res.statusCode, data: JSON.parse(data) });
        } catch (e) {
          resolve({ status: res.statusCode, data: data });
        }
      });
    });

    req.on('error', reject);
    req.on('timeout', () => {
      req.destroy();
      reject(new Error('Request timeout'));
    });

    req.end();
  });
}

function execCommand(command, timeout = 10000) {
  try {
    return { success: true, output: execSync(command, { encoding: 'utf8', timeout: timeout }) };
  } catch (error) {
    return { success: false, error: error.message };
  }
}

async function checkHealthServices() {
  console.log('Checking health services...');
  let content = '| Service | Status | Response Time | Notes |\n';
  content += '|---------|--------|---------------|-------|\n';

  // Read SSOT health configuration
  const ssotHealthPath = '/home/tony/CascadeProjects/chaba-tony-dell/docs/ssot/infrastructure/ssot.health.home.yml';
  let services = [];
  
  if (existsSync(ssotHealthPath)) {
    try {
      const ssotContent = readFileSync(ssotHealthPath, 'utf8');
      const yaml = require('js-yaml');
      const config = yaml.load(ssotContent);
      
      if (config && config.services) {
        services = config.services.map(svc => ({
          name: svc.name,
          id: svc.id,
          type: svc.type,
          url: svc.url,
          container: svc.container,
          check: svc.check,
          expected_status: svc.expected_status,
          expected_state: svc.expected_state,
          timeout: (svc.timeout || 5) * 1000,
          category: svc.category,
          note: svc.note
        }));
        console.log(`Loaded ${services.length} services from SSOT configuration`);
      }
    } catch (e) {
      console.error(`Failed to parse SSOT health configuration: ${e.message}`);
      // Fallback to hardcoded services
      services = [
        { name: 'Status API', path: '/api/health' },
        { name: 'Yomi API', path: '/api/yomi/health' },
        { name: 'Yomi Summarization', path: '/api/yomi/summarization-status' },
        { name: 'Yomi Rate Limiter', path: '/api/yomi/rate-limiter-status' },
        { name: 'Weaviate', path: '/api/weaviate/v1/nodes' },
      ];
    }
  } else {
    console.log('SSOT health configuration not found, using hardcoded services');
    services = [
      { name: 'Status API', path: '/api/health' },
      { name: 'Yomi API', path: '/api/yomi/health' },
      { name: 'Yomi Summarization', path: '/api/yomi/summarization-status' },
      { name: 'Yomi Rate Limiter', path: '/api/yomi/rate-limiter-status' },
      { name: 'Weaviate', path: '/api/weaviate/v1/nodes' },
    ];
  }

  for (const service of services) {
    const start = Date.now();
    try {
      if (service.type === 'http') {
        // Parse URL to get hostname, port, and path
        const url = new URL(service.url);
        const host = url.hostname;
        const port = parseInt(url.port) || (url.protocol === 'https:' ? 443 : 80);
        const path = url.pathname + url.search;
        
        const result = await httpGetCustom(host, port, path, service.timeout);
        const duration = Date.now() - start;
        const expectedStatus = service.expected_status || 200;
        const status = result.status === expectedStatus ? '✅ Healthy' : '❌ Unhealthy';
        const notes = service.note ? ` - ${service.note}` : '';
        content += `| ${service.name} | ${status} | ${duration}ms | Status: ${result.status}${notes} |\n`;
        
        if (result.status !== expectedStatus && !service.note) {
          criticalIssues.push(`${service.name} returned status ${result.status} (expected ${expectedStatus})`);
          
          // Auto-create improvement if it doesn't exist
          const improvementLabel = `${service.name} Service Failure`;
          if (!improvementExists(improvementLabel)) {
            autoCreateImprovement(
              improvementLabel,
              `${service.name} returned status ${result.status} (expected ${expectedStatus}) - service is unhealthy and needs investigation`,
              'high',
              'service-health',
              [`docs/ssot/infrastructure/ssot.health.home.yml`]
            );
          }
        }
      } else if (service.type === 'container') {
        // Check container status via Docker
        const containerCheck = execCommand(`docker ps --filter "name=${service.container}" --format "{{.Status}}"`);
        const duration = Date.now() - start;
        
        if (containerCheck.success && containerCheck.output.includes('Up')) {
          const status = '✅ Healthy';
          const notes = service.note ? ` - ${service.note}` : '';
          content += `| ${service.name} | ${status} | ${duration}ms | Container: ${containerCheck.output.trim()}${notes} |\n`;
        } else {
          const status = '❌ Unhealthy';
          const errorMsg = containerCheck.success ? containerCheck.output.trim() : containerCheck.error;
          const notes = service.note ? ` - ${service.note}` : '';
          content += `| ${service.name} | ${status} | ${duration}ms | ${errorMsg}${notes} |\n`;
          
          // Only create improvement if service is not marked as offline
          if (!service.note) {
            criticalIssues.push(`${service.name} container is not running`);
            
            // Auto-create improvement if it doesn't exist
            const improvementLabel = `${service.name} Container Down`;
            if (!improvementExists(improvementLabel)) {
              autoCreateImprovement(
                improvementLabel,
                `${service.name} container is not running - needs investigation and restart`,
                'high',
                'service-health',
                [`docs/ssot/infrastructure/ssot.health.home.yml`]
              );
            }
          }
        }
      } else if (service.type === 'local') {
        // Check local command execution
        const checkCommand = service.check || service.command;
        if (!checkCommand) {
          const status = '❓ Unknown';
          const notes = service.note ? ` - ${service.note}` : '';
          content += `| ${service.name} | ${status} | ${Date.now() - start}ms | No check command defined${notes} |\n`;
          mediumIssues.push(`${service.name} has no check command defined`);
        } else {
          const localCheck = execCommand(checkCommand);
          const duration = Date.now() - start;
          
          if (localCheck.success) {
            const status = '✅ Healthy';
            const output = localCheck.output.trim() || 'No output';
            const notes = service.note ? ` - ${service.note}` : '';
            content += `| ${service.name} | ${status} | ${duration}ms | ${output.substring(0, 50)}${output.length > 50 ? '...' : ''}${notes} |\n`;
          } else {
            const status = '❌ Unhealthy';
            const errorMsg = localCheck.error || 'Command failed';
            const notes = service.note ? ` - ${service.note}` : '';
            content += `| ${service.name} | ${status} | ${duration}ms | ${errorMsg}${notes} |\n`;
            
            // Only create improvement if service is not marked as offline
            if (!service.note) {
              mediumIssues.push(`${service.name} check failed: ${errorMsg}`);
            }
          }
        }
      } else {
        content += `| ${service.name} | ❓ Unknown | ${Date.now() - start}ms | Unknown service type: ${service.type} |\n`;
      }
    } catch (error) {
      const duration = Date.now() - start;
      content += `| ${service.name} | ❌ Error | ${duration}ms | ${error.message} |\n`;
      criticalIssues.push(`${service.name} failed: ${error.message}`);
    }
  }

  // Check Docker containers
  const containerCheck = execCommand('docker compose ps');
  if (containerCheck.success) {
    content += '\n### Docker Containers\n\n';
    content += '```\n' + containerCheck.output.trim() + '\n```\n';
    
    // Check for non-running containers
    const lines = containerCheck.output.split('\n');
    for (const line of lines) {
      if (line.includes('Exited') || line.includes('dead')) {
        const serviceName = line.split(/\s+/)[0];
        if (serviceName && !serviceName.includes('NAME')) {
          mediumIssues.push(`Docker container ${serviceName} is not running`);
        }
      }
    }
  } else {
    content += `\nFailed to check Docker containers: ${containerCheck.error}\n`;
    mediumIssues.push('Could not check Docker container status');
  }

  appendSection('Health Check Results', content);
}

async function checkGPUStatus() {
  console.log('Checking GPU status...');
  let content = '';

  try {
    const result = await httpGet('/api/gpu/status');
    if (result.status === 200 && result.data.gpus && result.data.gpus.length > 0) {
      const gpu = result.data.gpus[0];
      const vramPercent = Math.round((gpu.memory_used_mb / gpu.memory_total_mb) * 100);
      
      content += `**GPU Model:** ${gpu.name || 'Unknown'}\n\n`;
      content += `**VRAM Usage:** ${gpu.memory_used_mb}MB / ${gpu.memory_total_mb}MB (${vramPercent}%)\n\n`;
      content += `**GPU Utilization:** ${gpu.utilization_percent}%\n\n`;
      content += `**Temperature:** ${gpu.temperature_c}°C\n\n`;
      
      if (gpu.temperature_c > 85) {
        criticalIssues.push(`GPU temperature critical: ${gpu.temperature_c}°C`);
        
        const improvementLabel = `GPU Temperature Critical`;
        if (!improvementExists(improvementLabel)) {
          autoCreateImprovement(
            improvementLabel,
            `GPU temperature critical at ${gpu.temperature_c}°C - immediate cooling intervention required`,
            'high',
            'gpu',
            [`docs/ssot/gpu.yml`]
          );
        }
      } else if (gpu.temperature_c > 80) {
        highIssues.push(`GPU temperature elevated: ${gpu.temperature_c}°C`);
        
        const improvementLabel = `GPU Temperature Elevated`;
        if (!improvementExists(improvementLabel)) {
          autoCreateImprovement(
            improvementLabel,
            `GPU temperature elevated at ${gpu.temperature_c}°C - investigate cooling and workload`,
            'high',
            'gpu',
            [`docs/ssot/gpu.yml`]
          );
        }
      } else if (gpu.temperature_c > 75) {
        mediumIssues.push(`GPU temperature moderately elevated: ${gpu.temperature_c}°C`);
      }

      if (vramPercent > 90) {
        highIssues.push(`GPU VRAM usage critical: ${vramPercent}%`);
        
        const improvementLabel = `GPU VRAM Usage Critical`;
        if (!improvementExists(improvementLabel)) {
          autoCreateImprovement(
            improvementLabel,
            `GPU VRAM usage critical at ${vramPercent}% - investigate memory leaks or optimize GPU workload`,
            'high',
            'gpu',
            [`docs/ssot/gpu.yml`]
          );
        }
      }
      
      // Show processes
      if (result.data.processes && result.data.processes.length > 0) {
        content += '**Active GPU Processes:**\n\n';
        result.data.processes.forEach(proc => {
          content += `- PID ${proc.pid}: ${proc.name} (${proc.memory_used_mb}MB)\n`;
        });
        content += '\n';
      }
    } else {
      content += `Failed to get GPU status: Invalid response format\n`;
      highIssues.push('GPU status endpoint returned invalid data');
    }
  } catch (error) {
    content += `Failed to get GPU status: ${error.message}\n`;
    highIssues.push(`GPU status check failed: ${error.message}`);
  }

  // Check GPU queue
  try {
    const result = await httpGetCustom(HOST, 3001, '/api/gpu-queue/status');
    if (result.status === 200) {
      const queue = result.data;
      content += '\n**GPU Queue Status:**\n\n';
      content += `- Pending: ${queue.pending || 0}\n`;
      content += `- Running: ${queue.running || 0}\n`;
      content += `- Completed: ${queue.completed || 0}\n`;
      content += `- Failed: ${queue.failed || 0}\n`;
      
      if (queue.running > 1) {
        mediumIssues.push(`Multiple jobs running in GPU queue: ${queue.running}`);
      }
      if (queue.failed > 0) {
        mediumIssues.push(`Failed jobs in GPU queue: ${queue.failed}`);
      }
    }
  } catch (error) {
    content += `\nFailed to get GPU queue status: ${error.message}\n`;
  }

  // CPU temperature check via thermal zones
  try {
    const thermalOutput = runCommand('cat /sys/class/thermal/thermal_zone*/temp 2>/dev/null');
    if (thermalOutput.success) {
      const temps = thermalOutput.output.trim().split('\n')
        .map(t => parseInt(t) / 1000)
        .filter(t => !isNaN(t) && t > 20);
      if (temps.length > 0) {
        const maxTemp = Math.max(...temps);
        content += `\n**CPU Temperature (max):** ${maxTemp.toFixed(1)}°C\n\n`;
        if (maxTemp > 90) {
          highIssues.push(`CPU temperature critical: ${maxTemp.toFixed(1)}°C`);
          const label = 'CPU Temperature Critical';
          if (!improvementExists(label)) {
            autoCreateImprovement(label,
              `CPU temperature critical at ${maxTemp.toFixed(1)}°C - check thermal paste, cooling, and sustained workload`,
              'high', 'performance', ['docs/ssot/infrastructure/ssot.gpu.yml']);
          }
        } else if (maxTemp > 80) {
          mediumIssues.push(`CPU temperature elevated: ${maxTemp.toFixed(1)}°C`);
        }
      }
    }
  } catch (e) { /* thermal check optional */ }

  // Check for unexpected VRAM holders (processes not in known-good list)
  try {
    const nvsmiOutput = runCommand("nvidia-smi --query-compute-apps=pid,used_memory --format=csv,noheader 2>/dev/null");
    if (nvsmiOutput.success) {
      const KNOWN_SERVICES = ['llama-server', 'embedding-service', 'uvicorn', 'python', 'Xorg'];
      const lines = nvsmiOutput.output.trim().split('\n').filter(Boolean);
      let unexpectedVram = 0;
      lines.forEach(line => {
        const [pidStr, memStr] = line.split(',').map(s => s.trim());
        const pid = parseInt(pidStr);
        const memMb = parseInt(memStr);
        if (pid && memMb > 500) {
          const cmd = runCommand(`ps -p ${pid} -o comm= 2>/dev/null`).output.trim();
          const isKnown = KNOWN_SERVICES.some(s => cmd.includes(s));
          if (!isKnown) {
            unexpectedVram += memMb;
            highIssues.push(`Unexpected process holding ${memMb}MB VRAM: PID ${pid} (${cmd})`);
          }
        }
      });
      if (unexpectedVram > 0) {
        content += `\n⚠️ **Unexpected VRAM holders:** ${unexpectedVram}MB across unknown processes\n\n`;
      }
    }
  } catch (e) { /* vram check optional */ }

  appendSection('GPU & Queue Status', content);
}

async function checkYomiSystem() {
  console.log('Checking Yomi system...');
  let content = '';

  try {
    const result = await httpGet('/api/yomi/rate-limiter-status');
    if (result.status === 200) {
      const rl = result.data;
      content += '**Rate Limiter Status:**\n\n';
      content += `- Summary Running: ${rl.summary?.running || 0}\n`;
      content += `- Summary Queued: ${rl.summary?.queued || 0}\n`;
      content += `- Daily Running: ${rl.daily?.running || 0}\n`;
      content += `- Daily Queued: ${rl.daily?.queued || 0}\n`;
      
      if ((rl.summary?.queued || 0) > 5) {
        mediumIssues.push(`High queue count in summary rate limiter: ${rl.summary?.queued}`);
      }
    }
  } catch (error) {
    content += `Failed to get rate limiter status: ${error.message}\n`;
  }

  try {
    const result = await httpGet('/api/yomi/summarization-status');
    if (result.status === 200) {
      const status = result.data;
      content += '\n**Summarization Status:**\n\n';
      
      // Parse actual API response structure
      const conversations = status.conversations || {};
      const dailySummaries = status.dailySummaries || {};
      
      content += `- Total Conversations: ${conversations.total || 0}\n`;
      content += `- With Summaries: ${conversations.withSummary || 0}\n`;
      content += `- Average Quality: ${conversations.avgSummaryQuality || 0}%\n`;
      content += `- Daily Summaries: ${dailySummaries.totalSummaries || 0}\n`;
      content += `- Conversations with Daily Summaries: ${dailySummaries.conversationsWithSummaries || 0}\n`;
      content += `- Last Daily Summary Update: ${dailySummaries.lastUpdated || 'Never'}\n`;
      content += `- Latest Summary Date: ${dailySummaries.latestSummaryDate || 'Never'}\n`;
      
      // Check for issues
      if ((conversations.total || 0) > 0 && (conversations.withSummary || 0) === 0) {
        mediumIssues.push('No conversation summaries generated despite having conversations');
      }
      
      if ((dailySummaries.totalSummaries || 0) === 0 && (conversations.total || 0) > 0) {
        mediumIssues.push('No daily summaries generated despite having conversations');
      }
      
      if ((conversations.avgSummaryQuality || 0) < 50) {
        mediumIssues.push(`Low average summary quality: ${conversations.avgSummaryQuality}%`);
      }
    }
  } catch (error) {
    content += `\nFailed to get summarization status: ${error.message}\n`;
  }

  appendSection('Yomi System Health', content);
}

function checkSystemResources() {
  console.log('Checking system resources...');
  let content = '';

  // Disk usage
  const diskCheck = execCommand('df -h / | tail -1');
  if (diskCheck.success) {
    content += '**Disk Usage:**\n```\n' + diskCheck.output.trim() + '\n```\n';
    const diskUsage = diskCheck.output.match(/(\d+)%/);
    if (diskUsage && parseInt(diskUsage[1]) > 90) {
      criticalIssues.push(`Disk usage critical: ${diskUsage[1]}%`);
      
      const improvementLabel = `Disk Usage Critical`;
      if (!improvementExists(improvementLabel)) {
        autoCreateImprovement(
          improvementLabel,
          `Disk usage critical at ${diskUsage[1]}% - immediate cleanup and storage management required`,
          'high',
          'storage',
          [`docker-compose.yml`]
        );
      }
    } else if (diskUsage && parseInt(diskUsage[1]) > 80) {
      highIssues.push(`Disk usage elevated: ${diskUsage[1]}%`);
      
      const improvementLabel = `Disk Usage Elevated`;
      if (!improvementExists(improvementLabel)) {
        autoCreateImprovement(
          improvementLabel,
          `Disk usage elevated at ${diskUsage[1]}% - plan storage cleanup and optimization`,
          'medium',
          'storage',
          [`docker-compose.yml`]
        );
      }
    }
  }

  // Memory usage
  const memCheck = execCommand('free -h');
  if (memCheck.success) {
    content += '\n**Memory Usage:**\n```\n' + memCheck.output.trim() + '\n```\n';
  }

  // CPU load
  const loadCheck = execCommand('uptime');
  if (loadCheck.success) {
    content += '\n**System Load:**\n```\n' + loadCheck.output.trim() + '\n```\n';
  }

  appendSection('System Resources', content);
}

function checkConfiguration() {
  console.log('Checking configuration...');
  let content = '';

  // Check SSOT files
  const ssotFiles = [
    '/home/tony/CascadeProjects/chaba-tony-dell/docs/ssot/infrastructure/ssot.health.home.yml',
    '/home/tony/CascadeProjects/chaba-tony-dell/docs/ssot/infrastructure/ssot.health.yml',
  ];

  content += '**SSOT Configuration Files:**\n\n';
  for (const file of ssotFiles) {
    if (existsSync(file)) {
      content += `- ✅ ${file}\n`;
    } else {
      content += `- ❌ ${file} (missing)\n`;
      lowIssues.push(`SSOT file missing: ${file}`);
    }
  }

  // Check for IP addresses in config files (should use .local hostnames)
  const ipCheck = execCommand('grep -r "192\\.168\\." /home/tony/CascadeProjects/chaba-tony-dell/docs/overview/ 2>/dev/null || true');
  if (ipCheck.success && ipCheck.output) {
    content += '\n**IP Addresses Found in Config:**\n```\n' + ipCheck.output + '\n```\n';
    if (ipCheck.output.trim()) {
      lowIssues.push('IP addresses found in config files (should use .local hostnames)');
    }
  }

  appendSection('Configuration Validation', content);
}

async function checkSecurityStatus() {
  console.log('Checking security status...');
  let content = '';

  try {
    const securityCheck = execCommand('node /home/tony/CascadeProjects/chaba-tony-dell/scripts/security-scan.mjs', 300000); // 5 minute timeout
    
    if (securityCheck.success) {
      content += '**Security Scan Results:**\n\n';
      
      // Try to parse the security results
      try {
        const securityResultsPath = '/home/tony/CascadeProjects/chaba-tony-dell/security-results.json';
        if (existsSync(securityResultsPath)) {
          const securityData = JSON.parse(readFileSync(securityResultsPath, 'utf8'));
          const summary = securityData.summary || {};
          
          content += `- **Total Vulnerabilities:** ${summary.totalVulnerabilities || 0}\n`;
          content += `- **Docker Vulnerabilities:** ${summary.dockerVulnerabilities || 0}\n`;
          content += `- **Python Vulnerabilities:** ${summary.pythonVulnerabilities || 0}\n`;
          content += `- **Node.js Vulnerabilities:** ${summary.nodeVulnerabilities || 0}\n`;
          content += `- **Stale Container Images:** ${summary.staleContainerImages || 0}\n`;
          content += `- **Overall Status:** ${summary.overallStatus || 'unknown'}\n\n`;
          
          // Check for security issues
          if (summary.totalVulnerabilities > 0) {
            highIssues.push(`Security scan found ${summary.totalVulnerabilities} vulnerabilities`);
            
            // Create improvement if critical vulnerabilities found
            if (summary.dockerVulnerabilities > 0) {
              const improvementLabel = `Docker Container Security Vulnerabilities`;
              if (!improvementExists(improvementLabel)) {
                autoCreateImprovement(
                  improvementLabel,
                  `Docker containers have ${summary.dockerVulnerabilities} security vulnerabilities - update images to patch HIGH/CRITICAL issues`,
                  'high',
                  'security',
                  [`docker-compose.yml`, `scripts/security-scan.mjs`]
                );
              }
            }
            
            if (summary.nodeVulnerabilities > 0) {
              const improvementLabel = `Node.js Security Vulnerabilities`;
              if (!improvementExists(improvementLabel)) {
                autoCreateImprovement(
                  improvementLabel,
                  `Node.js dependencies have ${summary.nodeVulnerabilities} security vulnerabilities - run npm audit fix`,
                  'medium',
                  'security',
                  [`package.json`, `scripts/security-scan.mjs`]
                );
              }
            }
          }
          
          if (summary.staleContainerImages > 0) {
            mediumIssues.push(`${summary.staleContainerImages} stale container images found (>90 days old)`);
            
            const improvementLabel = `Stale Container Images`;
            if (!improvementExists(improvementLabel)) {
              autoCreateImprovement(
                improvementLabel,
                `${summary.staleContainerImages} container images are older than 90 days - consider rebuilding with updated base images`,
                'medium',
                'security',
                [`docker-compose.yml`, `scripts/security-scan.mjs`]
              );
            }
          }
          
          // Show vulnerable Docker images
          if (securityData.dockerImages && securityData.dockerImages.length > 0) {
            const vulnerableImages = securityData.dockerImages.filter(img => img.vulnerable);
            if (vulnerableImages.length > 0) {
              content += '**Vulnerable Docker Images:**\n\n';
              vulnerableImages.forEach(img => {
                content += `- **${img.image}**: ${img.vulnerabilityCount} vulnerabilities\n`;
              });
              content += '\n';
            }
          }
          
          // Show vulnerable Python dependencies
          if (securityData.pythonDependencies && securityData.pythonDependencies.length > 0) {
            const vulnerableDeps = securityData.pythonDependencies.filter(dep => dep.vulnerable);
            if (vulnerableDeps.length > 0) {
              content += '**Vulnerable Python Dependencies:**\n\n';
              vulnerableDeps.forEach(dep => {
                content += `- **${dep.file}**: ${dep.vulnerabilityCount} vulnerabilities\n`;
              });
              content += '\n';
            }
          }
          
          // Show vulnerable Node.js dependencies
          if (securityData.nodeDependencies && securityData.nodeDependencies.length > 0) {
            const vulnerableDeps = securityData.nodeDependencies.filter(dep => dep.vulnerable);
            if (vulnerableDeps.length > 0) {
              content += '**Vulnerable Node.js Dependencies:**\n\n';
              vulnerableDeps.forEach(dep => {
                content += `- **${dep.directory}**: ${dep.vulnerabilityCount} vulnerabilities\n`;
              });
              content += '\n';
            }
          }
          
          // Show stale images
          if (securityData.containerAges && securityData.containerAges.length > 0) {
            const staleImages = securityData.containerAges.filter(img => img.stale);
            if (staleImages.length > 0) {
              content += '**Stale Container Images:**\n\n';
              staleImages.forEach(img => {
                content += `- **${img.image}**: ${img.ageInDays} days old\n`;
              });
              content += '\n';
            }
          }
        }
      } catch (parseError) {
        content += 'Security scan completed but results could not be parsed.\n';
        content += 'Raw output:\n```\n' + securityCheck.output + '\n```\n';
      }
    } else {
      content += 'Security scan failed: ' + securityCheck.error + '\n';
      mediumIssues.push('Security scan failed to execute');
    }
  } catch (error) {
    content += 'Failed to run security scan: ' + error.message + '\n';
    mediumIssues.push('Security scan encountered error');
  }

  appendSection('Security & Dependency Status', content);
}

function checkImprovementsSSOT() {
  console.log('Checking improvements SSOT...');
  let content = '';

  const ssotPath = '/home/tony/CascadeProjects/chaba-tony-dell/docs/ssot/ssot.improvements.yml';
  if (existsSync(ssotPath)) {
    content += '**Improvements SSOT:** ✅ Found at ' + ssotPath + '\n\n';
    
    try {
      const ssotContent = readFileSync(ssotPath, 'utf8');
      const pendingItems = (ssotContent.match(/status: pending/g) || []).length;
      const plannedItems = (ssotContent.match(/status: planned/g) || []).length;
      const completedItems = (ssotContent.match(/status: completed/g) || []).length;
      
      content += '**Improvement Status:**\n\n';
      content += '- Pending: ' + pendingItems + '\n';
      content += '- Planned: ' + plannedItems + '\n';
      content += '- Completed: ' + completedItems + '\n\n';
      
      if (pendingItems > 5) {
        mediumIssues.push('High number of pending improvements: ' + pendingItems);
      }
      
      // Validate dependencies
      const dependencyValidation = validateDependencies(ssotContent);
      if (dependencyValidation.issues.length > 0) {
        content += '**Dependency Validation:** ⚠️ Issues Found\n\n';
        dependencyValidation.issues.forEach(issue => {
          content += '- ' + issue + '\n';
        });
        content += '\n';
        
        if (dependencyValidation.criticalIssues > 0) {
          highIssues.push('Critical dependency issues found: ' + dependencyValidation.criticalIssues);
        } else {
          mediumIssues.push('Dependency validation issues found: ' + dependencyValidation.issues.length);
        }
      } else {
        content += '**Dependency Validation:** ✅ No issues found\n\n';
      }
      
      // Check for blocked improvements
      const blockedImprovements = findBlockedImprovements(ssotContent);
      if (blockedImprovements.length > 0) {
        content += '**Blocked Improvements:** ' + blockedImprovements.length + '\n\n';
        blockedImprovements.forEach(blocked => {
          content += '- **' + blocked.label + '** blocked by: ' + blocked.blockedBy.join(', ') + '\n';
        });
        content += '\n';
      }
      
      // Check for blocking improvements
      const blockingImprovements = findBlockingImprovements(ssotContent);
      if (blockingImprovements.length > 0) {
        content += '**Blocking Improvements:** ' + blockingImprovements.length + '\n\n';
        blockingImprovements.forEach(blocking => {
          content += '- **' + blocking.label + '** blocking: ' + blocking.blocking.join(', ') + '\n';
        });
        content += '\n';
      }
      
      // Analyze impact scores
      const impactAnalysis = analyzeImpactScores(ssotContent);
      content += '**Impact Analysis:**\n\n';
      content += '- High Impact (≥8/10): ' + impactAnalysis.highImpactCount + '\n';
      content += '- Medium Impact (5-7/10): ' + impactAnalysis.mediumImpactCount + '\n';
      content += '- Low Impact (<5/10): ' + impactAnalysis.lowImpactCount + '\n\n';
      
      if (impactAnalysis.highImpactCount > 0) {
        content += '**High Impact Improvements:**\n\n';
        impactAnalysis.highImpactItems.forEach(item => {
          content += '- **' + item.label + '** (' + item.overall_impact + '/10)\n';
        });
        content += '\n';
      }
      
      if (impactAnalysis.mediumImpactCount > 0) {
        content += '**Medium Impact Improvements:**\n\n';
        impactAnalysis.mediumImpactItems.forEach(item => {
          content += '- **' + item.label + '** (' + item.overall_impact + '/10)\n';
        });
        content += '\n';
      }
      
    } catch (e) {
      content += 'Failed to parse improvements SSOT: ' + e.message + '\n';
    }
  } else {
    content += '**Improvements SSOT:** ❌ Not found\n\n';
    lowIssues.push('Improvements SSOT file not found');
  }

  appendSection('Improvements Tracking', content);
}

function analyzeImpactScores(ssotContent) {
  const improvements = parseImprovementsFromScoring(ssotContent);
  const highImpactItems = [];
  const mediumImpactItems = [];
  const lowImpactItems = [];
  let highImpactCount = 0;
  let mediumImpactCount = 0;
  let lowImpactCount = 0;
  
  improvements.forEach(imp => {
    if (imp.status === 'pending' || imp.status === 'planned') {
      const overall = calculateOverallImpact(imp);
      if (overall >= 8) {
        highImpactCount++;
        highImpactItems.push({
          label: imp.label,
          overall_impact: overall
        });
      } else if (overall >= 5) {
        mediumImpactCount++;
        mediumImpactItems.push({
          label: imp.label,
          overall_impact: overall
        });
      } else {
        lowImpactCount++;
        lowImpactItems.push({
          label: imp.label,
          overall_impact: overall
        });
      }
    }
  });
  
  return { 
    highImpactCount, 
    highImpactItems,
    mediumImpactCount,
    mediumImpactItems,
    lowImpactCount,
    lowImpactItems
  };
}

function calculateOverallImpact(improvement) {
  // Weighted average: business 30%, technical 30%, user experience 20%, cost savings 20%
  const weights = {
    business: 0.3,
    technical: 0.3,
    user_experience: 0.2,
    cost_savings: 0.2
  };
  
  const business = improvement.business_impact !== null ? improvement.business_impact : 5;
  const technical = improvement.technical_impact !== null ? improvement.technical_impact : 5;
  const user_experience = improvement.user_experience_impact !== null ? improvement.user_experience_impact : 5;
  const cost_savings = improvement.cost_savings_impact !== null ? improvement.cost_savings_impact : 5;
  
  const overall = (
    (business * weights.business) +
    (technical * weights.technical) +
    (user_experience * weights.user_experience) +
    (cost_savings * weights.cost_savings)
  );
  
  return Math.round(overall * 10) / 10; // Round to 1 decimal place
}

function validateDependencies(ssotContent) {
  const issues = [];
  let criticalIssues = 0;
  
  // Parse all improvements
  const improvements = parseImprovementsFromScoring(ssotContent);
  const improvementLabels = new Set(improvements.map(imp => imp.label));
  
  // Check each improvement's dependencies
  for (const improvement of improvements) {
    if (improvement.depends_on && improvement.depends_on.length > 0) {
      for (const dep of improvement.depends_on) {
        // Check if dependency exists
        if (!improvementLabels.has(dep)) {
          issues.push(`Missing dependency: "${improvement.label}" depends on non-existent "${dep}"`);
          criticalIssues++;
        }
        
        // Check for self-dependency
        if (dep === improvement.label) {
          issues.push(`Self-dependency: "${improvement.label}" cannot depend on itself`);
          criticalIssues++;
        }
        
        // Check for circular dependencies
        if (hasCircularDependency(improvement.label, dep, improvements)) {
          issues.push(`Circular dependency detected involving "${improvement.label}" and "${dep}"`);
          criticalIssues++;
        }
      }
    }
    
    // Check priority consistency with dependencies
    if (improvement.depends_on && improvement.depends_on.length > 0) {
      for (const dep of improvement.depends_on) {
        const depImprovement = improvements.find(imp => imp.label === dep);
        if (depImprovement && depImprovement.priority) {
          const priorityOrder = { 'high': 3, 'medium': 2, 'low': 1 };
          const currentPriority = priorityOrder[improvement.priority] || 0;
          const depPriority = priorityOrder[depImprovement.priority] || 0;
          
          if (currentPriority > depPriority) {
            issues.push(`Priority inconsistency: "${improvement.label}" (${improvement.priority}) depends on lower priority "${dep}" (${depImprovement.priority})`);
          }
        }
      }
    }
  }
  
  return { issues, criticalIssues };
}

// Import parseImprovements from impact-scoring.mjs
import { parseImprovements as parseImprovementsFromScoring } from './impact-scoring.mjs';

function hasCircularDependency(startLabel, currentLabel, improvements, visited = new Set()) {
  if (visited.has(currentLabel)) {
    return currentLabel === startLabel;
  }
  
  visited.add(currentLabel);
  
  const currentImprovement = improvements.find(imp => imp.label === currentLabel);
  if (!currentImprovement || !currentImprovement.depends_on) {
    return false;
  }
  
  for (const dep of currentImprovement.depends_on) {
    if (hasCircularDependency(startLabel, dep, improvements, visited)) {
      return true;
    }
  }
  
  return false;
}

function findBlockedImprovements(ssotContent) {
  const improvements = parseImprovementsFromScoring(ssotContent);
  const blocked = [];
  
  for (const improvement of improvements) {
    if (improvement.depends_on && improvement.depends_on.length > 0) {
      const incompleteDeps = improvement.depends_on.filter(dep => {
        const depImprovement = improvements.find(imp => imp.label === dep);
        return !depImprovement || depImprovement.status !== 'completed';
      });
      
      if (incompleteDeps.length > 0) {
        blocked.push({
          label: improvement.label,
          blockedBy: incompleteDeps,
          status: improvement.status,
          reason: 'Dependencies not completed'
        });
      }
    }
  }
  
  return blocked;
}

function findBlockingImprovements(ssotContent) {
  const improvements = parseImprovementsFromScoring(ssotContent);
  const blocking = [];
  
  for (const improvement of improvements) {
    if (improvement.blocks && improvement.blocks.length > 0) {
      if (improvement.status !== 'completed') {
        blocking.push({
          label: improvement.label,
          blocking: improvement.blocks,
          status: improvement.status,
          reason: 'Not completed, blocking dependent improvements'
        });
      }
    }
  }
  
  return blocking;
}

function generateSummary() {
  console.log('Generating summary...');
  let content = '';

  const totalServices = 12; // Approximate based on SSOT
  const healthyServices = totalServices - criticalIssues.length - highIssues.length;
  const healthScore = Math.round((healthyServices / totalServices) * 100);

  content += `**Overall Health Score:** ${healthScore}/100\n\n`;
  content += `**Assessment Time:** ${new Date().toISOString()}\n\n`;
  content += `**Total Issues Found:** ${criticalIssues.length + highIssues.length + mediumIssues.length + lowIssues.length}\n\n`;

  if (criticalIssues.length > 0) {
    content += '### 🚨 Critical Issues (Immediate Action Required)\n\n';
    criticalIssues.forEach(issue => {
      content += `- ${issue}\n`;
    });
    content += '\n';
  }

  if (highIssues.length > 0) {
    content += '### ⚠️ High Priority Issues\n\n';
    highIssues.forEach(issue => {
      content += `- ${issue}\n`;
    });
    content += '\n';
  }

  if (mediumIssues.length > 0) {
    content += '### 📋 Medium Priority Issues\n\n';
    mediumIssues.forEach(issue => {
      content += `- ${issue}\n`;
    });
    content += '\n';
  }

  if (lowIssues.length > 0) {
    content += '### 💡 Low Priority Issues\n\n';
    lowIssues.forEach(issue => {
      content += `- ${issue}\n`;
    });
    content += '\n';
  }

  if (criticalIssues.length === 0 && highIssues.length === 0) {
    content += '### ✅ System Status: Healthy\n\nNo critical or high priority issues found. System is operating normally.\n\n';
  }

  appendSection('Executive Summary', content);
}

function generateRecommendations() {
  let recommendations = '## Improvement Recommendations\n\n';
  
  if (criticalIssues.length > 0) {
    recommendations += '### Immediate Actions Required\n\n';
    criticalIssues.forEach(issue => {
      recommendations += `- Investigate and resolve: ${issue}\n`;
    });
    recommendations += '\n';
  }

  if (highIssues.length > 0) {
    recommendations += '### Next Sprint Priorities\n\n';
    highIssues.forEach(issue => {
      recommendations += `- Address: ${issue}\n`;
    });
    recommendations += '\n';
  }

  recommendations += '### Ongoing Maintenance\n\n';
  recommendations += '- Review assessment reports regularly\n';
  recommendations += '- Monitor GPU temperature and VRAM usage trends\n';
  recommendations += '- Keep Docker images and dependencies updated\n';
  recommendations += '- Review and clean up GPU queue failures\n';
  recommendations += '- Monitor disk usage growth patterns\n';
  recommendations += '- Track improvements in ssot.improvements.yml\n';
  recommendations += '- Review security scan results and patch vulnerabilities\n';
  recommendations += '- Monitor container image ages and update stale images\n';
  recommendations += '- Review auto-created KB entries for accuracy and completeness\n';

  report += recommendations;
}

// KB-worthy issue detection
function detectKBWorthyIssues() {
  // Only create KB entries for specific, significant issues
  // More conservative approach to avoid creating generic entries
  
  // Check for specific hostname resolution issues
  const reportLower = report.toLowerCase();
  
  // Hostname resolution issues - specific pattern
  if (reportLower.includes('hostname') && reportLower.includes('etc/hosts') && 
      (reportLower.includes('resolution') || reportLower.includes('dns'))) {
    const content = `Hostname resolution issues detected during overnight assessment on ${reportDate}. 
The system showed patterns indicating /etc/hosts configuration problems. 
Related issues: ${criticalIssues.filter(i => i.includes('hostname') || i.includes('tony-omen')).slice(0, 2).join(', ') || 'Network connectivity issues detected'}. 
This suggests the /etc/hosts file may have incorrect IP mappings for local hostnames.`;
    
    if (!kbEntryExists('Hostname Resolution Issues')) {
      autoCreateKBEntry('Hostname Resolution Issues', content, 
        ['network', 'dns', 'troubleshooting', 'hostname-resolution']);
    }
  }
  
  // GPU VRAM exhaustion - specific pattern
  if (reportLower.includes('gpu') && reportLower.includes('vram') && 
      (reportLower.includes('critical') || reportLower.includes('90%'))) {
    const content = `GPU VRAM exhaustion detected during overnight assessment on ${reportDate}.
System showed critical GPU memory usage patterns. 
Related issues: ${criticalIssues.filter(i => i.includes('gpu') || i.includes('vram')).slice(0, 2).join(', ') || 'GPU memory pressure detected'}. 
This indicates GPU memory constraints affecting system performance.`;
    
    if (!kbEntryExists('GPU VRAM Exhaustion')) {
      autoCreateKBEntry('GPU VRAM Exhaustion', content, 
        ['gpu', 'memory', 'performance', 'vram']);
    }
  }
  
  // Disk space critical - specific pattern
  if (reportLower.includes('disk') && reportLower.includes('critical') && 
      (reportLower.includes('90%') || reportLower.includes('full'))) {
    const content = `Critical disk space issues detected during overnight assessment on ${reportDate}.
System showed disk usage at critical levels. 
Related issues: ${criticalIssues.filter(i => i.includes('disk') || i.includes('space')).slice(0, 2).join(', ') || 'Disk space pressure detected'}. 
This indicates storage capacity issues requiring immediate attention.`;
    
    if (!kbEntryExists('Critical Disk Space')) {
      autoCreateKBEntry('Critical Disk Space', content, 
        ['storage', 'maintenance', 'system', 'disk-space']);
    }
  }
}

function archiveOldReports() {
  const cutoffMs = REPORT_RETENTION_DAYS * 24 * 60 * 60 * 1000;
  const now = Date.now();
  let archived = 0;

  try {
    for (const file of readdirSync(REPORT_DIR)) {
      if (!file.endsWith('.md') && !file.endsWith('.dot') && !file.endsWith('.mmd')) continue;
      const filePath = join(REPORT_DIR, file);
      const stat = statSync(filePath);
      if (now - stat.mtimeMs > cutoffMs) {
        renameSync(filePath, join(REPORT_ARCHIVE_DIR, file));
        archived++;
      }
    }
    if (archived > 0) console.log(`Archived ${archived} report(s) older than ${REPORT_RETENTION_DAYS} days.`);
  } catch (err) {
    console.error('Report archival failed:', err.message);
  }
}

function saveReport(assessmentStartTime) {
  report += `\n---\n\n**Assessment Duration:** ${Math.round((Date.now() - assessmentStartTime) / 1000)}s\n`;
  report += `**Generated by:** Automated Overnight Assessment System\n`;
  report += `**Report Location:** ${reportPath}\n`;

  // Write report
  writeFileSync(reportPath, report);
  console.log(`Assessment complete. Report saved to: ${reportPath}`);
  console.log(`Total issues: ${criticalIssues.length} critical, ${highIssues.length} high, ${mediumIssues.length} medium, ${lowIssues.length} low`);

  // Archive reports older than REPORT_RETENTION_DAYS days
  archiveOldReports();
}

async function runAssessment() {
  console.log('Starting overnight system assessment...');
  const startTime = Date.now();

  // Create MCP client for health server integration
  const mcpClient = await createMCPClient();

  try {
    generateSummary();
    await checkHealthServices();
    
    // Add MCP Health Server Historical Analysis
    console.log('Integrating MCP health server historical data...');
    const healthHistory = await getMCPHealthHistory(mcpClient, 7); // Last 7 days
    const alerts = await getMCPAlerts(mcpClient, 7); // Last 7 days
    const historicalTrendReport = generateHistoricalTrendReport(healthHistory, alerts);
    appendSection('Historical Trend Analysis (MCP Health Server)', historicalTrendReport);

    // Add Performance Baseline Analysis
    console.log('Analyzing performance against baselines...');
    const baselines = loadPerformanceBaselines();
    const baselineAnalysis = analyzePerformanceAgainstBaselines(healthHistory, baselines);
    const baselineReport = generateBaselineAnalysisReport(baselineAnalysis);
    appendSection('Performance Baseline Analysis', baselineReport);
    
    // Check if Yomi is actively processing before GPU assessment
    let yomiProcessing = false;
    try {
      const yomiResult = await httpGet('/api/yomi/activity-status');
      if (yomiResult.status === 200) {
        const yomiStatus = yomiResult.data.processStatus || {};
        yomiProcessing = yomiStatus.status === 'processing';
        
        if (yomiProcessing) {
          console.log('Yomi is actively processing, waiting 30 seconds for GPU load to normalize...');
          await new Promise(resolve => setTimeout(resolve, 30000));
        }
      }
    } catch (error) {
      console.log('Could not check Yomi processing status, proceeding with GPU assessment');
    }
    
    await checkGPUStatus();
    await checkYomiSystem();
    checkSystemResources();
    checkConfiguration();
    await checkSecurityStatus();
    checkImprovementsSSOT();

    // Detect KB-worthy issues
    detectKBWorthyIssues();

    // Sync auto-created improvements to SSOT
    syncAutoCreatedImprovements();

    // Sync auto-created KB entries
    syncAutoCreatedKBEntries();

    // Add auto-created improvements section to report
    if (autoCreatedImprovements.length > 0) {
      let autoContent = '**Auto-Created Improvements:** ' + autoCreatedImprovements.length + '\n\n';
      autoContent += 'The following improvements were automatically created and added to ssot.improvements.yml:\n\n';
      autoCreatedImprovements.forEach(imp => {
        autoContent += `- **${imp.label}** (${imp.priority} priority): ${imp.text}\n`;
      });
      appendSection('Auto-Created Improvements', autoContent);
    }

    // Add auto-created KB entries section to report
    if (autoCreatedKBEntries.length > 0) {
      let kbContent = '**Auto-Created KB Entries:** ' + autoCreatedKBEntries.length + '\n\n';
      kbContent += 'The following knowledge base entries were automatically created:\n\n';
      autoCreatedKBEntries.forEach(entry => {
        kbContent += `- **${entry.title}** → ${entry.filename}\n`;
      });
      appendSection('Auto-Created KB Entries', kbContent);
    }

    // Generate recommendations (includes KB maintenance)
    generateRecommendations();
    saveReport(startTime);

  } catch (error) {
    console.error('Assessment failed:', error);
    await closeMCPClient(mcpClient);
    process.exit(1);
  }

  // Close MCP client
  await closeMCPClient(mcpClient);
}

runAssessment();