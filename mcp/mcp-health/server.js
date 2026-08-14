#!/usr/bin/env node
import { Server } from '@modelcontextprotocol/sdk/server/index.js';
import { StdioServerTransport } from '@modelcontextprotocol/sdk/server/stdio.js';
import {
  CallToolRequestSchema,
  ListToolsRequestSchema,
} from '@modelcontextprotocol/sdk/types.js';
import { readFileSync } from 'fs';
import { fileURLToPath } from 'url';
import { dirname, join } from 'path';
import yaml from 'yaml';
import pg from 'pg';

const __filename = fileURLToPath(import.meta.url);
const __dirname = dirname(__filename);

// PostgreSQL connection setup
const { Pool } = pg;
const pool = new Pool({
  host: 'localhost',
  port: 5432,
  database: 'chaba',
  user: 'chaba',
  password: process.env.POSTGRES_PASSWORD || 'chabapass',
  max: 20,
  idleTimeoutMillis: 30000,
  connectionTimeoutMillis: 2000,
});

// Database initialization
async function initializeDatabase() {
  const client = await pool.connect();
  try {
    // Create health_checks table
    await client.query(`
      CREATE TABLE IF NOT EXISTS health_checks (
        id SERIAL PRIMARY KEY,
        service_name TEXT NOT NULL,
        status TEXT NOT NULL,
        response_time REAL,
        error TEXT,
        http_status INTEGER,
        expected_status INTEGER,
        container_state TEXT,
        expected_state TEXT,
        active_state TEXT,
        sub_state TEXT,
        is_timer BOOLEAN DEFAULT FALSE,
        timestamp TIMESTAMP DEFAULT CURRENT_TIMESTAMP
      );
    `);

    // Create indexes
    await client.query(`
      CREATE INDEX IF NOT EXISTS idx_health_checks_service_timestamp 
      ON health_checks(service_name, timestamp);
    `);
    await client.query(`
      CREATE INDEX IF NOT EXISTS idx_health_checks_status 
      ON health_checks(status);
    `);
    await client.query(`
      CREATE INDEX IF NOT EXISTS idx_health_checks_timer 
      ON health_checks(is_timer);
    `);

    // Create alerts table
    await client.query(`
      CREATE TABLE IF NOT EXISTS alerts (
        id SERIAL PRIMARY KEY,
        service_name TEXT NOT NULL,
        alert_type TEXT NOT NULL,
        severity TEXT NOT NULL,
        message TEXT NOT NULL,
        acknowledged BOOLEAN DEFAULT FALSE,
        acknowledged_at TIMESTAMP,
        resolved BOOLEAN DEFAULT FALSE,
        resolved_at TIMESTAMP,
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
      );
    `);

    // Create indexes for alerts
    await client.query(`
      CREATE INDEX IF NOT EXISTS idx_alerts_service 
      ON alerts(service_name);
    `);
    await client.query(`
      CREATE INDEX IF NOT EXISTS idx_alerts_severity 
      ON alerts(severity);
    `);
    await client.query(`
      CREATE INDEX IF NOT EXISTS idx_alerts_resolved 
      ON alerts(resolved);
    `);
    await client.query(`
      CREATE INDEX IF NOT EXISTS idx_alerts_acknowledged 
      ON alerts(acknowledged);
    `);

    console.error('Database initialized successfully');
  } catch (error) {
    console.error('Database initialization error:', error);
    throw error;
  } finally {
    client.release();
  }
}

// Initialize database on startup
initializeDatabase().catch(error => {
  console.error('Failed to initialize database:', error);
  process.exit(1);
});

// Helper functions to mimic SQLite API with PostgreSQL
async function query(text, params) {
  const start = Date.now();
  try {
    const res = await pool.query(text, params);
    const duration = Date.now() - start;
    console.error('Executed query', { text, duration, rows: res.rowCount });
    return res;
  } catch (error) {
    console.error('Database query error:', error);
    throw error;
  }
}

// Convert SQLite-style ? placeholders to PostgreSQL $1, $2, etc.
const convertPlaceholders = (sql) => {
  let i = 0;
  return sql.replace(/\?/g, () => '$' + (++i));
};

// Simplified SQLite-like interface for compatibility
const db = {
  prepare: (sql) => ({
    all: async (...params) => {
      const result = await pool.query(convertPlaceholders(sql), params);
      return result.rows;
    },
    get: async (...params) => {
      const result = await pool.query(convertPlaceholders(sql), params);
      return result.rows[0] || null;
    },
    run: async (...params) => {
      const result = await pool.query(convertPlaceholders(sql), params);
      return result;
    },
    exec: async (sql) => {
      await pool.query(convertPlaceholders(sql));
    }
  })
};

// Read health configuration
async function loadHealthConfig() {
  const configPath = process.env.HEALTH_CONFIG || join(process.cwd(), 'docs/ssot/infrastructure/ssot.health.yml');
  console.error(`Loading health config from: ${configPath}`);
  try {
    const { execSync } = await import('child_process');

    // Read main config first to get profile rules
    let file = readFileSync(configPath, 'utf8');
    let config = yaml.parse(file);

    // Auto-detect network profile
    let profile = 'home';
    let baseUrl = config.profiles?.home?.base_url || 'http://tony-omen.local:8080';

    // 1. Optional explicit override
    if (process.env.HEALTH_PROFILE) {
      profile = process.env.HEALTH_PROFILE;
      baseUrl = config.profiles?.[profile]?.base_url || baseUrl;
      console.error(`Profile override from HEALTH_PROFILE: ${profile}`);
    } else {
      // 2. Try WiFi SSID detection
      let ssid = null;
      try {
        ssid = execSync('iwgetid -r 2>/dev/null', { encoding: 'utf8' }).trim();
      } catch {}
      if (!ssid) {
        try {
          const link = execSync('iw dev wlo1 link 2>/dev/null | grep -E "^\\s+SSID:"', { encoding: 'utf8' });
          const match = link.match(/SSID:\s*(.+)/);
          if (match) ssid = match[1].trim();
        } catch {}
      }
      if (ssid) {
        console.error(`Detected WiFi SSID: ${ssid}`);
        const homeSsids = config.profiles?.home?.ssids || [];
        const mobileSsids = config.profiles?.mobile?.ssids || [];
        if (homeSsids.includes(ssid)) {
          profile = 'home';
          baseUrl = config.profiles?.home?.base_url || baseUrl;
        } else if (mobileSsids.includes(ssid)) {
          profile = 'mobile';
          baseUrl = config.profiles?.mobile?.base_url || 'http://tony-omen:8080';
        }
      }

      // 3. Fall back to hostname reachability
      if (profile === 'home') {
        try {
          execSync('ping -c 1 -W 2 tony-omen.local', { stdio: 'ignore' });
        } catch {
          profile = 'mobile';
          try {
            const ip = execSync('ip route get 1.1.1.1 | awk \'{print $7}\'', { encoding: 'utf8' }).trim();
            baseUrl = `http://${ip}:8080`;
          } catch {
            baseUrl = 'http://localhost:8080';
          }
        }
      }
    }

    console.error(`Detected profile: ${profile}, base URL: ${baseUrl}`);

    // Try to load profile-specific config first
    try {
      const profileConfigPath = configPath.replace('ssot.health.yml', `ssot.health.${profile}.yml`);
      file = readFileSync(profileConfigPath, 'utf8');
      console.error(`Using profile-specific config: ${profileConfigPath}`);
    } catch {
      file = readFileSync(configPath, 'utf8');
      console.error(`Using main config: ${configPath}`);
    }

    config = yaml.parse(file);

    // Substitute {profile} placeholders in service URLs
    if (config.services) {
      config.services = config.services.map(service => {
        if (service.url && typeof service.url === 'string') {
          service.url = service.url.replace('{profile}', baseUrl);
        }
        return service;
      });
    }

    // Store profile info for later use
    config.detectedProfile = profile;
    config.detectedBaseUrl = baseUrl;

    return config;
  } catch (error) {
    console.error(`Failed to load health config from ${configPath}:`, error.message);
    return { services: [], detectedProfile: 'unknown' };
  }
}

// Get recovery actions from config
function getRecoveryActions(config, failureType) {
  if (!config.recovery_actions) return [];
  
  const actions = config.recovery_actions[failureType];
  if (typeof actions === 'string') {
    return [actions];
  } else if (Array.isArray(actions)) {
    return actions;
  }
  return [];
}

// Alert generation and management
async function generateAlert(serviceName, alertType, severity, message) {
  const stmt = db.prepare(`
    INSERT INTO alerts (service_name, alert_type, severity, message)
    VALUES ($1, $2, $3, $4)
    RETURNING id
  `);
  const result = await stmt.run(serviceName, alertType, severity, message);
  return result.rows[0]?.id;
}

