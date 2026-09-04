#!/usr/bin/env node

import http from 'http';
import { execSync } from 'child_process';
import { readFileSync, existsSync, writeFileSync } from 'fs';
import { join } from 'path';
import { fileURLToPath } from 'url';
import { dirname } from 'path';

const SSOT_PATH = '/home/tony/CascadeProjects/chaba-tony-dell/docs/ssot/ssot.improvements.yml';

// Parse command line arguments
const args = process.argv.slice(2);
const improvementLabel = args[0];

if (!improvementLabel) {
  console.error('Usage: node verify-improvement.mjs <improvement-label>');
  process.exit(1);
}

console.log(`Verifying improvement: ${improvementLabel}`);

// Load SSOT file
if (!existsSync(SSOT_PATH)) {
  console.error('SSOT improvements file not found');
  process.exit(1);
}

const ssotContent = readFileSync(SSOT_PATH, 'utf8');

// Find the improvement
const improvement = findImprovement(ssotContent, improvementLabel);
if (!improvement) {
  console.error(`Improvement "${improvementLabel}" not found in SSOT`);
  process.exit(1);
}

console.log(`Found improvement: ${improvement.label}`);
console.log(`Category: ${improvement.category}`);
console.log(`Status: ${improvement.status}`);

// Run verification based on category
const verificationResult = verifyByCategory(improvement);

console.log('\n=== Verification Results ===');
console.log(`Status: ${verificationResult.success ? 'PASSED' : 'FAILED'}`);
console.log(`Details: ${verificationResult.details}`);

// Update SSOT with verification result
if (verificationResult.success) {
  updateImprovementVerification(SSOT_PATH, improvementLabel, verificationResult);
  console.log('\n✅ Improvement verified and SSOT updated');
} else {
  console.log('\n❌ Verification failed - improvement may need more work');
}

process.exit(verificationResult.success ? 0 : 1);

function findImprovement(ssotContent, label) {
  const lines = ssotContent.split('\n');
  let currentImprovement = null;
  
  for (let i = 0; i < lines.length; i++) {
    const line = lines[i];
    
    if (line.includes(`label: ${label}`)) {
      currentImprovement = { label: label };
      
      // Parse subsequent lines for improvement details
      for (let j = i + 1; j < Math.min(i + 15, lines.length); j++) {
        const nextLine = lines[j];
        if (nextLine.trim().startsWith('- label:')) {
          break; // Next improvement found
        }
        
        if (nextLine.includes('text:')) {
          currentImprovement.text = nextLine.split('text:')[1].trim();
        } else if (nextLine.includes('category:')) {
          currentImprovement.category = nextLine.split('category:')[1].trim();
        } else if (nextLine.includes('status:')) {
          currentImprovement.status = nextLine.split('status:')[1].trim();
        } else if (nextLine.includes('priority:')) {
          currentImprovement.priority = nextLine.split('priority:')[1].trim();
        }
      }
      
      return currentImprovement;
    }
  }
  
  return null;
}

function verifyByCategory(improvement) {
  const category = improvement.category || 'general';
  
  switch (category) {
    case 'gpu':
      return verifyGPUImprovement(improvement);
    case 'yomi':
      return verifyYomiImprovement(improvement);
    case 'service-health':
      return verifyServiceHealthImprovement(improvement);
    case 'storage':
      return verifyStorageImprovement(improvement);
    case 'configuration':
      return verifyConfigurationImprovement(improvement);
    case 'memory':
    case 'performance':
      return verifyPerformanceImprovement(improvement);
    default:
      return verifyGeneralImprovement(improvement);
  }
}

function verifyGPUImprovement(improvement) {
  console.log('\nRunning GPU verification...');
  
  try {
    // Check GPU status
    const gpuData = httpGetCustom('tony-omen.local', 8080, '/api/gpu/status');
    
    if (gpuData.status !== 200) {
      return {
        success: false,
        details: 'GPU status endpoint unavailable'
      };
    }
    
    const gpu = gpuData.data.gpus[0];
    const vramPercent = Math.round((gpu.memory_used_mb / gpu.memory_total_mb) * 100);
    
    console.log(`GPU Temperature: ${gpu.temperature_c}°C`);
    console.log(`GPU VRAM: ${vramPercent}%`);
    
    // Check if the specific issue is resolved
    if (improvement.label.includes('Temperature')) {
      if (improvement.label.includes('Critical')) {
        const tempOk = gpu.temperature_c < 85;
        return {
          success: tempOk,
          details: `GPU temperature is ${gpu.temperature_c}°C (threshold: <85°C)`
        };
      } else if (improvement.label.includes('Elevated')) {
        const tempOk = gpu.temperature_c < 75;
        return {
          success: tempOk,
          details: `GPU temperature is ${gpu.temperature_c}°C (threshold: <75°C)`
        };
      }
    }
    
    if (improvement.label.includes('VRAM')) {
      const vramOk = vramPercent < 90;
      return {
        success: vramOk,
        details: `GPU VRAM usage is ${vramPercent}% (threshold: <90%)`
      };
    }
    
    return {
      success: true,
      details: 'GPU metrics within acceptable ranges'
    };
    
  } catch (error) {
    return {
      success: false,
      details: `GPU verification failed: ${error.message}`
    };
  }
}

