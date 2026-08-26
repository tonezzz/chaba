#!/usr/bin/env node

import { createRequire } from 'module';

const require = createRequire(import.meta.url);
const { Client } = require('/home/tony/CascadeProjects/chaba/mcp-servers/mcp-health/node_modules/@modelcontextprotocol/sdk/dist/cjs/client/index.js');
const { StdioClientTransport } = require('/home/tony/CascadeProjects/chaba/mcp-servers/mcp-health/node_modules/@modelcontextprotocol/sdk/dist/cjs/client/stdio.js');
import { writeFileSync } from 'fs';

async function createMCPClient() {
  try {
    const client = new Client({
      name: 'baseline-collector',
      version: '1.0.0'
    }, {
      capabilities: {}
    });

    const transport = new StdioClientTransport({
      command: '/usr/bin/node',
      args: ['/home/tony/CascadeProjects/chaba/mcp-servers/mcp-health/server.js'],
      env: {
        HEALTH_CONFIG: '/home/tony/CascadeProjects/chaba/docs/ssot/infrastructure/ssot.health.yml',
        HEALTH_SKILL: '/home/tony/CascadeProjects/chaba/.agents/skills/health-check/SKILL.md'
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

async function collectHealthHistory(client, days = 7) {
  try {
    const result = await client.callTool({
      name: 'get_health_history',
      arguments: {
        limit: 10000
      }
    });

    if (result.content && result.content.length > 0) {
      let historyData = result.content[0].text ? JSON.parse(result.content[0].text) : [];
      
      if (!Array.isArray(historyData)) {
        if (historyData.history && Array.isArray(historyData.history)) {
          historyData = historyData.history;
        } else {
          console.log('Health history data is not in expected format');
          return null;
        }
      }
      
      // Filter by date range
      const cutoffDate = new Date();
      cutoffDate.setDate(cutoffDate.getDate() - days);
      
      const filteredHistory = historyData.filter(check => {
        const checkDate = new Date(check.timestamp);
        return checkDate >= cutoffDate;
      });

      console.log(`Collected ${filteredHistory.length} health checks from ${days} days`);
      return filteredHistory;
    } else {
      console.log('No health history data found');
      return null;
    }
  } catch (error) {
    console.error(`Failed to collect health history: ${error.message}`);
    return null;
  }
}

function calculateBaselines(historyData) {
  const baselines = {};
  
  // Group by service name
  const byService = {};
  historyData.forEach(check => {
    if (!byService[check.service_name]) {
      byService[check.service_name] = [];
    }
    byService[check.service_name].push(check);
  });

  // Calculate baselines for each service
  Object.keys(byService).forEach(serviceName => {
    const checks = byService[serviceName];
    
    // Establish baselines for all services with any data (minimum 1 check)
    const healthyChecks = checks.filter(c => c.status === 'healthy');
    
    if (healthyChecks.length === 0) {
      console.log(`Skipping ${serviceName}: no healthy data available`);
      return;
    }

    const responseTimes = healthyChecks.map(c => c.response_time).filter(rt => rt !== null && rt > 0);
    
    if (responseTimes.length === 0) {
      console.log(`Skipping ${serviceName}: no valid response times`);
      return;
    }

    // Calculate statistics
    responseTimes.sort((a, b) => a - b);
    const mean = responseTimes.reduce((sum, rt) => sum + rt, 0) / responseTimes.length;
    const median = responseTimes[Math.floor(responseTimes.length / 2)];
    const p95 = responseTimes[Math.floor(responseTimes.length * 0.95)] || responseTimes[responseTimes.length - 1];
    const p99 = responseTimes[Math.floor(responseTimes.length * 0.99)] || responseTimes[responseTimes.length - 1];
    const min = responseTimes[0];
    const max = responseTimes[responseTimes.length - 1];
    
    // Calculate standard deviation
    const variance = responseTimes.reduce((sum, rt) => sum + Math.pow(rt - mean, 2), 0) / responseTimes.length;
    const stdDev = Math.sqrt(variance);

    baselines[serviceName] = {
      service_name: serviceName,
      category: checks[0].category || 'unknown',
      type: checks[0].type || 'unknown',
      total_checks: checks.length,
      healthy_checks: healthyChecks.length,
      healthy_percentage: (healthyChecks.length / checks.length) * 100,
      response_time: {
        mean: Math.round(mean),
        median: Math.round(median),
        p95: Math.round(p95),
        p99: Math.round(p99),
        min: Math.round(min),
        max: Math.round(max),
        std_dev: Math.round(stdDev)
      },
      data_quality: {
        sample_size: healthyChecks.length,
        confidence: healthyChecks.length >= 5 ? 'high' : healthyChecks.length >= 3 ? 'medium' : 'low',
        date_range: {
          start: new Date(Math.min(...checks.map(c => new Date(c.timestamp)))).toISOString(),
          end: new Date(Math.max(...checks.map(c => new Date(c.timestamp)))).toISOString()
        }
      },
      established: new Date().toISOString()
    };
  });

  return baselines;
}

async function main() {
  console.log('Starting performance baseline collection...');
  
  const client = await createMCPClient();
  if (!client) {
    console.error('Failed to create MCP client');
    process.exit(1);
  }

  try {
    // Collect 7 days of health history (adjusted based on available data)
    const historyData = await collectHealthHistory(client, 7);
    
    if (!historyData || historyData.length === 0) {
      console.error('No health history data available');
      process.exit(1);
    }

    // Calculate baselines
    const baselines = calculateBaselines(historyData);
    
    console.log(`Established baselines for ${Object.keys(baselines).length} services`);
    
    // Save baselines to file
    const baselineFile = '/home/tony/CascadeProjects/chaba/docs/ssot/infrastructure/performance-baselines.yml';
    const yaml = require('js-yaml');
    writeFileSync(baselineFile, yaml.dump({ baselines }), 'utf8');
    
    console.log(`Baselines saved to ${baselineFile}`);
    
    // Print summary
    console.log('\nBaseline Summary:');
    Object.values(baselines).forEach(baseline => {
      console.log(`- ${baseline.service_name}: ${baseline.response_time.median}ms median, ${baseline.healthy_percentage.toFixed(1)}% healthy`);
    });

  } catch (error) {
    console.error('Baseline collection failed:', error);
    process.exit(1);
  } finally {
    await closeMCPClient(client);
  }
}

main();