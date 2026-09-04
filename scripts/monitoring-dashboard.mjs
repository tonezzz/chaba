#!/usr/bin/env node
/**
 * Chaba Monitoring Dashboard
 * Real-time monitoring dashboard for Chaba infrastructure
 * Integrates service health, performance metrics, alerts, and backup status
 */

import http from 'http';
import fs from 'fs';
import path from 'path';
import { fileURLToPath } from 'url';
import { exec } from 'child_process';
import { promisify } from 'util';

const execAsync = promisify(exec);
const __filename = fileURLToPath(import.meta.url);
const __dirname = path.dirname(__filename);

// Configuration
const PORT = 3002;
const UPDATE_INTERVAL = 30000; // 30 seconds
const LOG_FILE = '/home/tony/CascadeProjects/chaba-tony-dell/logs/health-monitor.log';
const BACKUP_LOG = '/var/log/chaba-backup.log';
const BACKUP_MONITOR_LOG = '/var/log/chaba-backup-monitor.log';

// Dashboard state
let dashboardState = {
    services: {},
    performance: {},
    alerts: [],
    backup: {},
    gpu: {},
    lastUpdate: null,
    uptime: Date.now()
};

// Service health check endpoints
const SERVICE_ENDPOINTS = {
    'status-api': 'http://tony-dell:8000/health',
    'yomi-api': 'http://tony-dell:3000/api/yomi/health',
    'caddy': 'http://tony-dell:8080/',
    'trade-api': 'http://tony-dell:3001/api/trade/health'
};

// Check service health
async function checkServiceHealth(serviceName, url) {
    try {
        const start = Date.now();
        const response = await fetch(url, {
            method: 'GET',
            signal: AbortSignal.timeout(5000)
        });
        const responseTime = Date.now() - start;
        
        return {
            name: serviceName,
            status: response.ok ? 'healthy' : 'unhealthy',
            statusCode: response.status,
            responseTime: responseTime,
            lastCheck: new Date().toISOString()
        };
    } catch (error) {
        return {
            name: serviceName,
            status: 'error',
            error: error.message,
            lastCheck: new Date().toISOString()
        };
    }
}

// Check Docker container status
async function checkContainerStatus(containerName) {
    try {
        const { stdout } = await execAsync(`docker ps --filter "name=${containerName}" --format "{{.Status}}"`);
        const isRunning = stdout.trim().length > 0;
        
        return {
            name: containerName,
            status: isRunning ? 'running' : 'stopped',
            lastCheck: new Date().toISOString()
        };
    } catch (error) {
        return {
            name: containerName,
            status: 'error',
            error: error.message,
            lastCheck: new Date().toISOString()
        };
    }
}

// Parse health monitor log for recent alerts
function parseHealthMonitorLog() {
    try {
        if (!fs.existsSync(LOG_FILE)) {
            return [];
        }
        
        const logContent = fs.readFileSync(LOG_FILE, 'utf-8');
        const lines = logContent.split('\n').slice(-50); // Last 50 lines
        
        const alerts = [];
        for (const line of lines) {
            if (line.includes('critical') || line.includes('warning') || line.includes('ISSUES')) {
                const timestamp = line.match(/\[([\d- :]+)\]/)?.[1] || new Date().toISOString();
                const severity = line.includes('critical') ? 'critical' : 
                               line.includes('warning') ? 'warning' : 'info';
                const message = line.replace(/\[.*?\]\s*/, '').trim();
                
                alerts.push({
                    timestamp,
                    severity,
                    message,
                    source: 'health-monitor'
                });
            }
        }
        
        return alerts.slice(-20); // Last 20 alerts
    } catch (error) {
        console.error('Error parsing health monitor log:', error);
        return [];
    }
}

