#!/usr/bin/env node

/**
 * Health Check API
 * Simple API to run health checks and return results
 */

import { createServer } from 'http';
import { readFileSync, existsSync } from 'fs';
import { execSync } from 'child_process';

const PORT = 3006;
const SSOT_HEALTH_FILE = '/home/tony/CascadeProjects/chaba/docs/ssot/infrastructure/ssot.health.yml';

/**
 * Parse YAML service configuration
 */
function parseHealthConfig(yamlText) {
  const lines = yamlText.split('\n');
  const services = [];
  let inServices = false;
  let currentService = null;
  let indentLevel = 0;

  for (const line of lines) {
    const trimmed = line.trim();
    const indent = line.search(/\S|$/);

    if (trimmed === 'services:') {
      inServices = true;
      continue;
    }

    if (inServices && indent === 2 && trimmed.startsWith('- id:')) {
      if (currentService) {
        services.push(currentService);
      }
      currentService = {
        id: trimmed.substring(5).trim(),
        type: 'http',
        category: 'other'
      };
      continue;
    }

    if (currentService && inServices && indent === 4) {
      if (trimmed.startsWith('type:')) {
        currentService.type = trimmed.substring(5).trim();
      } else if (trimmed.startsWith('url:')) {
        let url = trimmed.substring(4).trim();
        // Strip quotes if present
        if ((url.startsWith('"') && url.endsWith('"')) || (url.startsWith("'") && url.endsWith("'"))) {
          url = url.slice(1, -1);
        }
        currentService.url = url;
      } else if (trimmed.startsWith('container:')) {
        currentService.container = trimmed.substring(10).trim();
      } else if (trimmed.startsWith('service:')) {
        currentService.service = trimmed.substring(8).trim();
      } else if (trimmed.startsWith('category:')) {
        currentService.category = trimmed.substring(9).trim();
      } else if (trimmed.startsWith('name:')) {
        currentService.name = trimmed.substring(5).trim();
      }
    }
  }

  if (currentService) {
    services.push(currentService);
  }

  return services;
}

/**
 * Check HTTP service
 */
function checkHTTPService(service) {
  try {
    let url = service.url;
    
    // Handle both quoted and unquoted profile placeholders
    url = url.replace(/"{profile}"/g, 'http://tony-omen.local:8080');
    url = url.replace(/{profile}/g, 'http://tony-omen.local:8080');
    
    const start = Date.now();
    const output = execSync(`curl -s -o /dev/null -w '%{http_code}' --max-time 5 "${url}"`, {
      encoding: 'utf8',
      timeout: 6000
    });
    const responseTime = Date.now() - start;
    const statusCode = parseInt(output.trim());

    if (statusCode >= 200 && statusCode < 300) {
      return { status: 'healthy', response_time };
    } else if (statusCode >= 400 && statusCode < 500) {
      return { status: 'error', error: `HTTP ${statusCode}`, response_time };
    } else {
      return { status: 'degraded', error: `HTTP ${statusCode}`, response_time };
    }
  } catch (error) {
    return { status: 'error', error: error.message, response_time: 0 };
  }
}

/**
 * Check container service
 */
function checkContainerService(service) {
  try {
    const output = execSync(`docker compose ps ${service.container} --format json`, {
      encoding: 'utf8',
      cwd: '/home/tony/CascadeProjects/chaba/stacks/web',
      timeout: 5000
    });
    
    if (!output || output.trim() === '') {
      return { status: 'error', error: 'Container not found or not running' };
    }
    
    const containers = JSON.parse(output);

    if (containers.length === 0) {
      return { status: 'error', error: 'Container not found' };
    }

    const container = containers[0];
    const state = container.State || '';

    if (state.includes('running')) {
      return { status: 'healthy' };
    } else if (state.includes('restarting')) {
      return { status: 'degraded', error: 'Container restarting' };
    } else {
      return { status: 'error', error: `Container state: ${state}` };
    }
  } catch (error) {
    return { status: 'error', error: error.message };
  }
}

/**
 * Check systemd service
 */
function checkSystemService(service) {
  try {
    const output = execSync(`systemctl --user is-active ${service.service}`, {
      encoding: 'utf8',
      timeout: 3000
    });
    const state = output.trim();

    if (state === 'active') {
      return { status: 'healthy' };
    } else {
      return { status: 'error', error: `Service state: ${state}` };
    }
  } catch (error) {
    return { status: 'error', error: error.message };
  }
}

/**
 * Run health check
 */
function runHealthCheck() {
  try {
    // Load SSOT health config
    if (!existsSync(SSOT_HEALTH_FILE)) {
      return {
        status: 'error',
        services: [],
        summary: { total: 0, healthy: 0, degraded: 0, error: 0 },
        error: 'SSOT health config not found',
        checkedAt: new Date().toISOString()
      };
    }

    const yamlText = readFileSync(SSOT_HEALTH_FILE, 'utf8');
    const services = parseHealthConfig(yamlText);

    // Check each service
    const results = services.map(service => {
      let result;
      try {
        if (service.type === 'http') {
          result = checkHTTPService(service);
        } else if (service.type === 'container') {
          result = checkContainerService(service);
        } else if (service.type === 'systemd') {
          result = checkSystemService(service);
        } else {
          result = { status: 'error', error: `Unknown type: ${service.type}`, response_time: 0 };
        }
      } catch (error) {
        result = { status: 'error', error: error.message, response_time: 0 };
      }

      return {
        ...service,
        ...result
      };
    });

    // Calculate summary
    const summary = {
      total: results.length,
      healthy: results.filter(s => s.status === 'healthy').length,
      degraded: results.filter(s => s.status === 'degraded').length,
      error: results.filter(s => s.status === 'error').length
    };

    return {
      status: summary.error > 0 ? 'error' : summary.degraded > 0 ? 'degraded' : 'healthy',
      services: results,
      summary,
      checkedAt: new Date().toISOString()
    };
  } catch (error) {
    console.error('Health check failed:', error);
    return {
      status: 'error',
      services: [],
      summary: { total: 0, healthy: 0, degraded: 0, error: 0 },
      error: error.message,
      checkedAt: new Date().toISOString()
    };
  }
}

const server = createServer((req, res) => {
  // Enable CORS
  res.setHeader('Access-Control-Allow-Origin', '*');
  res.setHeader('Access-Control-Allow-Methods', 'GET, OPTIONS');
  res.setHeader('Access-Control-Allow-Headers', 'Content-Type');
  
  if (req.method === 'OPTIONS') {
    res.writeHead(200);
    res.end();
    return;
  }
  
  const url = new URL(req.url, `http://localhost:${PORT}`);
  const path = url.pathname;
  
  if (path === '/health' || path === '/api/health') {
    const healthData = runHealthCheck();
    res.writeHead(200, { 'Content-Type': 'application/json' });
    res.end(JSON.stringify(healthData));
    return;
  }
  
  res.writeHead(404, { 'Content-Type': 'application/json' });
  res.end(JSON.stringify({ error: 'Not found' }));
});

server.listen(PORT, '0.0.0.0', () => {
  console.log(`Health Check API listening on port ${PORT}`);
});