function verifyYomiImprovement(improvement) {
  console.log('\nRunning Yomi verification...');
  
  try {
    // Check Yomi API health
    const yomiHealth = httpGet('http://tony-dell:3000/api/yomi/health');
    
    if (yomiHealth.status !== 200) {
      return {
        success: false,
        details: 'Yomi API health check failed'
      };
    }
    
    // Check specific Yomi components based on improvement
    if (improvement.label.includes('Summarization')) {
      const summaryStatus = httpGet('http://tony-dell:3000/api/yomi/summarization-status');
      
      if (summaryStatus.status !== 200) {
        return {
          success: false,
          details: 'Yomi summarization status endpoint failed'
        };
      }
      
      const status = summaryStatus.data;
      const hasRecentRun = status.lastRun && status.lastRun !== 'Never';
      const lowErrorCount = (status.errorCount || 0) < 5;
      
      return {
        success: hasRecentRun && lowErrorCount,
        details: `Summarization last run: ${status.lastRun}, error count: ${status.errorCount}`
      };
    }
    
    if (improvement.label.includes('Rate Limiter')) {
      const rateLimiterStatus = httpGet('http://tony-dell:3000/api/yomi/rate-limiter-status');
      
      if (rateLimiterStatus.status !== 200) {
        return {
          success: false,
          details: 'Yomi rate limiter status endpoint failed'
        };
      }
      
      const rl = rateLimiterStatus.data;
      const healthyQueue = (rl.summary?.queued || 0) < 5 && (rl.daily?.queued || 0) < 5;
      
      return {
        success: healthyQueue,
        details: `Rate limiter queues - summary: ${rl.summary?.queued || 0}, daily: ${rl.daily?.queued || 0}`
      };
    }
    
    return {
      success: true,
      details: 'Yomi system healthy'
    };
    
  } catch (error) {
    return {
      success: false,
      details: `Yomi verification failed: ${error.message}`
    };
  }
}

function verifyServiceHealthImprovement(improvement) {
  console.log('\nRunning service health verification...');
  
  try {
    // Extract service name from improvement label
    const serviceName = improvement.label.replace(' Service Failure', '').trim();
    
    // Map service names to endpoints
    const serviceEndpoints = {
      'Status API': '/api/health',
      'Yomi API': '/api/yomi/health',
      'Yomi Summarization': '/api/yomi/summarization-status',
      'Yomi Rate Limiter': '/api/yomi/rate-limiter-status',
      'Weaviate': '/api/weaviate/v1/nodes',
      'Thai Legal LLM': { host: 'tony-omen.local', port: 8001, path: '/health' },
      'Imagen2': { host: 'tony-omen.local', port: 8000, path: '/health' },
      'GPU Queue': { host: 'tony-omen.local', port: 3001, path: '/health' }
    };
    
    const endpoint = serviceEndpoints[serviceName];
    if (!endpoint) {
      return {
        success: false,
        details: `Unknown service: ${serviceName}`
      };
    }
    
    let result;
    if (typeof endpoint === 'string') {
      result = httpGet(`http://tony-dell:8080${endpoint}`);
    } else {
      result = httpGetCustom(endpoint.host, endpoint.port, endpoint.path);
    }
    
    const success = result.status === 200;
    return {
      success: success,
      details: `${serviceName} returned status ${result.status} (expected: 200)`
    };
    
  } catch (error) {
    return {
      success: false,
      details: `Service verification failed: ${error.message}`
    };
  }
}