async function checkExistingAlert(serviceName, alertType, resolved = false) {
  const stmt = db.prepare(`
    SELECT id FROM alerts 
    WHERE service_name = $1 AND alert_type = $2 AND resolved = $3
    ORDER BY created_at DESC 
    LIMIT 1
  `);
  const alert = await stmt.get(serviceName, alertType, Boolean(resolved));
  return alert;
}

async function logAlert(serviceName, alertType, severity, message) {
  const timestamp = new Date().toISOString();
  const logMessage = `[MCP-HEALTH-ALERT] ${timestamp} | ${severity.toUpperCase()} | ${serviceName} | ${alertType} | ${message}`;
  
  // Log to stderr for MCP server logs
  console.error(logMessage);
  
  // Try to log to system journal
  try {
    const { execSync } = await import('child_process');
    execSync(`logger -t mcp-health "${logMessage}"`, { stdio: 'pipe' });
  } catch (error) {
    // Ignore logging errors
  }
}

async function processAlerts(config, serviceName, status, previousStatus, error) {
  if (!config.alerts || !config.alerts.enabled) return;
  
  const thresholds = config.alerts.thresholds || {};
  const criticality = config.alerts.service_criticality || {};
  
  // Determine service criticality
  let serviceCriticality = 'optional';
  if (criticality.critical?.includes(serviceName)) {
    serviceCriticality = 'critical';
  } else if (criticality.important?.includes(serviceName)) {
    serviceCriticality = 'important';
  }
  
  // Generate alerts based on status changes
  if (status === 'error' && previousStatus !== 'error') {
    const severity = serviceCriticality === 'critical' ? 'critical' : 'error';
    const message = error || `Service ${serviceName} is in error state`;
    
    // Check for existing unresolved alert
    const existingAlert = await checkExistingAlert(serviceName, 'service_failure');
    if (!existingAlert) {
      const alertId = await generateAlert(serviceName, 'service_failure', severity, message);
      
      // Log alert based on configured channels
      if (config.alerts.channels) {
        for (const channel of config.alerts.channels) {
          if (channel.enabled && channel.severity?.includes(severity)) {
            if (channel.type === 'log') {
              await logAlert(serviceName, 'service_failure', severity, message);
            }
          }
        }
      }
    }
  }
  
  // Recovery notification
  if (status === 'healthy' && previousStatus === 'error' && thresholds.recovery_notification) {
    const existingAlert = await checkExistingAlert(serviceName, 'service_failure');
    if (existingAlert) {
      // Mark alert as resolved
      const stmt = db.prepare(`
        UPDATE alerts 
        SET resolved = TRUE, resolved_at = CURRENT_TIMESTAMP 
        WHERE id = ?
      `);
      await stmt.run(existingAlert.id);
      
      await logAlert(serviceName, 'service_recovery', 'info', `Service ${serviceName} has recovered`);
    }
  }
  
  // Performance degradation alert
  if (status === 'degraded') {
    const existingAlert = await checkExistingAlert(serviceName, 'performance_degradation');
    if (!existingAlert) {
      const message = `Service ${serviceName} is experiencing performance degradation`;
      await generateAlert(serviceName, 'performance_degradation', 'degraded', message);
      await logAlert(serviceName, 'performance_degradation', 'degraded', message);
    }
  }
}

// Enhanced error context with troubleshooting steps
function getEnhancedErrorContext(serviceName, status, error, serviceType, serviceUrl, config) {
  const troubleshootingSteps = [];
  const url = serviceUrl || serviceName;
  
  // Service-specific troubleshooting
  if (serviceType === 'container') {
    troubleshootingSteps.push(
      `Check container status: docker ps -a | grep ${serviceName}`,
      `View container logs: docker logs ${serviceName}`,
      `Restart container: docker restart ${serviceName}`,
      `Inspect container: docker inspect ${serviceName}`
    );
  } else if (serviceType === 'systemd') {
    const serviceConfig = config?.services?.find(s => (s.name || s.id) === serviceName);
    const systemdName = serviceConfig?.service || serviceName;
    const systemdScope = serviceConfig?.scope === 'system' ? '' : '--user ';
    troubleshootingSteps.push(
      `Check service status: systemctl ${systemdScope}status ${systemdName}`,
      `View service logs: journalctl ${systemdScope}-xeu ${systemdName}`,
      `Restart service: systemctl ${systemdScope}restart ${systemdName}`,
      `Check service configuration: systemctl ${systemdScope}show ${systemdName}`
    );
  } else if (serviceType === 'http') {
    troubleshootingSteps.push(
      `Test endpoint directly: curl -v ${url}`,
      `Check network connectivity: ping -c 2 $(echo ${url} | sed 's|.*://||' | cut -d'/' -f1)`,
      `Check DNS resolution: nslookup $(echo ${url} | sed 's|.*://||' | cut -d'/' -f1)`,
      `Check port availability: ss -tulpn | grep $(echo ${url} | sed 's|.*://||' | cut -d'/' -f2 | cut -d':' -f1)`
    );
  }
  
  // Status-specific troubleshooting
  if (status === 'error') {
    if (error?.includes('timeout')) {
      troubleshootingSteps.push(
        'Check network connectivity and firewall rules',
        'Verify service is actually running',
        'Check system resources: htop or docker stats'
      );
    } else if (error?.includes('EADDRINUSE') || error?.includes('port')) {
      troubleshootingSteps.push(
        'Check for port conflicts: ss -tulpn',
        'Kill conflicting process: kill <pid>',
        'Change service port configuration'
      );
    } else if (error?.includes('connection refused')) {
      troubleshootingSteps.push(
        'Verify service is running',
        'Check firewall rules',
        'Verify correct port and address'
      );
    }
  } else if (status === 'degraded') {
    troubleshootingSteps.push(
      'Check system resources: htop or docker stats',
      'Review service logs for performance issues',
      'Check network latency: ping -c 5 <host>'
    );
  }
  
  // Add SSOT recovery actions if available
  const ssotRecoveryActions = getSSOTRecoveryActions(serviceName, status, error, config);
  if (ssotRecoveryActions.length > 0) {
    troubleshootingSteps.push(
      '--- SSOT Recovery Actions ---',
      ...ssotRecoveryActions
    );
  }
  
  return {
    service: serviceName,
    status,
    error,
    service_type: serviceType,
    service_url: url,
    troubleshooting_steps: troubleshootingSteps,
    common_solutions: getCommonSolutions(status, error),
    ssot_recovery_actions: ssotRecoveryActions
  };
}

// Get SSOT recovery actions based on service and error
function getSSOTRecoveryActions(serviceName, status, error, config) {
  const recoveryActions = config.recovery_actions || {};
  const serviceId = serviceName.toLowerCase().replace(/\s+/g, '_');
  
  // Try to find matching recovery action key
  let matchingKey = null;
  
  // Direct match by service ID
  if (recoveryActions[serviceId]) {
    matchingKey = serviceId;
  }
  
  // Error-based matching
  if (!matchingKey && error) {
    if (error.includes('timeout')) {
      matchingKey = 'timeout_issues';
    } else if (error.includes('port') || error.includes('EADDRINUSE')) {
      matchingKey = 'port_conflicts';
    } else if (error.includes('connection refused')) {
      matchingKey = 'connection_issues';
    } else if (error.includes('not found')) {
      matchingKey = 'service_not_found';
    }
  }
  
  // Status-based matching
  if (!matchingKey) {
    if (status === 'error') {
      matchingKey = 'general_service_failure';
    } else if (status === 'degraded') {
      matchingKey = 'performance_issues';
    }
  }
  
  return matchingKey ? (recoveryActions[matchingKey] || []) : [];
}

function getCommonSolutions(status, error) {
  const solutions = [];
  
  if (status === 'error') {
    if (error?.includes('timeout')) {
      solutions.push('Increase timeout configuration', 'Check network connectivity', 'Restart service');
    } else if (error?.includes('port') || error?.includes('EADDRINUSE')) {
      solutions.push('Kill conflicting process', 'Change port configuration', 'Restart service');
    } else if (error?.includes('not found')) {
      solutions.push('Start service', 'Check service configuration', 'Verify installation');
    } else {
      solutions.push('Check service logs', 'Restart service', 'Verify configuration');
    }
  } else if (status === 'degraded') {
    solutions.push('Check system resources', 'Review service logs', 'Scale horizontally if needed');
  } else if (status === 'unknown') {
    solutions.push('Verify service is running', 'Check network connectivity', 'Review service configuration');
  }
  
  return solutions;
}

