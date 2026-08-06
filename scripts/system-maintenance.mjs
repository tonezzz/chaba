#!/usr/bin/env node

import { execSync } from 'child_process';
import { writeFileSync, existsSync, mkdirSync, readFileSync } from 'fs';
import { join } from 'path';

const LOG_DIR = '/home/tony/CascadeProjects/chaba/logs/maintenance';
const LOG_FILE = join(LOG_DIR, 'maintenance.log');

// Ensure log directory exists
if (!existsSync(LOG_DIR)) mkdirSync(LOG_DIR, { recursive: true });

function log(message) {
  const timestamp = new Date().toISOString();
  const logEntry = `[${timestamp}] ${message}\n`;
  writeFileSync(LOG_FILE, logEntry, { flag: 'a' });
  console.log(logEntry.trim());
}

function execCommand(command, description) {
  try {
    log(`Starting: ${description}`);
    const result = execSync(command, { encoding: 'utf8', timeout: 300000 });
    log(`Success: ${description}`);
    return { success: true, output: result };
  } catch (error) {
    log(`Failed: ${description} - ${error.message}`);
    return { success: false, error: error.message };
  }
}

function dockerCleanup() {
  log('=== Docker Cleanup ===');
  
  // Remove unused containers, networks, images, and build cache
  const result = execCommand('docker system prune -a -f --volumes', 'Docker system prune');
  
  if (result.success) {
    // Extract space reclaimed from output
    const match = result.output.match(/Total reclaimed space: (.+)/);
    if (match) {
      log(`Space reclaimed: ${match[1]}`);
    }
  }
  
  return result.success;
}

function journalCleanup() {
  log('=== Journal Cleanup ===');
  
  // Limit journal size to 500M
  const result = execCommand('sudo journalctl --vacuum-size=500M', 'Journal vacuum to 500M');
  
  if (result.success) {
    const match = result.output.match(/freed (.+) of archived journals/);
    if (match) {
      log(`Journal space freed: ${match[1]}`);
    }
  }
  
  return result.success;
}

function logCleanup() {
  log('=== Log Cleanup ===');
  
  // Clean old log files (>30 days)
  const result = execCommand(
    'find /var/log -type f -name "*.log" -mtime +30 -delete 2>/dev/null || true',
    'Clean logs older than 30 days'
  );
  
  return result.success;
}

function diskCheck() {
  log('=== Disk Space Check ===');
  
  const result = execCommand('df -h /', 'Check disk usage');
  
  if (result.success) {
    const match = result.output.match(/(\d+)%/);
    if (match) {
      const usage = parseInt(match[1]);
      log(`Disk usage: ${usage}%`);
      
      if (usage > 90) {
        log('⚠️  CRITICAL: Disk usage above 90%');
      } else if (usage > 80) {
        log('⚠️  WARNING: Disk usage above 80%');
      }
    }
  }
  
  return result.success;
}

function dockerHealthCheck() {
  log('=== Docker Health Check ===');
  
  const result = execCommand('docker ps --format "{{.Names}}: {{.Status}}"', 'Check running containers');
  
  if (result.success) {
    const containers = result.output.trim().split('\n');
    log(`Running containers: ${containers.length}`);
    
    // Check for unhealthy containers
    const unhealthy = containers.filter(c => c.includes('unhealthy') || c.includes('Exited'));
    if (unhealthy.length > 0) {
      log(`⚠️  Unhealthy containers: ${unhealthy.length}`);
      unhealthy.forEach(c => log(`  - ${c}`));
    }
  }
  
  return result.success;
}

function gpuMonitorCheck() {
  log('=== GPU Monitor Check ===');
  
  const result = execCommand('node /home/tony/CascadeProjects/chaba/scripts/gpu-monitor.mjs', 'GPU monitoring check');
  
  return result.success;
}

function generateReport(results) {
  log('=== Maintenance Report ===');
  
  const timestamp = new Date().toISOString();
  const report = {
    timestamp,
    results: {
      dockerCleanup: results.dockerCleanup,
      journalCleanup: results.journalCleanup,
      logCleanup: results.logCleanup,
      diskCheck: results.diskCheck,
      dockerHealthCheck: results.dockerHealthCheck,
      gpuMonitorCheck: results.gpuMonitorCheck
    },
    summary: {
      total: Object.keys(results).length,
      successful: Object.values(results).filter(r => r).length,
      failed: Object.values(results).filter(r => !r).length
    }
  };
  
  log(`Summary: ${report.summary.successful}/${report.summary.total} tasks successful`);
  
  return report;
}

function main() {
  log('=== Starting System Maintenance ===');
  
  const results = {
    dockerCleanup: dockerCleanup(),
    journalCleanup: journalCleanup(),
    logCleanup: logCleanup(),
    diskCheck: diskCheck(),
    dockerHealthCheck: dockerHealthCheck(),
    gpuMonitorCheck: gpuMonitorCheck()
  };
  
  const report = generateReport(results);
  
  log('=== System Maintenance Complete ===');
  
  return report;
}

// Run maintenance
const report = main();

// Export for use in other scripts
if (process.argv[2] === '--export') {
  console.log(JSON.stringify(report, null, 2));
}