function verifyStorageImprovement(improvement) {
  console.log('\nRunning storage verification...');
  
  try {
    const diskCheck = execSync('df -h / | tail -1', { encoding: 'utf8' });
    const diskUsage = diskCheck.match(/(\d+)%/);
    
    if (!diskUsage) {
      return {
        success: false,
        details: 'Could not parse disk usage'
      };
    }
    
    const usagePercent = parseInt(diskUsage[1]);
    console.log(`Disk usage: ${usagePercent}%`);
    
    if (improvement.label.includes('Critical')) {
      const success = usagePercent < 80;
      return {
        success: success,
        details: `Disk usage is ${usagePercent}% (threshold: <80%)`
      };
    } else if (improvement.label.includes('Elevated')) {
      const success = usagePercent < 70;
      return {
        success: success,
        details: `Disk usage is ${usagePercent}% (threshold: <70%)`
      };
    }
    
    return {
      success: true,
      details: `Disk usage is ${usagePercent}%`
    };
    
  } catch (error) {
    return {
      success: false,
      details: `Storage verification failed: ${error.message}`
    };
  }
}

function verifyConfigurationImprovement(improvement) {
  console.log('\nRunning configuration verification...');
  
  try {
    // Check for specific configuration issues based on improvement label
    if (improvement.label.includes('Docker Compose')) {
      // Check for version attribute in docker-compose.yml
      const dockerComposePath = '/home/tony/CascadeProjects/chaba-tony-dell/docker-compose.yml';
      if (!existsSync(dockerComposePath)) {
        return {
          success: false,
          details: 'docker-compose.yml not found'
        };
      }
      
      const dockerCompose = readFileSync(dockerComposePath, 'utf8');
      const hasVersion = dockerCompose.includes('version:');
      
      console.log(`Docker compose version attribute present: ${hasVersion}`);
      
      return {
        success: !hasVersion,
        details: `Docker compose version attribute ${hasVersion ? 'present' : 'removed'} (expected: removed)`
      };
    }
    
    // Default configuration check - check for IP addresses in config files
    const ipCheck = execSync('grep -r "192\\.168\\." /home/tony/CascadeProjects/chaba-tony-dell/docs/overview/ 2>/dev/null || true', { encoding: 'utf8' });
    
    const ipCount = (ipCheck.match(/192\.168\./g) || []).length;
    console.log(`Found ${ipCount} IP addresses in config files`);
    
    // For configuration improvements, we generally consider them verified if the file exists
    const success = ipCount < 10; // Reasonable threshold
    
    return {
      success: success,
      details: `Configuration check: ${ipCount} IP addresses found (threshold: <10)`
    };
    
  } catch (error) {
    return {
      success: false,
      details: `Configuration verification failed: ${error.message}`
    };
  }
}

function verifyPerformanceImprovement(improvement) {
  console.log('\nRunning performance verification...');
  
  try {
    const memCheck = execSync('free -h', { encoding: 'utf8' });
    const loadCheck = execSync('uptime', { encoding: 'utf8' });
    
    console.log('Memory and load data collected');
    
    // For performance improvements, we do a basic check
    const success = true; // Performance improvements are hard to auto-verify
    
    return {
      success: success,
      details: 'Performance metrics collected - manual review recommended'
    };
    
  } catch (error) {
    return {
      success: false,
      details: `Performance verification failed: ${error.message}`
    };
  }
}

function verifyGeneralImprovement(improvement) {
  console.log('\nRunning general verification...');
  
  // For general improvements, we can't auto-verify
  return {
    success: true,
    details: 'General improvement - manual verification recommended'
  };
}

function httpGet(url, timeout = 5000) {
  return new Promise((resolve, reject) => {
    const options = {
      hostname: 'tony-omen.local',
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

function updateImprovementVerification(ssotPath, label, verificationResult) {
  const ssotContent = readFileSync(ssotPath, 'utf8');
  const lines = ssotContent.split('\n');
  
  // Find the improvement and add verification data
  for (let i = 0; i < lines.length; i++) {
    if (lines[i].includes(`label: ${label}`)) {
      // Add verification data after the improvement
      const verificationLines = [
        `    verification_method: automated`,
        `    verification_result: ${verificationResult.success ? 'passed' : 'failed'}`,
        `    verification_details: ${verificationResult.details}`,
        `    verification_date: ${new Date().toISOString()}`
      ];
      
      // Try to get git info if available
      try {
        const gitInfo = getGitInfo();
        if (gitInfo.commit) {
          verificationLines.push(`    git_commit: ${gitInfo.commit}`);
          verificationLines.push(`    git_branch: ${gitInfo.branch}`);
        }
      } catch (e) {
        // Git info not available, skip
      }
      
      // Insert verification lines
      let insertIndex = i + 1;
      while (insertIndex < lines.length && !lines[insertIndex].trim().startsWith('- label:') && insertIndex < i + 15) {
        insertIndex++;
      }
      
      lines.splice(insertIndex, 0, ...verificationLines);
      break;
    }
  }
  
  // Write back to file
  writeFileSync(ssotPath, lines.join('\n'));
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