// Parse backup logs
async function parseBackupLogs() {
    try {
        const backupStatus = {
            lastBackup: null,
            lastBackupStatus: 'unknown',
            backupCount: 0,
            recentErrors: []
        };
        
        // Check backup log
        if (fs.existsSync(BACKUP_LOG)) {
            const backupLogContent = fs.readFileSync(BACKUP_LOG, 'utf-8');
            const lines = backupLogContent.split('\n').slice(-20);
            
            for (const line of lines) {
                if (line.includes('Backup completed successfully')) {
                    const timestamp = line.match(/\[([\d- :]+)\]/)?.[1];
                    if (timestamp) {
                        backupStatus.lastBackup = timestamp;
                        backupStatus.lastBackupStatus = 'success';
                    }
                } else if (line.includes('ERROR')) {
                    backupStatus.recentErrors.push({
                        timestamp: line.match(/\[([\d- :]+)\]/)?.[1] || new Date().toISOString(),
                        message: line.replace(/\[.*?\]\s*\[ERROR\]\s*/, '').trim()
                    });
                }
            }
        }
        
        // Count backup files
        const backupDir = '/home/tony/GoogleDrive/Tony AI/backup/chaba/daily';
        if (fs.existsSync(backupDir)) {
            const files = fs.readdirSync(backupDir);
            backupStatus.backupCount = files.filter(f => f.endsWith('.sql.gz') || f.endsWith('.tar.gz')).length;
        }
        
        // Check Google Drive mount
        try {
            const { stdout } = await execAsync('mount | grep gdrive');
            backupStatus.gdriveMounted = stdout.includes('/home/tony/GoogleDrive');
        } catch {
            backupStatus.gdriveMounted = false;
        }
        
        return backupStatus;
    } catch (error) {
        console.error('Error parsing backup logs:', error);
        return { error: error.message };
    }
}

// Get GPU status
async function getGPUStatus() {
    try {
        const { stdout } = await execAsync('nvidia-smi --query-gpu=name,memory.used,memory.total,temperature.gpu,utilization.gpu --format=csv,noheader');
        const gpuData = stdout.trim().split(',').map(s => s.trim());
        
        return {
            name: gpuData[0],
            memoryUsed: gpuData[1],
            memoryTotal: gpuData[2],
            temperature: gpuData[3],
            utilization: gpuData[4],
            lastCheck: new Date().toISOString()
        };
    } catch (error) {
        return {
            status: 'error',
            error: error.message,
            lastCheck: new Date().toISOString()
        };
    }
}

// Get system resources
async function getSystemResources() {
    try {
        const { stdout: memInfo } = await execAsync('free -m | grep Mem');
        const memData = memInfo.trim().split(/\s+/);
        
        const { stdout: diskInfo } = await execAsync('df -h / | tail -1');
        const diskData = diskInfo.trim().split(/\s+/);
        
        return {
            memory: {
                total: parseInt(memData[1]),
                used: parseInt(memData[2]),
                free: parseInt(memData[3]),
                percent: Math.round((parseInt(memData[2]) / parseInt(memData[1])) * 100)
            },
            disk: {
                total: diskData[1],
                used: diskData[2],
                available: diskData[3],
                percent: parseInt(diskData[4])
            },
            lastCheck: new Date().toISOString()
        };
    } catch (error) {
        return {
            status: 'error',
            error: error.message,
            lastCheck: new Date().toISOString()
        };
    }
}

// Update dashboard state
async function updateDashboardState() {
    console.log('Updating dashboard state...');
    
    // Check services
    const serviceChecks = await Promise.all(
        Object.entries(SERVICE_ENDPOINTS).map(([name, url]) => checkServiceHealth(name, url))
    );
    dashboardState.services = Object.fromEntries(
        serviceChecks.map(check => [check.name, check])
    );
    
    // Check key containers
    const containers = ['postgres', 'redis', 'caddy', 'gpu-queue'];
    const containerChecks = await Promise.all(
        containers.map(name => checkContainerStatus(name))
    );
    containerChecks.forEach(check => {
        dashboardState.services[check.name] = check;
    });
    
    // Parse alerts
    dashboardState.alerts = parseHealthMonitorLog();
    
    // Backup status
    dashboardState.backup = await parseBackupLogs();
    
    // GPU status
    dashboardState.gpu = await getGPUStatus();
    
    // System resources
    dashboardState.performance = await getSystemResources();
    
    dashboardState.lastUpdate = new Date().toISOString();
    
    console.log('Dashboard state updated:', dashboardState.lastUpdate);
}