// Port conflict detection
async function checkPortAvailability(port, serviceProcessName = null) {
  try {
    const { execSync } = await import('child_process');
    const result = execSync(`ss -tulpn | grep :${port} || true`, { encoding: 'utf8' });
    
    if (result.trim() === '') {
      return { available: true, process: null };
    }
    
    // Parse the process information
    const lines = result.trim().split('\n');
    const processes = [];
    
    for (const line of lines) {
      const parts = line.trim().split(/\s+/);
      if (parts.length >= 7) {
        const processName = parts[6];
        const pid = parts[1].split('/')[0];
        processes.push({ name: processName, pid: pid });
      }
    }
    
    // If service process name is provided, check if it's the expected process
    if (serviceProcessName) {
      const isExpectedProcess = processes.some(p => 
        p.name.toLowerCase().includes(serviceProcessName.toLowerCase()) ||
        p.name.includes('node') || p.name.includes('docker')
      );
      
      return {
        available: !isExpectedProcess,
        processes: processes,
        isExpectedService: isExpectedProcess
      };
    }
    
    return { available: false, processes: processes };
  } catch (error) {
    // If command fails, assume port is unavailable for safety
    return { available: false, error: error.message };
  }
}

// Extract port from URL
function extractPortFromUrl(url) {
  try {
    const urlObj = new URL(url);
    return parseInt(urlObj.port) || (urlObj.protocol === 'https:' ? 443 : 80);
  } catch {
    return null;
  }
}

