#!/usr/bin/env node

import { execSync } from 'child_process';
import { readFileSync, existsSync } from 'fs';
import { join } from 'path';

const DATA_DIR = '/home/tony/CascadeProjects/chaba/data/gpu-monitor';
const LOG_FILE = join(DATA_DIR, 'gpu-usage.log');
const ALERT_FILE = join(DATA_DIR, 'gpu-alerts.log');

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

function getRecentAlerts(count = 10) {
  if (!existsSync(ALERT_FILE)) return [];

  const lines = readFileSync(ALERT_FILE, 'utf8').split('\n').filter(line => line.trim());
  return lines.slice(-count).map(line => {
    const parts = line.split('|').map(p => p.trim());
    return {
      timestamp: parts[0],
      type: parts[1],
      category: parts[2],
      message: parts[3]
    };
  });
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

function displayDashboard() {
  console.log('\n=== GPU Monitoring Dashboard ===\n');

  // Current Status
  const current = getGPUStatus();
  if (current) {
    console.log('📊 Current Status:');
    console.log(`   VRAM: ${current.memoryPercent}% (${current.memoryUsed}/${current.memoryTotal}MB)`);
    console.log(`   Utilization: ${current.utilization}%`);
    console.log(`   Temperature: ${current.temperature}°C`);
    console.log(`   Updated: ${current.timestamp}`);
  } else {
    console.log('❌ Unable to get GPU status');
  }

  // Historical Stats
  const historicalData = getHistoricalData(24);
  const stats = calculateStats(historicalData);
  
  if (stats) {
    console.log('\n📈 24h Statistics:');
    console.log(`   VRAM: avg ${stats.memory.avg}% (max ${stats.memory.max}%, min ${stats.memory.min}%)`);
    console.log(`   Utilization: avg ${stats.utilization.avg}% (max ${stats.utilization.max}%, min ${stats.utilization.min}%)`);
    console.log(`   Temperature: avg ${stats.temperature.avg}°C (max ${stats.temperature.max}°C, min ${stats.temperature.min}°C)`);
    console.log(`   Data points: ${stats.samples}`);
  }

  // Recent Alerts
  const alerts = getRecentAlerts(5);
  if (alerts.length > 0) {
    console.log('\n⚠️  Recent Alerts:');
    alerts.forEach(alert => {
      console.log(`   [${alert.type}] ${alert.timestamp} - ${alert.message}`);
    });
  } else {
    console.log('\n✅ No recent alerts');
  }

  // System Health
  console.log('\n🖥️  System Health:');
  const diskUsage = execCommand('df -h / | tail -1');
  if (diskUsage) {
    const diskMatch = diskUsage.match(/(\d+)%/);
    if (diskMatch) {
      const usage = parseInt(diskMatch[1]);
      const status = usage > 90 ? '🔴 CRITICAL' : usage > 80 ? '🟡 WARNING' : '🟢 OK';
      console.log(`   Disk: ${status} (${usage}%)`);
    }
  }

  const containerCount = execCommand('docker ps --format "{{.Names}}" | wc -l');
  if (containerCount) {
    console.log(`   Docker Containers: ${containerCount.trim()} running`);
  }

  console.log('\n=== End Dashboard ===\n');
}

// Run dashboard
displayDashboard();