// Generate HTML dashboard
function generateDashboardHTML() {
    const servicesHTML = Object.entries(dashboardState.services).map(([name, status]) => {
        const statusClass = status.status === 'healthy' || status.status === 'running' ? 'status-healthy' : 
                           status.status === 'error' ? 'status-error' : 'status-warning';
        const responseTime = status.responseTime ? `<span class="response-time">${status.responseTime}ms</span>` : '';
        
        return `
            <div class="service-card ${statusClass}">
                <div class="service-name">${name}</div>
                <div class="service-status">${status.status}</div>
                ${responseTime}
                <div class="service-time">${new Date(status.lastCheck).toLocaleTimeString()}</div>
            </div>
        `;
    }).join('');
    
    const alertsHTML = dashboardState.alerts.slice(-10).map(alert => {
        const severityClass = alert.severity === 'critical' ? 'alert-critical' : 
                             alert.severity === 'warning' ? 'alert-warning' : 'alert-info';
        
        return `
            <div class="alert-item ${severityClass}">
                <div class="alert-time">${new Date(alert.timestamp).toLocaleString()}</div>
                <div class="alert-severity">${alert.severity}</div>
                <div class="alert-message">${alert.message}</div>
            </div>
        `;
    }).join('');
    
    const backupHTML = `
        <div class="backup-status">
            <div class="backup-item">
                <span class="backup-label">Last Backup:</span>
                <span class="backup-value">${dashboardState.backup.lastBackup || 'Never'}</span>
            </div>
            <div class="backup-item">
                <span class="backup-label">Status:</span>
                <span class="backup-value ${dashboardState.backup.lastBackupStatus === 'success' ? 'status-healthy' : 'status-warning'}">
                    ${dashboardState.backup.lastBackupStatus}
                </span>
            </div>
            <div class="backup-item">
                <span class="backup-label">Backup Count:</span>
                <span class="backup-value">${dashboardState.backup.backupCount}</span>
            </div>
            <div class="backup-item">
                <span class="backup-label">Google Drive:</span>
                <span class="backup-value ${dashboardState.backup.gdriveMounted ? 'status-healthy' : 'status-error'}">
                    ${dashboardState.backup.gdriveMounted ? 'Mounted' : 'Not Mounted'}
                </span>
            </div>
        </div>
    `;
    
    const performanceHTML = `
        <div class="performance-grid">
            <div class="performance-card">
                <div class="performance-title">Memory Usage</div>
                <div class="performance-value">${dashboardState.performance.memory?.percent || 0}%</div>
                <div class="performance-detail">${dashboardState.performance.memory?.used || 0}MB / ${dashboardState.performance.memory?.total || 0}MB</div>
            </div>
            <div class="performance-card">
                <div class="performance-title">Disk Usage</div>
                <div class="performance-value">${dashboardState.performance.disk?.percent || 0}%</div>
                <div class="performance-detail">${dashboardState.performance.disk?.used || 'N/A'} / ${dashboardState.performance.disk?.total || 'N/A'}</div>
            </div>
            <div class="performance-card">
                <div class="performance-title">GPU Temperature</div>
                <div class="performance-value">${dashboardState.gpu.temperature || 'N/A'}°C</div>
                <div class="performance-detail">Utilization: ${dashboardState.gpu.utilization || 'N/A'}</div>
            </div>
            <div class="performance-card">
                <div class="performance-title">GPU Memory</div>
                <div class="performance-value">${dashboardState.gpu.memoryUsed || 'N/A'}</div>
                <div class="performance-detail">Total: ${dashboardState.gpu.memoryTotal || 'N/A'}</div>
            </div>
        </div>
    `;
    
    return `
<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Chaba Monitoring Dashboard</title>
    <style>
        * { margin: 0; padding: 0; box-sizing: border-box; }
        body { font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif; background: #1a1a2e; color: #eee; }
        .container { max-width: 1400px; margin: 0 auto; padding: 20px; }
        .header { display: flex; justify-content: space-between; align-items: center; margin-bottom: 30px; }
        .header h1 { font-size: 2em; color: #4ecca3; }
        .last-update { color: #888; font-size: 0.9em; }
        .section { margin-bottom: 30px; }
        .section-title { font-size: 1.3em; margin-bottom: 15px; color: #4ecca3; border-bottom: 2px solid #4ecca3; padding-bottom: 5px; }
        .services-grid { display: grid; grid-template-columns: repeat(auto-fill, minmax(200px, 1fr)); gap: 15px; }
        .service-card { background: #16213e; padding: 15px; border-radius: 8px; border-left: 4px solid #666; }
        .service-card.status-healthy { border-left-color: #4ecca3; }
        .service-card.status-error { border-left-color: #e94560; }
        .service-card.status-warning { border-left-color: #f9a825; }
        .service-name { font-weight: bold; margin-bottom: 5px; }
        .service-status { font-size: 0.9em; margin-bottom: 5px; }
        .response-time { font-size: 0.8em; color: #888; }
        .service-time { font-size: 0.75em; color: #666; }
        .performance-grid { display: grid; grid-template-columns: repeat(auto-fit, minmax(200px, 1fr)); gap: 15px; }
        .performance-card { background: #16213e; padding: 20px; border-radius: 8px; text-align: center; }
        .performance-title { font-size: 0.9em; color: #888; margin-bottom: 10px; }
        .performance-value { font-size: 2em; font-weight: bold; color: #4ecca3; }
        .performance-detail { font-size: 0.8em; color: #666; margin-top: 5px; }
        .alerts-container { max-height: 300px; overflow-y: auto; }
        .alert-item { background: #16213e; padding: 10px; margin-bottom: 8px; border-radius: 4px; border-left: 3px solid #666; }
        .alert-item.alert-critical { border-left-color: #e94560; }
        .alert-item.alert-warning { border-left-color: #f9a825; }
        .alert-item.alert-info { border-left-color: #4ecca3; }
        .alert-time { font-size: 0.75em; color: #888; }
        .alert-severity { font-size: 0.8em; font-weight: bold; margin: 3px 0; }
        .alert-message { font-size: 0.9em; }
        .backup-status { background: #16213e; padding: 20px; border-radius: 8px; }
        .backup-item { display: flex; justify-content: space-between; padding: 8px 0; border-bottom: 1px solid #333; }
        .backup-item:last-child { border-bottom: none; }
        .backup-label { color: #888; }
        .backup-value { font-weight: bold; }
        .status-healthy { color: #4ecca3; }
        .status-error { color: #e94560; }
        .status-warning { color: #f9a825; }
        .refresh-btn { background: #4ecca3; color: #1a1a2e; border: none; padding: 10px 20px; border-radius: 4px; cursor: pointer; font-weight: bold; }
        .refresh-btn:hover { background: #3db892; }
    </style>
</head>
<body>
    <div class="container">
        <div class="header">
            <h1>🚀 Chaba Monitoring Dashboard</h1>
            <div>
                <button class="refresh-btn" onclick="location.reload()">Refresh</button>
                <div class="last-update">Last update: ${new Date(dashboardState.lastUpdate).toLocaleString()}</div>
            </div>
        </div>
        
        <div class="section">
            <div class="section-title">📊 Performance Metrics</div>
            ${performanceHTML}
        </div>
        
        <div class="section">
            <div class="section-title">🔧 Service Status</div>
            <div class="services-grid">
                ${servicesHTML}
            </div>
        </div>
        
        <div class="section">
            <div class="section-title">💾 Backup Status</div>
            ${backupHTML}
        </div>
        
        <div class="section">
            <div class="section-title">🚨 Recent Alerts</div>
            <div class="alerts-container">
                ${alertsHTML || '<div style="color: #888; padding: 10px;">No recent alerts</div>'}
            </div>
        </div>
    </div>
    
    <script>
        // Auto-refresh every 30 seconds
        setTimeout(() => location.reload(), 30000);
    </script>
</body>
</html>
    `;
}

