#!/usr/bin/env node
/**
 * Security & Dependency Scanning Module
 * Integrates with overnight-assessment.mjs for automated security scanning
 */

import { execSync } from 'child_process';
import fs from 'fs';
import path from 'path';
import { fileURLToPath } from 'url';

const __filename = fileURLToPath(import.meta.url);
const __dirname = path.dirname(__filename);

// Security scan results
const securityResults = {
  dockerImages: [],
  pythonDependencies: [],
  nodeDependencies: [],
  containerAges: [],
  timestamp: new Date().toISOString()
};

// Docker images to scan
const dockerImages = [
  'caddy:2-alpine',
  'ghcr.io/blakeblackshear/frigate:stable',
  'pgvector/pgvector:pg16',
  'netdata/netdata:stable',
  'postgres:16-alpine',
  'redis:7.4-alpine'
];

// Python requirements files to audit
const pythonRequirements = [
  'scripts/embeddings/requirements.txt',
  'frigate/control/requirements.txt',
  'stacks/web/thai-legal-inference/requirements.txt'
];

// Node.js directories to audit
const nodeDirectories = [
  '.',
  'scripts/embeddings',
  'scripts/gpu-queue',
  'scripts/weaviate'
];

/**
 * Scan Docker images for vulnerabilities using Trivy
 */
async function scanDockerImages() {
  console.log('Scanning Docker images for vulnerabilities...');
  
  for (const image of dockerImages) {
    try {
      console.log(`  Scanning ${image}...`);
      const result = execSync(
        `trivy image --severity HIGH,CRITICAL --format json --skip-version-check --scanners vuln ${image}`,
        { encoding: 'utf8', timeout: 120000 }
      );
      
      const vulnerabilities = JSON.parse(result);
      const vulnCount = vulnerabilities.Results?.[0]?.Vulnerabilities?.length || 0;
      
      securityResults.dockerImages.push({
        image,
        vulnerable: vulnCount > 0,
        vulnerabilityCount: vulnCount,
        vulnerabilities: vulnerabilities.Results?.[0]?.Vulnerabilities || []
      });
      
      console.log(`    Found ${vulnCount} HIGH/CRITICAL vulnerabilities`);
    } catch (error) {
      console.error(`    Failed to scan ${image}: ${error.message}`);
      securityResults.dockerImages.push({
        image,
        error: error.message,
        vulnerable: false,
        vulnerabilityCount: 0
      });
    }
  }
}

/**
 * Audit Python dependencies using pip-audit
 */
async function auditPythonDependencies() {
  console.log('Auditing Python dependencies...');
  
  for (const reqFile of pythonRequirements) {
    const fullPath = path.join(__dirname, '..', reqFile);
    
    if (!fs.existsSync(fullPath)) {
      console.log(`  Skipping ${reqFile} (not found)`);
      continue;
    }
    
    try {
      console.log(`  Auditing ${reqFile}...`);
      const result = execSync(
        `pip-audit -r ${fullPath} --format json`,
        { encoding: 'utf8', timeout: 60000 }
      );
      
      const auditResult = JSON.parse(result);
      const vulnCount = auditResult?.vulnerabilities?.length || 0;
      
      securityResults.pythonDependencies.push({
        file: reqFile,
        vulnerable: vulnCount > 0,
        vulnerabilityCount: vulnCount,
        vulnerabilities: auditResult?.vulnerabilities || []
      });
      
      console.log(`    Found ${vulnCount} vulnerabilities`);
    } catch (error) {
      // pip-audit returns non-zero exit code when vulnerabilities found
      const output = error.stdout || error.stderr || '';
      try {
        const auditResult = JSON.parse(output);
        const vulnCount = auditResult?.vulnerabilities?.length || 0;
        
        securityResults.pythonDependencies.push({
          file: reqFile,
          vulnerable: vulnCount > 0,
          vulnerabilityCount: vulnCount,
          vulnerabilities: auditResult?.vulnerabilities || []
        });
        
        console.log(`    Found ${vulnCount} vulnerabilities`);
      } catch (parseError) {
        console.error(`    Failed to audit ${reqFile}: ${error.message}`);
        securityResults.pythonDependencies.push({
          file: reqFile,
          error: error.message,
          vulnerable: false,
          vulnerabilityCount: 0
        });
      }
    }
  }
}

/**
 * Audit Node.js dependencies using npm audit
 */