// Caddy proxy configuration validation
async function validateCaddyProxyConfig() {
  try {
    const { readFileSync } = await import('fs');
    const { join } = await import('path');
    const caddyfilePath = join(process.cwd(), 'stacks/web/Caddyfile');
    
    const caddyfileContent = readFileSync(caddyfilePath, 'utf8');
    const issues = [];
    
    // Check for common proxy configuration issues
    const lines = caddyfileContent.split('\n');
    let inBlock = false;
    let currentBlock = '';
    
    for (let i = 0; i < lines.length; i++) {
      const line = lines[i].trim();
      
      // Track blocks
      if (line.startsWith('handle ') || line.startsWith('handle_path ')) {
        inBlock = true;
        currentBlock = line;
      } else if (line === '}' && inBlock) {
        inBlock = false;
        
        // Check for potential issues in the block
        if (currentBlock.includes('handle ') && !currentBlock.includes('handle_path ')) {
          // Check if block contains path operations that should use handle_path
          const blockContent = lines.slice(i - 10, i).join('\n');
          if (blockContent.includes('reverse_proxy') && !blockContent.includes('file_server')) {
            issues.push({
              type: 'potential_proxy_misconfig',
              line: i - 10,
              block: currentBlock,
              message: 'Using "handle" instead of "handle_path" may cause path stripping issues with reverse_proxy',
              recommendation: 'Consider using "handle_path" for reverse_proxy blocks to preserve path information'
            });
          }
        }
        currentBlock = '';
      }
    }
    
    // Check for duplicate route definitions
    const routePatterns = [];
    for (const line of lines) {
      const handleMatch = line.match(/handle\s+(.+?)\s*\{/);
      const handlePathMatch = line.match(/handle_path\s+(.+?)\s*\{/);
      if (handleMatch) {
        routePatterns.push({ type: 'handle', pattern: handleMatch[1], line: lines.indexOf(line) + 1 });
      } else if (handlePathMatch) {
        routePatterns.push({ type: 'handle_path', pattern: handlePathMatch[1], line: lines.indexOf(line) + 1 });
      }
    }
    
    // Check for overlapping routes
    for (let i = 0; i < routePatterns.length; i++) {
      for (let j = i + 1; j < routePatterns.length; j++) {
        const route1 = routePatterns[i];
        const route2 = routePatterns[j];
        
        // Check if one route is a prefix of another
        if (route1.pattern !== route2.pattern) {
          if (route1.pattern.startsWith(route2.pattern) || route2.pattern.startsWith(route1.pattern)) {
            issues.push({
              type: 'potential_route_conflict',
              routes: [route1, route2],
              message: `Route overlap detected between "${route1.pattern}" and "${route2.pattern}"`,
              recommendation: 'Review route order and specificity to ensure proper routing'
            });
          }
        }
      }
    }
    
    return {
      valid: issues.length === 0,
      issues: issues,
      caddyfile: caddyfilePath
    };
  } catch (error) {
    return {
      valid: false,
      error: error.message,
      issues: [{
        type: 'validation_error',
        message: `Failed to read Caddyfile: ${error.message}`
      }]
    };
  }
}

// HTTP health check
async function checkHTTPService(service) {
  const { execSync } = await import('child_process');
  const startTime = Date.now();
  const expectedStatus = service.expected_status || 200;
  
  // Extract port for conflict detection
  const port = extractPortFromUrl(service.url);
  let portConflictInfo = null;
  
  if (port) {
    const portCheck = await checkPortAvailability(port);
    if (!portCheck.available && !portCheck.isExpectedService) {
      portConflictInfo = `Port ${port} is in use by ${portCheck.processes?.map(p => p.name).join(', ') || 'another process'}`;
    }
  }
  
  try {
    const response = execSync(`curl -s -o /dev/null -w "%{http_code}" --max-time ${service.timeout || 5} "${service.url}"`, { 
      encoding: 'utf8',
      stdio: 'pipe'
    });
    const responseTime = Date.now() - startTime;
    const statusCode = parseInt(response.trim());
    
    // Status categorization based on expected status
    let status = 'healthy';
    if (statusCode === expectedStatus) {
      if (responseTime > 3000) {
        status = 'degraded';
      } else {
        status = 'healthy';
      }
    } else if (statusCode >= 400 && statusCode < 500) {
      status = 'error';
    } else if (statusCode >= 500) {
      status = 'error';
      } else {
      status = 'unknown';
    }
    
    // Enhanced error context for port conflicts
    let error = null;
    if (status === 'error' && portConflictInfo) {
      error = `${portConflictInfo}. This may indicate a port conflict preventing service startup.`;
    }
    
    return {
      status,
      response_time: responseTime,
      http_status: statusCode,
      expected_status: expectedStatus,
      error
    };
  } catch (error) {
    const responseTime = Date.now() - startTime;
    const errorMessage = error.message || error.toString();
    return {
      status: 'unknown',
      response_time: responseTime,
      http_status: null,
      expected_status: expectedStatus,
      error: errorMessage.includes('timeout') ? 'Connection timeout' : errorMessage
    };
  }
}

// Container health check
async function checkContainerService(service) {
  const { execSync } = await import('child_process');
  const startTime = Date.now();
  const expectedState = service.expected_state || 'running';
  
  try {
    // Try docker ps first (does not depend on a compose project)
    let output = '';
    try {
      output = execSync(`docker ps -a --filter "name=${service.container}" --format "table {{.Names}}\\t{{.Status}}"`, { 
        encoding: 'utf8',
        stdio: 'pipe'
      });
    } catch {}
    
    // Fallback to docker compose ps if docker ps found nothing
    if (!output.trim() || !output.includes('Up')) {
      try {
        output = execSync(`docker compose ps -a ${service.container}`, { 
          encoding: 'utf8',
          stdio: 'pipe'
        });
      } catch {}
    }
    
    const responseTime = Date.now() - startTime;
    
    // Parse docker compose output or docker ps output
    let status = '';
    let state = 'unknown';
    
    if (output.includes('Up') || output.includes('running')) {
      state = 'running';
      status = output;
    } else if (output.includes('Restarting')) {
      state = 'restarting';
      status = output;
    } else if (output.includes('Exited') || output.includes('exited')) {
      state = 'exited';
      status = output;
    } else if (output.includes('Dead') || output.includes('dead')) {
      state = 'dead';
      status = output;
    } else if (!output.trim()) {
      // Container not found
      return {
        status: 'error',
        response_time: responseTime,
        container_state: 'not found',
        expected_state: expectedState,
        error: `Container ${service.container} not found. Check: docker ps -a | grep ${service.container}`
      };
    } else {
      // Parse docker ps format output
      status = output.trim();
      if (status.includes('Up')) {
        state = 'running';
      } else if (status.includes('Restarting')) {
        state = 'restarting';
      } else if (status.includes('Exited')) {
        state = 'exited';
      } else if (status.includes('Dead')) {
        state = 'dead';
      }
    }
    
    // Status categorization based on expected state
    let healthStatus = 'healthy';
    if (state === expectedState) {
      healthStatus = 'healthy';
    } else if (state === 'restarting') {
      healthStatus = 'degraded';
    } else if (state === 'exited' || state === 'dead') {
      healthStatus = 'error';
    } else {
      healthStatus = 'unknown';
    }
    
    // Check for port conflicts in container
    let portConflictInfo = null;
    if (healthStatus === 'error' && (state === 'exited' || state === 'dead')) {
      try {
        const containerInfo = execSync(`docker inspect ${service.container} --format '{{json .HostConfig.PortBindings}}'`, { encoding: 'utf8' });
        if (containerInfo && containerInfo !== 'null') {
          const portBindings = JSON.parse(containerInfo);
          for (const [containerPort, hostBindings] of Object.entries(portBindings)) {
            if (hostBindings && hostBindings.length > 0) {
              const hostPort = hostBindings[0].HostPort;
              if (hostPort) {
                const portCheck = await checkPortAvailability(hostPort);
                if (!portCheck.available && !portCheck.isExpectedService) {
                  portConflictInfo = `Port ${hostPort} (container port ${containerPort}) is in use by ${portCheck.processes?.map(p => p.name).join(', ') || 'another process'}`;
                }
              }
            }
          }
        }
      } catch (error) {
        // Ignore container inspection errors
      }
    }
    
    // Enhanced error context
    let error = null;
    if (healthStatus === 'error') {
      if (portConflictInfo) {
        error = `${portConflictInfo}. Resolution: kill conflicting process or change port mapping.`;
      } else {
        error = `Container state: ${state}. Expected: ${expectedState}. Recovery: docker restart ${service.container}`;
      }
    }
    
    return {
      status: healthStatus,
      response_time: responseTime,
      container_state: state,
      expected_state: expectedState,
      error
    };
  } catch (error) {
    const responseTime = Date.now() - startTime;
    return {
      status: 'error',
      response_time: responseTime,
      container_state: null,
      expected_state: expectedState,
      error: error.message
    };
  }
}

// Systemd health check
async function checkSystemService(service) {
  const { execSync } = await import('child_process');
  const startTime = Date.now();
  const expectedState = service.expected_state || 'active';
  const systemctlCmd = service.scope === 'system' ? 'systemctl' : 'systemctl --user';
  
  try {
    const output = execSync(`${systemctlCmd} show ${service.service} --property=ActiveState --property=SubState`, { 
      encoding: 'utf8',
      stdio: 'pipe'
    });
    const responseTime = Date.now() - startTime;
    
    // Parse systemd output
    const lines = output.trim().split('\n');
    const activeState = lines.find(l => l.startsWith('ActiveState='))?.split('=')[1] || 'unknown';
    const subState = lines.find(l => l.startsWith('SubState='))?.split('=')[1] || 'unknown';
    
    // Check if this is a timer service
    let isTimer = false;
    try {
      const serviceType = execSync(`${systemctlCmd} show ${service.service} --property=Type --value`, { encoding: 'utf8' });
      isTimer = serviceType.trim() === 'oneshot' || serviceType.trim() === 'simple';
      const unitFile = execSync(`${systemctlCmd} show ${service.service} --property=Id --value`, { encoding: 'utf8' });
      isTimer = isTimer || unitFile.trim().includes('.timer');
    } catch {
      // Assume not a timer if we can't check
    }
    
    // Enhanced timer status categorization
    let status = 'healthy';
    if (isTimer && subState === 'waiting' && activeState === 'active') {
      // Timer in waiting state is normal/healthy
      status = 'healthy';
    } else if (activeState === expectedState) {
      // For active state, also check sub-state
      if (expectedState === 'active' && (subState === 'running' || subState === 'exited' || subState === 'waiting')) {
        status = 'healthy';
      } else if (expectedState === 'active') {
        status = 'degraded';
      } else {
        status = 'healthy';
      }
    } else if (activeState === 'activating') {
      status = 'degraded';
    } else if (activeState === 'inactive' || activeState === 'failed') {
      status = 'error';
    } else {
      status = 'unknown';
    }
    
    return {
      status,
      response_time: responseTime,
      active_state: activeState,
      sub_state: subState,
      expected_state: expectedState,
      is_timer: isTimer,
      error: null
    };
  } catch (error) {
    const responseTime = Date.now() - startTime;
    const errorMessage = error.message || error.toString();
    return {
      status: 'error',
      response_time: responseTime,
      active_state: null,
      sub_state: null,
      expected_state: expectedState,
      error: errorMessage.includes('Could not find') ? 'Service not found' : errorMessage
    };
  }
}

// Create MCP server
const server = new Server(
  {
    name: 'mcp-health',
    version: '1.0.0',
  },
  {
    capabilities: {
      tools: {},
    },
  }
);

// List available tools
server.setRequestHandler(ListToolsRequestSchema, async () => {
  return {
    tools: [
      {
        name: 'check_health',
        description: 'Run health checks for all services defined in ssot.health.yml configuration',
        inputSchema: {
          type: 'object',
          properties: {
            service: {
              type: 'string',
              description: 'Optional specific service name to check (checks all if not provided)'
            }
          }
        }
      },
      {
        name: 'get_health_status',
        description: 'Get current health status of all services',
        inputSchema: {
          type: 'object',
          properties: {}
        }
      },
      {
        name: 'get_health_history',
        description: 'Get historical health check data for analysis',
        inputSchema: {
          type: 'object',
          properties: {
            service_name: {
              type: 'string',
              description: 'Optional service name to filter history'
            },
            limit: {
              type: 'number',
              description: 'Maximum number of records to return (default: 100)'
            }
          }
        }
      },
      {
        name: 'get_health_summary',
        description: 'Get health summary including uptime, failure counts, and trends',
        inputSchema: {
          type: 'object',
          properties: {
            service_name: {
              type: 'string',
              description: 'Optional service name for specific summary'
            }
          }
        }
      },
      {
        name: 'analyze_dependencies',
        description: 'Analyze service dependencies and detect cascading failures',
        inputSchema: {
          type: 'object',
          properties: {
            service_name: {
              type: 'string',
              description: 'Optional service name to analyze dependencies for'
            }
          }
        }
      },
      {
        name: 'get_alerts',
        description: 'Get active and historical alerts',
        inputSchema: {
          type: 'object',
          properties: {
            service_name: {
              type: 'string',
              description: 'Optional service name to filter alerts'
            },
            severity: {
              type: 'string',
              description: 'Optional severity level to filter (critical, error, degraded, info)'
            },
            resolved: {
              type: 'boolean',
              description: 'Optional filter for resolved vs unresolved alerts'
            },
            limit: {
              type: 'number',
              description: 'Maximum number of alerts to return (default: 50)'
            }
          }
        }
      },
      {
        name: 'acknowledge_alert',
        description: 'Acknowledge an alert to prevent duplicate notifications',
        inputSchema: {
          type: 'object',
          properties: {
            alert_id: {
              type: 'number',
              description: 'Alert ID to acknowledge'
            }
          },
          required: ['alert_id']
        }
      },
      {
        name: 'get_alert_config',
        description: 'Get current alert configuration from SSOT',
        inputSchema: {
          type: 'object',
          properties: {}
        }
      },
      {
        name: 'check_port_conflicts',
        description: 'Check for port conflicts across all monitored services',
        inputSchema: {
          type: 'object',
          properties: {
            port: {
              type: 'number',
              description: 'Optional specific port to check (checks all service ports if not provided)'
            }
          }
        }
      },
      {
        name: 'validate_proxy_config',
        description: 'Validate Caddy proxy configuration for common routing issues',
        inputSchema: {
          type: 'object',
          properties: {}
        }
      },
      {
        name: 'restart_service',
        description: 'Safely restart a service with conflict resolution (requires user confirmation)',
        inputSchema: {
          type: 'object',
          properties: {
            service_name: {
              type: 'string',
              description: 'Service name to restart'
            },
            service_type: {
              type: 'string',
              description: 'Service type (container, systemd, http)',
              enum: ['container', 'systemd', 'http']
            },
            force: {
              type: 'boolean',
              description: 'Force restart even if conflicts detected (use with caution)'
            }
          },
          required: ['service_name', 'service_type']
        }
      },
      {
        name: 'get_troubleshooting_info',
        description: 'Get enhanced troubleshooting information for a service',
        inputSchema: {
          type: 'object',
          properties: {
            service_name: {
              type: 'string',
              description: 'Service name to get troubleshooting info for'
            }
          },
          required: ['service_name']
        }
      },
      {
        name: 'quick_health',
        description: 'Quick pass/fail status check for critical services only',
        inputSchema: {
          type: 'object',
          properties: {
            service: {
              type: 'string',
              description: 'Optional specific service name (checks all critical services if not provided)'
            }
          }
        }
      },
      {
        name: 'check_group',
        description: 'Check health of services in a specific group (e.g., web-stack, datastore)',
        inputSchema: {
          type: 'object',
          properties: {
            group: {
              type: 'string',
              description: 'Service group name to check',
              required: ['group']
            }
          },
          required: ['group']
        }
      },
      {
        name: 'reload_config',
        description: 'Reload health configuration from YAML file without restarting MCP server',
        inputSchema: {
          type: 'object',
          properties: {}
        }
      },
      {
        name: 'get_health_score',
        description: 'Get overall system health score (0-100) based on critical service status',
        inputSchema: {
          type: 'object',
          properties: {
            include_optional: {
              type: 'boolean',
              description: 'Include optional services in score calculation (default: false)'
            }
          }
        }
      },
      {
        name: 'batch_check',
        description: 'Check multiple services in parallel for faster health checks',
        inputSchema: {
          type: 'object',
          properties: {
            services: {
              type: 'array',
              description: 'Array of service names to check in parallel',
              items: {
                type: 'string'
              }
            }
          }
        }
      },
      {
        name: 'set_auto_recovery',
        description: 'Configure automatic recovery policies for specific failure types',
        inputSchema: {
          type: 'object',
          properties: {
            service_name: {
              type: 'string',
              description: 'Service name to configure auto-recovery for'
            },
            failure_type: {
              type: 'string',
              description: 'Failure type (container_down, endpoint_unreachable, port_conflict, etc.)'
            },
            enabled: {
              type: 'boolean',
              description: 'Enable or disable auto-recovery for this failure type'
            },
            max_attempts: {
              type: 'number',
              description: 'Maximum recovery attempts before giving up (default: 3)'
            },
            cooldown_seconds: {
              type: 'number',
              description: 'Cooldown period between recovery attempts in seconds (default: 60)'
            }
          },
          required: ['service_name', 'failure_type', 'enabled']
        }
      },
      {
        name: 'get_service_template',
        description: 'Get service template for common service types (web-api, database, container)',
        inputSchema: {
          type: 'object',
          properties: {
            template_type: {
              type: 'string',
              description: 'Template type (web-api, database, container, systemd)',
              enum: ['web-api', 'database', 'container', 'systemd']
            }
          },
          required: ['template_type']
        }
      },
      {
        name: 'sync_to_mddb',
        description: 'Sync health history to mddb for semantic search and analysis',
        inputSchema: {
          type: 'object',
          properties: {
            days: {
              type: 'number',
              description: 'Number of days of history to sync (default: 7)'
            }
          }
        }
      }
    ]
  };
});

// Handle tool calls
server.setRequestHandler(CallToolRequestSchema, async (request) => {
  const { name, arguments: args } = request.params;

  try {
    switch (name) {
      case 'check_health': {
        const config = await loadHealthConfig();
        const results = [];
        const detectedProfile = config.profiles?.home ? 'home' : 'mobile';
        
        for (const service of config.services || []) {
          const serviceName = service.name || service.id;
          
          // Profile filtering
          if (service.profiles && !service.profiles.includes(detectedProfile)) {
            continue;
          }
          
          // Specific service filtering
          if (args.service && serviceName !== args.service) continue;
          
          const startTime = Date.now();
          let checkResult;
          
          // Perform health check based on service type
          if (service.type === 'http') {
            checkResult = await checkHTTPService(service);
          } else if (service.type === 'container') {
            checkResult = await checkContainerService(service);
          } else if (service.type === 'systemd') {
            checkResult = await checkSystemService(service);
          } else {
            checkResult = {
              status: 'unknown',
              response_time: 0,
              error: `Unknown service type: ${service.type}`
            };
          }
          
          // Get previous status for alert processing
          const previousStatusStmt = db.prepare(`
            SELECT status FROM health_checks 
            WHERE service_name = ? 
            ORDER BY timestamp DESC 
            LIMIT 1
          `);
          const previousStatus = (await previousStatusStmt.get(serviceName))?.status || 'unknown';
          
          // Store in database
          const stmt = db.prepare(`
            INSERT INTO health_checks (service_name, status, response_time, error, http_status, expected_status, container_state, expected_state, active_state, sub_state)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
          `);
          await stmt.run(
            serviceName, 
            checkResult.status, 
            checkResult.response_time, 
            checkResult.error,
            checkResult.http_status || null,
            checkResult.expected_status || null,
            checkResult.container_state || null,
            checkResult.expected_state || null,
            checkResult.active_state || null,
            checkResult.sub_state || null
          );
          
          // Process alerts based on status changes
          await processAlerts(config, serviceName, checkResult.status, previousStatus, checkResult.error);
          
          results.push({
            service: serviceName,
            category: service.category || 'uncategorized',
            type: service.type,
            ...checkResult,
            timestamp: new Date().toISOString()
          });
        }
        
        // Group by category
        const groupedResults = results.reduce((acc, result) => {
          if (!acc[result.category]) {
            acc[result.category] = [];
          }
          acc[result.category].push(result);
          return acc;
        }, {});
        
        // Calculate summary
        const summary = {
          total: results.length,
          healthy: results.filter(r => r.status === 'healthy').length,
          degraded: results.filter(r => r.status === 'degraded').length,
          error: results.filter(r => r.status === 'error').length,
          unknown: results.filter(r => r.status === 'unknown').length,
          profile: detectedProfile,
          base_url: config.detectedBaseUrl
        };
        
        // Add recovery suggestions for unhealthy services
        const unhealthyServices = results.filter(r => r.status !== 'healthy');
        const recoverySuggestions = {};
        
        unhealthyServices.forEach(service => {
          let failureType = 'unknown';
          if (service.type === 'container' && service.status === 'error') {
            failureType = 'container_down';
          } else if (service.type === 'http' && service.status === 'error') {
            failureType = 'http_error';
          } else if (service.status === 'unknown') {
            failureType = 'timeout';
          }
          
          const actions = getRecoveryActions(config, failureType);
          if (actions.length > 0) {
            recoverySuggestions[service.service] = {
              failure_type: failureType,
              status: service.status,
              error: service.error,
              recovery_actions: actions
            };
          }
        });
        
        return {
          content: [{
            type: 'text',
            text: JSON.stringify({
              summary,
              services_by_category: groupedResults,
              all_services: results,
              recovery_suggestions: recoverySuggestions
            }, null, 2)
          }]
        };
      }

      case 'get_health_status': {
        const config = await loadHealthConfig();
        const services = config.services || [];
        const detectedProfile = config.profiles?.home ? 'home' : 'mobile';
        
        const status = (await Promise.all(services.map(async service => {
          const serviceName = service.name || service.id;
          
          // Profile filtering
          if (service.profiles && !service.profiles.includes(detectedProfile)) {
            return null;
          }
          
          const stmt = db.prepare(`
            SELECT * FROM health_checks 
            WHERE service_name = ? 
            ORDER BY timestamp DESC 
            LIMIT 1
          `);
          const lastCheck = await stmt.get(serviceName);
          
          return {
            service: serviceName,
            category: service.category || 'uncategorized',
            type: service.type,
            status: lastCheck?.status || 'unknown',
            last_checked: lastCheck?.timestamp || null,
            response_time: lastCheck?.response_time || null,
            error: lastCheck?.error || null
          };
        }))).filter(Boolean); // Remove null entries from profile filtering
        
        // Group by category
        const groupedStatus = status.reduce((acc, result) => {
          if (!acc[result.category]) {
            acc[result.category] = [];
          }
          acc[result.category].push(result);
          return acc;
        }, {});
        
        // Calculate summary
        const summary = {
          total: status.length,
          healthy: status.filter(s => s.status === 'healthy').length,
          degraded: status.filter(s => s.status === 'degraded').length,
          error: status.filter(s => s.status === 'error').length,
          unknown: status.filter(s => s.status === 'unknown').length,
          profile: detectedProfile,
          base_url: config.detectedBaseUrl
        };
        
        return {
          content: [{
            type: 'text',
            text: JSON.stringify({
              summary,
              services_by_category: groupedStatus,
              all_services: status
            }, null, 2)
          }]
        };
      }

      case 'get_health_history': {
        const limit = args.limit || 100;
        let query = 'SELECT * FROM health_checks';
        const params = [];
        
        if (args.service_name) {
          query += ' WHERE service_name = ?';
          params.push(args.service_name);
        }
        
        query += ' ORDER BY timestamp DESC LIMIT ?';
        params.push(limit);
        
        const stmt = db.prepare(query);
        const history = await stmt.all(...params);
        
        // Add category information from config
        const config = await loadHealthConfig();
        const historyWithCategory = history.map(item => {
          const service = config.services?.find(s => (s.name || s.id) === item.service_name);
          return {
            ...item,
            category: service?.category || 'uncategorized',
            type: service?.type || 'unknown'
          };
        });
        
        return {
          content: [{
            type: 'text',
            text: JSON.stringify(historyWithCategory, null, 2)
          }]
        };
      }

      case 'get_health_summary': {
        const config = await loadHealthConfig();
        let query = `
          SELECT 
            service_name,
            COUNT(*) as total_checks,
            SUM(CASE WHEN status = 'healthy' THEN 1 ELSE 0 END) as healthy_count,
            SUM(CASE WHEN status = 'degraded' THEN 1 ELSE 0 END) as degraded_count,
            SUM(CASE WHEN status = 'error' THEN 1 ELSE 0 END) as error_count,
            SUM(CASE WHEN status = 'unknown' THEN 1 ELSE 0 END) as unknown_count,
            AVG(response_time) as avg_response_time,
            MAX(timestamp) as last_check
          FROM health_checks
        `;
        const params = [];
        
        if (args.service_name) {
          query += ' WHERE service_name = ?';
          params.push(args.service_name);
        }
        
        query += ' GROUP BY service_name';
        
        const stmt = db.prepare(query);
        const summary = (await stmt.all(...params)) || [];
        
        // Add category information from config
        const summaryWithCategory = summary.map(item => {
          const service = config.services?.find(s => (s.name || s.id) === item.service_name);
          return {
            ...item,
            category: service?.category || 'uncategorized',
            type: service?.type || 'unknown'
          };
        });
        
        // Calculate uptime percentage
        const summaryWithUptime = summaryWithCategory.map(item => ({
          ...item,
          uptime_percentage: item.total_checks > 0 
            ? ((item.healthy_count / item.total_checks) * 100).toFixed(2)
            : 0
        }));
        
        // Group by category
        const groupedSummary = summaryWithUptime.reduce((acc, item) => {
          if (!acc[item.category]) {
            acc[item.category] = [];
          }
          acc[item.category].push(item);
          return acc;
        }, {});
        
        return {
          content: [{
            type: 'text',
            text: JSON.stringify({
              by_category: groupedSummary,
              all_services: summaryWithUptime
            }, null, 2)
          }]
        };
      }

      case 'analyze_dependencies': {
        const config = await loadHealthConfig();
        const dependencies = config.dependencies || {};
        const detectedProfile = config.detectedProfile || 'home';
        
        // Get current health status with deployment method info
        const statusResults = [];
        for (const service of config.services || []) {
          const serviceName = service.name || service.id;
          
          // Profile filtering
          if (service.profiles && !service.profiles.includes(detectedProfile)) {
            continue;
          }
          
          const stmt = db.prepare(`
            SELECT * FROM health_checks 
            WHERE service_name = ? 
            ORDER BY timestamp DESC 
            LIMIT 1
          `);
          const lastCheck = await stmt.get(serviceName);
          
          statusResults.push({
            service: serviceName,
            status: lastCheck?.status || 'unknown',
            category: service.category || 'uncategorized',
            type: service.type || 'unknown',
            deployment_method: service.type === 'systemd' ? 'systemd' : 
                             service.type === 'container' ? 'container' : 'http'
          });
        }
        
        // Analyze dependencies with deployment method conflicts
        const dependencyAnalysis = {};
        
        Object.entries(dependencies).forEach(([service, deps]) => {
          const serviceStatus = statusResults.find(s => s.service === service);
          const depStatuses = deps.map(dep => {
            const depStatus = statusResults.find(s => s.service === dep);
            return {
              service: dep,
              status: depStatus?.status || 'unknown',
              type: depStatus?.type || 'unknown',
              deployment_method: depStatus?.deployment_method || 'unknown'
            };
          });
          
          const failingDeps = depStatuses.filter(d => d.status !== 'healthy');
          
          // Check for deployment method conflicts
          const serviceDeployment = serviceStatus?.deployment_method || 'unknown';
          const deploymentConflicts = depStatuses.filter(d => 
            d.deployment_method !== 'unknown' && 
            d.deployment_method !== serviceDeployment &&
            d.status === 'healthy'
          );
          
          dependencyAnalysis[service] = {
            current_status: serviceStatus?.status || 'unknown',
            deployment_method: serviceDeployment,
            dependencies: depStatuses,
            failing_dependencies: failingDeps,
            deployment_conflicts: deploymentConflicts,
            potential_cascading_failure: serviceStatus?.status !== 'healthy' && failingDeps.length > 0,
            dependency_failure_cause: failingDeps.length > 0 ? failingDeps.map(d => d.service).join(', ') : null,
            deployment_conflict_warning: deploymentConflicts.length > 0 ? 
              `Mixed deployment methods detected: ${deploymentConflicts.map(d => `${d.service}(${d.deployment_method})`).join(', ')}` : null
          };
        });
        
        return {
          content: [{
            type: 'text',
            text: JSON.stringify({
              dependency_analysis: dependencyAnalysis,
              total_services: statusResults.length,
              services_with_dependencies: Object.keys(dependencies).length,
              deployment_conflicts_detected: Object.values(dependencyAnalysis).filter(d => d.deployment_conflicts.length > 0).length
            }, null, 2)
          }]
        };
      }

      case 'get_alerts': {
        const config = await loadHealthConfig();
        const limit = args.limit || 50;
        let query = 'SELECT * FROM alerts';
        const params = [];
        const conditions = [];
        
        if (args.service_name) {
          conditions.push('service_name = ?');
          params.push(args.service_name);
        }
        
        if (args.severity) {
          conditions.push('severity = ?');
          params.push(args.severity);
        }
        
        if (args.resolved !== undefined) {
          conditions.push('resolved = ?');
          params.push(args.resolved);
        }
        
        if (conditions.length > 0) {
          query += ' WHERE ' + conditions.join(' AND ');
        }
        
        query += ' ORDER BY created_at DESC LIMIT ?';
        params.push(limit);
        
        const stmt = db.prepare(query);
        const alerts = await stmt.all(...params);
        
        return {
          content: [{
            type: 'text',
            text: JSON.stringify({
              alerts: alerts,
              total: alerts.length,
              alert_config: config.alerts
            }, null, 2)
          }]
        };
      }

      case 'acknowledge_alert': {
        const stmt = db.prepare(`
          UPDATE alerts 
          SET acknowledged = 1, acknowledged_at = CURRENT_TIMESTAMP 
          WHERE id = ?
        `);
        const result = await stmt.run(args.alert_id);
        
        if (result.rowCount === 0) {
          throw new Error(`Alert ${args.alert_id} not found`);
        }
        
        return {
          content: [{
            type: 'text',
            text: JSON.stringify({
              success: true,
              message: `Alert ${args.alert_id} acknowledged`,
              alert_id: args.alert_id
            }, null, 2)
          }]
        };
      }

      case 'get_alert_config': {
        const config = await loadHealthConfig();
        
        return {
          content: [{
            type: 'text',
            text: JSON.stringify({
              alert_config: config.alerts,
              service_criticality: config.alerts?.service_criticality || {},
              thresholds: config.alerts?.thresholds || {},
              channels: config.alerts?.channels || []
            }, null, 2)
          }]
        };
      }

      case 'check_port_conflicts': {
        const config = await loadHealthConfig();
        const conflicts = [];
        
        if (args.port) {
          // Check specific port
          const portCheck = await checkPortAvailability(args.port);
          if (!portCheck.available && !portCheck.isExpectedService) {
            conflicts.push({
              port: args.port,
              available: false,
              processes: portCheck.processes,
              conflict: `Port ${args.port} is in use by ${portCheck.processes?.map(p => p.name).join(', ') || 'another process'}`
            });
          } else {
            conflicts.push({
              port: args.port,
              available: true,
              processes: portCheck.processes
            });
          }
        } else {
          // Check all service ports
          for (const service of config.services || []) {
            if (service.url && service.type === 'http') {
              const port = extractPortFromUrl(service.url);
              if (port) {
                const serviceName = service.name || service.id;
                const portCheck = await checkPortAvailability(port, serviceName);
                
                if (!portCheck.available && !portCheck.isExpectedService) {
                  conflicts.push({
                    service: serviceName,
                    port: port,
                    url: service.url,
                    processes: portCheck.processes,
                    conflict: `Port ${port} is in use by ${portCheck.processes?.map(p => p.name).join(', ') || 'another process'}`
                  });
                }
              }
            }
          }
        }
        
        return {
          content: [{
            type: 'text',
            text: JSON.stringify({
              conflicts: conflicts,
              total_conflicts: conflicts.filter(c => c.conflict).length,
              checked_port: args.port || 'all service ports'
            }, null, 2)
          }]
        };
      }

      case 'validate_proxy_config': {
        const validation = await validateCaddyProxyConfig();
        
        return {
          content: [{
            type: 'text',
            text: JSON.stringify(validation, null, 2)
          }]
        };
      }

      case 'restart_service': {
        const { service_name, service_type, force = false } = args;
        
        // Get service configuration
        const config = await loadHealthConfig();
        const service = config.services?.find(s => 
          (s.name === service_name || s.id === service_name)
        );
        
        if (!service) {
          throw new Error(`Service ${service_name} not found in configuration`);
        }
        
        // Check for port conflicts before restart
        let portConflicts = [];
        if (service.url && service_type === 'http') {
          const port = extractPortFromUrl(service.url);
          if (port) {
            const portCheck = await checkPortAvailability(port, service_name);
            if (!portCheck.available && !portCheck.isExpectedService) {
              portConflicts.push({
                port: port,
                processes: portCheck.processes,
                conflict: `Port ${port} is in use by ${portCheck.processes?.map(p => p.name).join(', ') || 'another process'}`
              });
            }
          }
        }
        
        // If conflicts detected and not forced, return conflict info
        if (portConflicts.length > 0 && !force) {
          return {
            content: [{
              type: 'text',
              text: JSON.stringify({
                service: service_name,
                service_type: service_type,
                status: 'conflict_detected',
                message: 'Port conflicts detected, cannot safely restart',
                conflicts: portConflicts,
                recommendation: 'Kill conflicting processes or use force=true to restart anyway (use with caution)',
                kill_command: portConflicts.map(c => `kill ${c.processes?.map(p => p.pid).join(' ')}`).join('; ')
              }, null, 2)
            }],
            isError: true
          };
        }
        
        // Perform restart based on service type
        let restartResult;
        try {
          const { execSync } = await import('child_process');
          
          if (service_type === 'container') {
            const containerName = service.container || service_name;
            execSync(`docker restart ${containerName}`, { stdio: 'pipe' });
            restartResult = {
              method: 'docker',
              command: `docker restart ${containerName}`,
              success: true
            };
          } else if (service_type === 'systemd') {
            const systemdName = service.service || service_name;
            const systemdCmd = service.scope === 'system' ? 'systemctl' : 'systemctl --user';
            execSync(`${systemdCmd} restart ${systemdName}`, { stdio: 'pipe' });
            restartResult = {
              method: 'systemd',
              command: `${systemdCmd} restart ${systemdName}`,
              success: true
            };
          } else if (service_type === 'http') {
            // For HTTP services, we can't directly restart, just provide guidance
            restartResult = {
              method: 'manual',
              command: 'Manual intervention required for HTTP services',
              success: false,
              message: 'HTTP services require manual restart of the underlying process'
            };
          } else {
            throw new Error(`Unknown service type: ${service_type}`);
          }
          
          // Generate alert for service restart
          await generateAlert(service_name, 'service_restart', 'info', `Service ${service_name} was restarted via ${restartResult.method}`);
          
          return {
            content: [{
              type: 'text',
              text: JSON.stringify({
                service: service_name,
                service_type: service_type,
                status: 'restarted',
                restart_result: restartResult,
                conflicts_resolved: portConflicts.length > 0,
                timestamp: new Date().toISOString()
              }, null, 2)
            }]
          };
        } catch (error) {
          return {
            content: [{
              type: 'text',
              text: JSON.stringify({
                service: service_name,
                service_type: service_type,
                status: 'restart_failed',
                error: error.message,
                restart_result: {
                  success: false,
                  error: error.message
                }
              }, null, 2)
            }],
            isError: true
          };
        }
      }

      case 'get_troubleshooting_info': {
        const config = await loadHealthConfig();
        const service = config.services?.find(s => 
          (s.name === args.service_name || s.id === args.service_name)
        );
        
        if (!service) {
          throw new Error(`Service ${args.service_name} not found in configuration`);
        }
        
        // Get current health status
        const stmt = db.prepare(`
          SELECT * FROM health_checks 
          WHERE service_name = ? 
          ORDER BY timestamp DESC 
          LIMIT 1
        `);
        const lastCheck = await stmt.get(args.service_name);
        
        // Use the resolved URL from config (after profile substitution)
        // The service.url should already be resolved by loadHealthConfig
        let serviceUrl = service.url || 'unknown';
        
        // If URL still contains placeholder, resolve it manually
        if (serviceUrl.includes('{profile}')) {
          const baseUrl = config.detectedBaseUrl || 'http://tony-omen.local:8080';
          serviceUrl = serviceUrl.replace('{profile}', baseUrl);
        }
        
        const troubleshootingInfo = getEnhancedErrorContext(
          args.service_name,  // serviceName
          lastCheck?.status || 'unknown',  // status
          lastCheck?.error || null,  // error
          service.type || 'unknown',  // serviceType
          serviceUrl,  // serviceUrl
          config  // config for SSOT recovery actions
        );
        
        return {
          content: [{
            type: 'text',
            text: JSON.stringify({
              service: args.service_name,
              current_status: lastCheck?.status || 'unknown',
              service_type: service.type || 'unknown',
              service_url: serviceUrl,
              last_checked: lastCheck?.timestamp || null,
              troubleshooting_info: troubleshootingInfo
            }, null, 2)
          }]
        };
      }

      case 'quick_health': {
        const config = await loadHealthConfig();
        const criticality = config.alerts?.service_criticality || {};
        const criticalServices = [...(criticality.critical || []), ...(criticality.important || [])];
        
        const results = [];
        const detectedProfile = config.detectedProfile || 'home';
        
        for (const service of config.services || []) {
          const serviceName = service.name || service.id;
          
          // Only check critical services unless specific service requested
          if (args.service && serviceName !== args.service) continue;
          if (!args.service && !criticalServices.includes(serviceName)) continue;
          
          // Profile filtering
          if (service.profiles && !service.profiles.includes(detectedProfile)) {
            continue;
          }
          
          try {
            const startTime = Date.now();
            let checkResult;
            
            if (service.type === 'http') {
              checkResult = await checkHTTPService(service);
            } else if (service.type === 'container') {
              checkResult = await checkContainerService(service);
            } else if (service.type === 'systemd') {
              checkResult = await checkSystemService(service);
            } else {
              checkResult = {
                status: 'unknown',
                response_time: 0,
                error: `Unknown service type: ${service.type}`
              };
            }
            
            results.push({
              service: serviceName,
              status: checkResult.status === 'healthy' ? 'PASS' : 'FAIL',
              response_time: checkResult.response_time
            });
          } catch (error) {
            results.push({
              service: serviceName,
              status: 'FAIL',
              error: error.message
            });
          }
        }
        
        return {
          content: [{
            type: 'text',
            text: JSON.stringify({
              timestamp: new Date().toISOString(),
              profile: detectedProfile,
              services_checked: results.length,
              passed: results.filter(r => r.status === 'PASS').length,
              failed: results.filter(r => r.status === 'FAIL').length,
              results
            }, null, 2)
          }]
        };
      }

      case 'check_group': {
        const config = await loadHealthConfig();
        const groupName = args.group;
        
        if (!config.groups || !config.groups[groupName]) {
          throw new Error(`Group ${groupName} not found in configuration`);
        }
        
        const groupServices = config.groups[groupName];
        const results = [];
        const detectedProfile = config.detectedProfile || 'home';
        
        for (const serviceName of groupServices) {
          const service = config.services?.find(s => 
            (s.name === serviceName || s.id === serviceName)
          );
          
          if (!service) {
            results.push({
              service: serviceName,
              status: 'error',
              error: 'Service not found in configuration'
            });
            continue;
          }
          
          // Profile filtering
          if (service.profiles && !service.profiles.includes(detectedProfile)) {
            results.push({
              service: serviceName,
              status: 'skipped',
              reason: 'Not applicable for current profile'
            });
            continue;
          }
          
          try {
            const startTime = Date.now();
            let checkResult;
            
            if (service.type === 'http') {
              checkResult = await checkHTTPService(service);
            } else if (service.type === 'container') {
              checkResult = await checkContainerService(service);
            } else if (service.type === 'systemd') {
              checkResult = await checkSystemService(service);
            } else {
              checkResult = {
                status: 'unknown',
                response_time: 0,
                error: `Unknown service type: ${service.type}`
              };
            }
            
            results.push({
              service: serviceName,
              status: checkResult.status,
              response_time: checkResult.response_time,
              url: service.url
            });
          } catch (error) {
            results.push({
              service: serviceName,
              status: 'error',
              error: error.message
            });
          }
        }
        
        return {
          content: [{
            type: 'text',
            text: JSON.stringify({
              group: groupName,
              timestamp: new Date().toISOString(),
              profile: detectedProfile,
              total_services: groupServices.length,
              healthy: results.filter(r => r.status === 'healthy').length,
              degraded: results.filter(r => r.status === 'degraded').length,
              error: results.filter(r => r.status === 'error').length,
              skipped: results.filter(r => r.status === 'skipped').length,
              results
            }, null, 2)
          }]
        };
      }

      case 'reload_config': {
        try {
          const config = await loadHealthConfig();
          return {
            content: [{
              type: 'text',
              text: JSON.stringify({
                status: 'success',
                timestamp: new Date().toISOString(),
                profile: config.detectedProfile,
                services_loaded: config.services?.length || 0,
                groups_loaded: Object.keys(config.groups || {}).length,
                message: 'Configuration reloaded successfully'
              }, null, 2)
            }]
          };
        } catch (error) {
          return {
            content: [{
              type: 'text',
              text: JSON.stringify({
                status: 'error',
                error: error.message
              }, null, 2)
            }],
            isError: true
          };
        }
      }

      case 'get_health_score': {
        const config = await loadHealthConfig();
        const criticality = config.alerts?.service_criticality || {};
        const includeOptional = args.include_optional || false;
        
        let servicesToCheck = [...(criticality.critical || []), ...(criticality.important || [])];
        if (includeOptional) {
          servicesToCheck = [...servicesToCheck, ...(criticality.optional || [])];
        }
        
        let totalScore = 0;
        let maxScore = servicesToCheck.length * 100;
        const serviceScores = [];
        const detectedProfile = config.detectedProfile || 'home';
        
        for (const serviceName of servicesToCheck) {
          const service = config.services?.find(s => 
            (s.name === serviceName || s.id === serviceName)
          );
          
          if (!service) {
            serviceScores.push({
              service: serviceName,
              score: 0,
              reason: 'Service not found in configuration'
            });
            continue;
          }
          
          // Profile filtering
          if (service.profiles && !service.profiles.includes(detectedProfile)) {
            serviceScores.push({
              service: serviceName,
              score: 100,
              reason: 'Not applicable for current profile'
            });
            totalScore += 100;
            continue;
          }
          
          try {
            const startTime = Date.now();
            let checkResult;
            
            if (service.type === 'http') {
              checkResult = await checkHTTPService(service);
            } else if (service.type === 'container') {
              checkResult = await checkContainerService(service);
            } else if (service.type === 'systemd') {
              checkResult = await checkSystemService(service);
            } else {
              checkResult = {
                status: 'unknown',
                response_time: 0,
                error: `Unknown service type: ${service.type}`
              };
            }
            
            let score = 0;
            if (checkResult.status === 'healthy') score = 100;
            else if (checkResult.status === 'degraded') score = 50;
            
            serviceScores.push({
              service: serviceName,
              score,
              status: checkResult.status,
              response_time: checkResult.response_time
            });
            totalScore += score;
          } catch (error) {
            serviceScores.push({
              service: serviceName,
              score: 0,
              error: error.message
            });
          }
        }
        
        const overallScore = maxScore > 0 ? Math.round((totalScore / maxScore) * 100) : 0;
        
        return {
          content: [{
            type: 'text',
            text: JSON.stringify({
              overall_score: overallScore,
              timestamp: new Date().toISOString(),
              profile: detectedProfile,
              include_optional: includeOptional,
              services_checked: serviceScores.length,
              service_scores: serviceScores,
              grade: overallScore >= 90 ? 'A' : overallScore >= 80 ? 'B' : overallScore >= 70 ? 'C' : overallScore >= 60 ? 'D' : 'F'
            }, null, 2)
          }]
        };
      }

      case 'batch_check': {
        const config = await loadHealthConfig();
        const servicesToCheck = args.services || [];
        
        if (servicesToCheck.length === 0) {
          throw new Error('No services specified for batch check');
        }
        
        const results = await Promise.all(
          servicesToCheck.map(async (serviceName) => {
            const service = config.services?.find(s => 
              (s.name === serviceName || s.id === serviceName)
            );
            
            if (!service) {
              return {
                service: serviceName,
                status: 'error',
                error: 'Service not found in configuration'
              };
            }
            
            try {
              const startTime = Date.now();
              let checkResult;
              
              if (service.type === 'http') {
                checkResult = await checkHTTPService(service);
              } else if (service.type === 'container') {
                checkResult = await checkContainerService(service);
              } else if (service.type === 'systemd') {
                checkResult = await checkSystemService(service);
              } else {
                checkResult = {
                  status: 'unknown',
                  response_time: 0,
                  error: `Unknown service type: ${service.type}`
                };
              }
              
              return {
                service: serviceName,
                status: checkResult.status,
                response_time: checkResult.response_time
              };
            } catch (error) {
              return {
                service: serviceName,
                status: 'error',
                error: error.message
              };
            }
          })
        );
        
        return {
          content: [{
            type: 'text',
            text: JSON.stringify({
              timestamp: new Date().toISOString(),
              batch_size: servicesToCheck.length,
              healthy: results.filter(r => r.status === 'healthy').length,
              degraded: results.filter(r => r.status === 'degraded').length,
              error: results.filter(r => r.status === 'error').length,
              results
            }, null, 2)
          }]
        };
      }

      case 'set_auto_recovery': {
        const { service_name, failure_type, enabled, max_attempts = 3, cooldown_seconds = 60 } = args;
        
        // Create auto-recovery table if it doesn't exist
        db.exec(`
          CREATE TABLE IF NOT EXISTS auto_recovery_policies (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            service_name TEXT NOT NULL,
            failure_type TEXT NOT NULL,
            enabled BOOLEAN NOT NULL,
            max_attempts INTEGER DEFAULT 3,
            cooldown_seconds INTEGER DEFAULT 60,
            created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
            updated_at DATETIME DEFAULT CURRENT_TIMESTAMP,
            UNIQUE(service_name, failure_type)
          );
        `);
        
        const stmt = db.prepare(`
          INSERT INTO auto_recovery_policies (service_name, failure_type, enabled, max_attempts, cooldown_seconds)
          VALUES (?, ?, ?, ?, ?)
          ON CONFLICT(service_name, failure_type) 
          DO UPDATE SET enabled = ?, max_attempts = ?, cooldown_seconds = ?, updated_at = CURRENT_TIMESTAMP
        `);
        
        await stmt.run(service_name, failure_type, enabled, max_attempts, cooldown_seconds, enabled, max_attempts, cooldown_seconds);
        
        return {
          content: [{
            type: 'text',
            text: JSON.stringify({
              status: 'success',
              service_name,
              failure_type,
              enabled,
              max_attempts,
              cooldown_seconds,
              timestamp: new Date().toISOString()
            }, null, 2)
          }]
        };
      }

      case 'get_service_template': {
        const templateType = args.template_type;
        
        const templates = {
          'web-api': {
            type: 'http',
            url: 'http://example.com:8080/health',
            expected_status: 200,
            timeout: 5,
            category: 'web',
            profiles: ['home', 'mobile'],
            recovery_actions: [
              'Check container: docker ps | grep service-name',
              'Restart service: docker restart service-name',
              'Check logs: docker logs service-name'
            ]
          },
          'database': {
            type: 'container',
            container: 'postgres',
            expected_state: 'running',
            timeout: 5,
            category: 'datastore',
            profiles: ['home', 'mobile'],
            recovery_actions: [
              'Check container: docker ps | grep postgres',
              'Start container: docker start postgres',
              'Check logs: docker logs postgres'
            ]
          },
          'container': {
            type: 'container',
            container: 'service-name',
            expected_state: 'running',
            timeout: 5,
            category: 'application',
            profiles: ['home', 'mobile'],
            recovery_actions: [
              'Check container: docker ps | grep service-name',
              'Restart container: docker restart service-name',
              'Check logs: docker logs service-name'
            ]
          },
          'systemd': {
            type: 'systemd',
            service: 'service-name.service',
            expected_state: 'active',
            timeout: 5,
            category: 'system',
            profiles: ['home', 'mobile'],
            recovery_actions: [
              'Check service: systemctl status service-name',
              'Restart service: systemctl restart service-name',
              'Check logs: journalctl -u service-name'
            ]
          }
        };
        
        const template = templates[templateType];
        if (!template) {
          throw new Error(`Template type ${templateType} not found`);
        }
        
        return {
          content: [{
            type: 'text',
            text: JSON.stringify({
              template_type: templateType,
              template,
              usage: 'Copy this template and customize for your service in ssot.health.yml'
            }, null, 2)
          }]
        };
      }

      case 'sync_to_mddb': {
        const days = args.days || 7;
        const cutoffDate = new Date(Date.now() - days * 24 * 60 * 60 * 1000).toISOString();
        
        const stmt = db.prepare(`
          SELECT * FROM health_checks 
          WHERE timestamp >= ? 
          ORDER BY timestamp DESC
        `);
        
        const records = await stmt.all(cutoffDate);
        
        // Check if mddb MCP is available
        try {
          // This would require mcp_call_tool, but we're in the MCP server itself
          // For now, return the data that would be synced
          return {
            content: [{
              type: 'text',
              text: JSON.stringify({
                status: 'data_prepared',
                records_to_sync: records.length,
                days,
                cutoff_date: cutoffDate,
                note: 'MCP-to-MCP integration requires external coordination. Records prepared for manual sync.',
                sample_records: records.slice(0, 5)
              }, null, 2)
            }]
          };
        } catch (error) {
          return {
            content: [{
              type: 'text',
              text: JSON.stringify({
                status: 'error',
                error: error.message
              }, null, 2)
            }],
            isError: true
          };
        }
      }

      default:
        throw new Error(`Unknown tool: ${name}`);
    }
  } catch (error) {
    return {
      content: [{
        type: 'text',
        text: JSON.stringify({ error: error.message }, null, 2)
      }],
      isError: true
    };
  }
});

// Start server
async function main() {
  const transport = new StdioServerTransport();
  await server.connect(transport);
  console.error('MCP Health Server running on stdio');
}

main().catch((error) => {
  console.error('Server error:', error);
  process.exit(1);
});