// Create HTTP server
const server = http.createServer(async (req, res) => {
    if (req.url === '/') {
        // Serve dashboard HTML
        res.writeHead(200, { 'Content-Type': 'text/html' });
        res.end(generateDashboardHTML());
    } else if (req.url === '/api/status') {
        // Serve JSON API
        res.writeHead(200, { 'Content-Type': 'application/json' });
        res.end(JSON.stringify(dashboardState, null, 2));
    } else if (req.url === '/api/refresh') {
        // Force refresh
        await updateDashboardState();
        res.writeHead(200, { 'Content-Type': 'application/json' });
        res.end(JSON.stringify({ status: 'refreshed', timestamp: dashboardState.lastUpdate }));
    } else {
        res.writeHead(404);
        res.end('Not found');
    }
});

// Start server
server.listen(PORT, () => {
    console.log(`🚀 Chaba Monitoring Dashboard running on http://localhost:${PORT}`);
    console.log(`📊 Dashboard: http://localhost:${PORT}`);
    console.log(`🔌 API: http://localhost:${PORT}/api/status`);
    
    // Initial update
    updateDashboardState();
    
    // Periodic updates
    setInterval(updateDashboardState, UPDATE_INTERVAL);
});

// Handle graceful shutdown
process.on('SIGTERM', () => {
    console.log('Shutting down monitoring dashboard...');
    server.close(() => {
        console.log('Server closed');
        process.exit(0);
    });
});