async function auditNodeDependencies() {
  console.log('Auditing Node.js dependencies...');
  
  for (const dir of nodeDirectories) {
    const fullPath = path.join(__dirname, '..', dir);
    const packageJsonPath = path.join(fullPath, 'package.json');
    
    if (!fs.existsSync(packageJsonPath)) {
      console.log(`  Skipping ${dir} (no package.json)`);
      continue;
    }
    
    try {
      console.log(`  Auditing ${dir}...`);
      const result = execSync(
        `cd ${fullPath} && npm audit --json`,
        { encoding: 'utf8', timeout: 60000 }
      );
      
      const auditResult = JSON.parse(result);
      const vulnCount = Object.keys(auditResult?.vulnerabilities || {}).length;
      
      securityResults.nodeDependencies.push({
        directory: dir,
        vulnerable: vulnCount > 0,
        vulnerabilityCount: vulnCount,
        vulnerabilities: auditResult?.vulnerabilities || {}
      });
      
      console.log(`    Found ${vulnCount} vulnerabilities`);
    } catch (error) {
      // npm audit returns non-zero exit code when vulnerabilities found
      const output = error.stdout || error.stderr || '';
      try {
        const auditResult = JSON.parse(output);
        const vulnCount = Object.keys(auditResult?.vulnerabilities || {}).length;
        
        securityResults.nodeDependencies.push({
          directory: dir,
          vulnerable: vulnCount > 0,
          vulnerabilityCount: vulnCount,
          vulnerabilities: auditResult?.vulnerabilities || {}
        });
        
        console.log(`    Found ${vulnCount} vulnerabilities`);
      } catch (parseError) {
        console.error(`    Failed to audit ${dir}: ${error.message}`);
        securityResults.nodeDependencies.push({
          directory: dir,
          error: error.message,
          vulnerable: false,
          vulnerabilityCount: 0
        });
      }
    }
  }
}

/**
 * Check container image ages
 */
async function checkContainerImageAges() {
  console.log('Checking container image ages...');
  
  for (const image of dockerImages) {
    try {
      console.log(`  Checking age of ${image}...`);
      const result = execSync(
        `docker inspect ${image} --format='{{.Created}}'`,
        { encoding: 'utf8', timeout: 10000 }
      );
      
      const createdDate = new Date(result.trim());
      const ageInDays = (Date.now() - createdDate) / (1000 * 60 * 60 * 24);
      
      securityResults.containerAges.push({
        image,
        created: createdDate.toISOString(),
        ageInDays: Math.round(ageInDays),
        stale: ageInDays > 90
      });
      
      if (ageInDays > 90) {
        console.log(`    WARNING: Image is ${Math.round(ageInDays)} days old (stale)`);
      } else {
        console.log(`    Image is ${Math.round(ageInDays)} days old`);
      }
    } catch (error) {
      console.error(`    Failed to check age of ${image}: ${error.message}`);
      securityResults.containerAges.push({
        image,
        error: error.message,
        stale: false
      });
    }
  }
}

/**
 * Generate security summary
 */
function generateSecuritySummary() {
  const totalDockerVulns = securityResults.dockerImages.reduce((sum, img) => sum + (img.vulnerabilityCount || 0), 0);
  const totalPythonVulns = securityResults.pythonDependencies.reduce((sum, dep) => sum + (dep.vulnerabilityCount || 0), 0);
  const totalNodeVulns = securityResults.nodeDependencies.reduce((sum, dep) => sum + (dep.vulnerabilityCount || 0), 0);
  const staleImages = securityResults.containerAges.filter(img => img.stale).length;
  
  return {
    totalVulnerabilities: totalDockerVulns + totalPythonVulns + totalNodeVulns,
    dockerVulnerabilities: totalDockerVulns,
    pythonVulnerabilities: totalPythonVulns,
    nodeVulnerabilities: totalNodeVulns,
    staleContainerImages: staleImages,
    overallStatus: (totalDockerVulns + totalPythonVulns + totalNodeVulns) === 0 && staleImages === 0 ? 'secure' : 'needs-attention'
  };
}

/**
 * Main execution
 */
async function main() {
  console.log('Starting Security & Dependency Scan...');
  console.log('========================================');
  
  await scanDockerImages();
  await auditPythonDependencies();
  await auditNodeDependencies();
  await checkContainerImageAges();
  
  const summary = generateSecuritySummary();
  
  console.log('========================================');
  console.log('Security Scan Summary:');
  console.log(`  Total Vulnerabilities: ${summary.totalVulnerabilities}`);
  console.log(`  Docker: ${summary.dockerVulnerabilities}`);
  console.log(`  Python: ${summary.pythonVulnerabilities}`);
  console.log(`  Node.js: ${summary.nodeVulnerabilities}`);
  console.log(`  Stale Images: ${summary.staleContainerImages}`);
  console.log(`  Overall Status: ${summary.overallStatus}`);
  
  // Output full results
  console.log('\nFull results saved to security-results.json');
  fs.writeFileSync(
    path.join(__dirname, '..', 'security-results.json'),
    JSON.stringify({ ...securityResults, summary }, null, 2)
  );
  
  return { results: securityResults, summary };
}

// CLI interface
if (import.meta.url === `file://${process.argv[1]}`) {
  main().catch(error => {
    console.error('Security scan failed:', error);
    process.exit(1);
  });
}

export { main, securityResults };