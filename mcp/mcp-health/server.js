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
import Database from 'better-sqlite3';

const __filename = fileURLToPath(import.meta.url);
const __dirname = dirname(__filename);

// Database setup for health history
const db = new Database(join(__dirname, 'health-history.db'));
db.exec(`
  CREATE TABLE IF NOT EXISTS health_checks (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
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
    timestamp DATETIME DEFAULT CURRENT_TIMESTAMP
  );
  CREATE INDEX IF NOT EXISTS idx_service_timestamp ON health_checks(service_name, timestamp);
  CREATE INDEX IF NOT EXISTS idx_status ON health_checks(status);
  
  CREATE TABLE IF NOT EXISTS alerts (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    service_name TEXT NOT NULL,
    alert_type TEXT NOT NULL,
    severity TEXT NOT NULL,
    message TEXT NOT NULL,
    acknowledged BOOLEAN DEFAULT 0,
    acknowledged_at DATETIME,
    resolved BOOLEAN DEFAULT 0,
    resolved_at DATETIME,
    created_at DATETIME DEFAULT CURRENT_TIMESTAMP
  );
  CREATE INDEX IF NOT EXISTS idx_alerts_service ON alerts(service_name);
  CREATE INDEX IF NOT EXISTS idx_alerts_severity ON alerts(severity);
  CREATE INDEX IF NOT EXISTS idx_alerts_resolved ON alerts(resolved);
`);

