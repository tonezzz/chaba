#!/usr/bin/env node

import { execSync } from 'child_process';
import { writeFileSync, existsSync, mkdirSync, readFileSync } from 'fs';
import { join } from 'path';

const DATA_DIR = '/home/tony/CascadeProjects/chaba/data/gpu-monitor';
const LOG_FILE = join(DATA_DIR, 'gpu-usage.log');
const ALERT_FILE = join(DATA_DIR, 'gpu-alerts.log');
const THRESHOLDS = {
  warning: 80,    // 80% VRAM usage triggers warning
  critical: 90,  // 90% VRAM usage triggers critical alert
  temp_warning: 75,  // 75°C triggers temperature warning
  temp_critical: 85  // 85°C triggers critical temperature alert
};

// Ensure data directory exists
if (!existsSync(DATA_DIR)) mkdirSync(DATA_DIR, { recursive: true });

function execCommand(command) {
  try {
    return execSync(command, { encoding: 'utf8' }).trim();
  } catch (error) {
    return null;
  }
}

function getGPUStatus() {
  const nvidiaSmi = execCommand('nvidia-smi --query-gpu=memory.used,memory.total,utilization.gpu,temperature.gpu --format=csv,noheader,nounits');
  if (!nvidiaSmi) return null;

  const [memoryUsed, memoryTotal, utilization, temperature] = nvidiaSmi.split(',').map(v => parseInt(v.trim()));
  const memoryPercent = Math.round((memoryUsed / memoryTotal) * 100);

  return {
    memoryUsed,
    memoryTotal,
    memoryPercent,
    utilization,
    temperature,
    timestamp: new Date().toISOString()
  };
}

function logGPUStatus(status) {
  const logEntry = `${status.timestamp} | VRAM: ${status.memoryPercent}% (${status.memoryUsed}/${status.memoryTotal}MB) | Util: ${status.utilization}% | Temp: ${status.temperature}°C\n`;
  writeFileSync(LOG_FILE, logEntry, { flag: 'a' });
}

function checkAlerts(status) {
  const alerts = [];
  const timestamp = new Date().toISOString();

  // VRAM Usage Alerts
  if (status.memoryPercent >= THRESHOLDS.critical) {
    alerts.push({
      type: 'CRITICAL',
      category: 'vram',
      message: `GPU VRAM usage critical: ${status.memoryPercent}% (${status.memoryUsed}/${status.memoryTotal}MB)`,
      timestamp
    });
  } else if (status.memoryPercent >= THRESHOLDS.warning) {
    alerts.push({
      type: 'WARNING',
      category: 'vram',
      message: `GPU VRAM usage elevated: ${status.memoryPercent}% (${status.memoryUsed}/${status.memoryTotal}MB)`,
      timestamp
    });
  }

  // Temperature Alerts
  if (status.temperature >= THRESHOLDS.temp_critical) {
    alerts.push({
      type: 'CRITICAL',
      category: 'temperature',
      message: `GPU temperature critical: ${status.temperature}°C`,
      timestamp
    });
  } else if (status.temperature >= THRESHOLDS.temp_warning) {
    alerts.push({
      type: 'WARNING',
      category: 'temperature',
      message: `GPU temperature elevated: ${status.temperature}°C`,
      timestamp
    });
  }

  return alerts;
}

function logAlerts(alerts) {
  if (alerts.length === 0) return;

  const alertEntry = alerts.map(alert => 
    `${alert.timestamp} | ${alert.type} | ${alert.category} | ${alert.message}\n`
  ).join('');

  writeFileSync(ALERT_FILE, alertEntry, { flag: 'a' });
}

function getHistoricalData(hours = 24) {
  if (!existsSync(LOG_FILE)) return [];

  const lines = readFileSync(LOG_FILE, 'utf8').split('\n').filter(line => line.trim());
  const cutoffTime = new Date(Date.now() - hours * 60 * 60 * 1000);

  return lines
    .filter(line => {
      const timestamp = new Date(line.split('|')[0].trim());
      return timestamp >= cutoffTime;
    })
    .map(line => {
      const parts = line.split('|').map(p => p.trim());
      const timestamp = parts[0];
      const vramMatch = parts[1].match(/VRAM: (\d+)% \((\d+)\/(\d+)MB\)/);
      const utilMatch = parts[2].match(/Util: (\d+)%/);
      const tempMatch = parts[3].match(/Temp: (\d+)°C/);

      return {
        timestamp,
        memoryPercent: parseInt(vramMatch[1]),
        memoryUsed: parseInt(vramMatch[2]),
        memoryTotal: parseInt(vramMatch[3]),
        utilization: parseInt(utilMatch[1]),
        temperature: parseInt(tempMatch[1])
      };
    });
}

function calculateStats(data) {
  if (data.length === 0) return null;

  const memoryValues = data.map(d => d.memoryPercent);
  const utilValues = data.map(d => d.utilization);
  const tempValues = data.map(d => d.temperature);

  const avg = arr => arr.reduce((a, b) => a + b, 0) / arr.length;
  const max = arr => Math.max(...arr);
  const min = arr => Math.min(...arr);

  return {
    memory: {
      avg: Math.round(avg(memoryValues)),
      max: max(memoryValues),
      min: min(memoryValues)
    },
    utilization: {
      avg: Math.round(avg(utilValues)),
      max: max(utilValues),
      min: min(utilValues)
    },
    temperature: {
      avg: Math.round(avg(tempValues)),
      max: max(tempValues),
      min: min(tempValues)
    },
    samples: data.length
  };
}

function main() {
  console.log('GPU Monitoring Check...');

  const status = getGPUStatus();
  if (!status) {
    console.error('Failed to get GPU status');
    return;
  }

  console.log(`Current Status: VRAM ${status.memoryPercent}% | Util ${status.utilization}% | Temp ${status.temperature}°C`);

  // Log current status
  logGPUStatus(status);

  // Check for alerts
  const alerts = checkAlerts(status);
  if (alerts.length > 0) {
    console.log(`⚠️  ${alerts.length} alert(s) triggered`);
    alerts.forEach(alert => console.log(`  ${alert.type}: ${alert.message}`));
    logAlerts(alerts);
  }

  // Calculate historical stats
  const historicalData = getHistoricalData(24);
  const stats = calculateStats(historicalData);
  
  if (stats) {
    console.log(`24h Stats: VRAM avg ${stats.memory.avg}% (max ${stats.memory.max}%) | Temp avg ${stats.temperature.avg}°C (max ${stats.temperature.max}°C)`);
  }

  return { status, alerts, stats };
}

// Run monitoring check
const result = main();
console.log('GPU monitoring check complete');

// Export for use in other scripts
if (process.argv[2] === '--export') {
  console.log(JSON.stringify(result, null, 2));
}