// Read health configuration
async function loadHealthConfig() {
  const configPath = process.env.HEALTH_CONFIG || join(process.cwd(), 'docs/ssot/infrastructure/ssot.health.yml');
  console.error(`Loading health config from: ${configPath}`);
  try {
    const file = readFileSync(configPath, 'utf8');
    const config = yaml.parse(file);
    
    // Auto-detect network profile
    let profile = 'home';
    let baseUrl = 'http://tony-omen.local:8080';
    
    try {
      const { execSync } = await import('child_process');
      execSync('ping -c 1 -W 1 tony-omen.local', { stdio: 'ignore' });
    } catch {
      profile = 'mobile';
      try {
        const { execSync } = await import('child_process');
        const ip = execSync('ip route get 1.1.1.1 | awk \'{print $7}\'', { encoding: 'utf8' }).trim();
        baseUrl = `http://${ip}:8080`;
      } catch {
        baseUrl = 'http://localhost:8080';
      }
    }
    
    console.error(`Detected profile: ${profile}, base URL: ${baseUrl}`);
    
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
function generateAlert(serviceName, alertType, severity, message) {
  const stmt = db.prepare(`
    INSERT INTO alerts (service_name, alert_type, severity, message)
    VALUES (?, ?, ?, ?)
  `);
  const result = stmt.run(serviceName, alertType, severity, message);
  return result.lastInsertRowid;
}

function checkExistingAlert(serviceName, alertType, resolved = false) {
  const stmt = db.prepare(`
    SELECT id FROM alerts 
    WHERE service_name = ? AND alert_type = ? AND resolved = ?
    ORDER BY created_at DESC 
    LIMIT 1
  `);
  const alert = stmt.get(serviceName, alertType, resolved ? 1 : 0);
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
    const existingAlert = checkExistingAlert(serviceName, 'service_failure');
    if (!existingAlert) {
      const alertId = generateAlert(serviceName, 'service_failure', severity, message);
      
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
    const existingAlert = checkExistingAlert(serviceName, 'service_failure');
    if (existingAlert) {
      // Mark alert as resolved
      const stmt = db.prepare(`
        UPDATE alerts 
        SET resolved = 1, resolved_at = CURRENT_TIMESTAMP 
        WHERE id = ?
      `);
      stmt.run(existingAlert.id);
      
      await logAlert(serviceName, 'service_recovery', 'info', `Service ${serviceName} has recovered`);
    }
  }
  
  // Performance degradation alert
  if (status === 'degraded') {
    const existingAlert = checkExistingAlert(serviceName, 'performance_degradation');
    if (!existingAlert) {
      const message = `Service ${serviceName} is experiencing performance degradation`;
      generateAlert(serviceName, 'performance_degradation', 'degraded', message);
      await logAlert(serviceName, 'performance_degradation', 'degraded', message);
    }
  }
}

// HTTP health check
async function checkHTTPService(service) {
  const { execSync } = await import('child_process');
  const startTime = Date.now();
  const expectedStatus = service.expected_status || 200;
  
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
    
    return {
      status,
      response_time: responseTime,
      http_status: statusCode,
      expected_status: expectedStatus,
      error: null
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
    // Try docker ps first (more reliable for individual containers)
    const output = execSync(`docker ps -a --filter "name=${service.container}" --format "{{.Status}}"`, { 
      encoding: 'utf8',
      stdio: 'pipe'
    });
    const responseTime = Date.now() - startTime;
    
    if (!output.trim()) {
      return {
        status: 'error',
        response_time: responseTime,
        container_state: 'not found',
        expected_state: expectedState,
        error: `Container ${service.container} not found`
      };
    }
    
    const status = output.trim();
    
    // Parse docker status
    let state = 'unknown';
    if (status.includes('Up')) {
      state = 'running';
    } else if (status.includes('Restarting')) {
      state = 'restarting';
    } else if (status.includes('Exited')) {
      state = 'exited';
    } else if (status.includes('Dead')) {
      state = 'dead';
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
    
    return {
      status: healthStatus,
      response_time: responseTime,
      container_state: state,
      expected_state: expectedState,
      error: null
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
  
  try {
    const output = execSync(`systemctl --user show ${service.service} --property=ActiveState --property=SubState`, { 
      encoding: 'utf8',
      stdio: 'pipe'
    });
    const responseTime = Date.now() - startTime;
    
    // Parse systemd output
    const lines = output.trim().split('\n');
    const activeState = lines.find(l => l.startsWith('ActiveState='))?.split('=')[1] || 'unknown';
    const subState = lines.find(l => l.startsWith('SubState='))?.split('=')[1] || 'unknown';
    
    // Status categorization based on expected state
    let status = 'healthy';
    if (activeState === expectedState) {
      // For active state, also check sub-state
      if (expectedState === 'active' && (subState === 'running' || subState === 'exited')) {
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
          const previousStatus = previousStatusStmt.get(serviceName)?.status || 'unknown';
          
          // Store in database
          const stmt = db.prepare(`
            INSERT INTO health_checks (service_name, status, response_time, error, http_status, expected_status, container_state, expected_state, active_state, sub_state)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
          `);
          stmt.run(
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
        
        const status = services.map(service => {
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
          const lastCheck = stmt.get(serviceName);
          
          return {
            service: serviceName,
            category: service.category || 'uncategorized',
            type: service.type,
            status: lastCheck?.status || 'unknown',
            last_checked: lastCheck?.timestamp || null,
            response_time: lastCheck?.response_time || null,
            error: lastCheck?.error || null
          };
        }).filter(Boolean); // Remove null entries from profile filtering
        
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
        const history = stmt.all(...params);
        
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
        const summary = stmt.all(...params);
        
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
        
        // Get current health status
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
          const lastCheck = stmt.get(serviceName);
          
          statusResults.push({
            service: serviceName,
            status: lastCheck?.status || 'unknown',
            category: service.category || 'uncategorized'
          });
        }
        
        // Analyze dependencies
        const dependencyAnalysis = {};
        
        Object.entries(dependencies).forEach(([service, deps]) => {
          const serviceStatus = statusResults.find(s => s.service === service);
          const depStatuses = deps.map(dep => {
            const depStatus = statusResults.find(s => s.service === dep);
            return {
              service: dep,
              status: depStatus?.status || 'unknown'
            };
          });
          
          const failingDeps = depStatuses.filter(d => d.status !== 'healthy');
          
          dependencyAnalysis[service] = {
            current_status: serviceStatus?.status || 'unknown',
            dependencies: depStatuses,
            failing_dependencies: failingDeps,
            potential_cascading_failure: serviceStatus?.status !== 'healthy' && failingDeps.length > 0,
            dependency_failure_cause: failingDeps.length > 0 ? failingDeps.map(d => d.service).join(', ') : null
          };
        });
        
        return {
          content: [{
            type: 'text',
            text: JSON.stringify({
              dependency_analysis: dependencyAnalysis,
              total_services: statusResults.length,
              services_with_dependencies: Object.keys(dependencies).length
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
          params.push(args.resolved ? 1 : 0);
        }
        
        if (conditions.length > 0) {
          query += ' WHERE ' + conditions.join(' AND ');
        }
        
        query += ' ORDER BY created_at DESC LIMIT ?';
        params.push(limit);
        
        const stmt = db.prepare(query);
        const alerts = stmt.all(...params);
        
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
        const result = stmt.run(args.alert_id);
        
        if (result.changes === 0) {
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
