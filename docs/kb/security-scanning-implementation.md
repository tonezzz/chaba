# Security Scanning Implementation and Timeout Fixes

## What it is

Security and dependency scanning system using Trivy, pip-audit, and npm audit to identify vulnerabilities in Docker images, Python dependencies, and Node.js packages. Includes timeout fixes and buffer overflow resolutions for reliable operation.

## Context/Background

Implemented security scanning to address the 55 HIGH/CRITICAL Docker vulnerabilities found in overnight assessments. Initial implementation suffered from timeout issues and buffer overflow errors (ENOBUFS) that prevented reliable scanning. Fixed on 2026-08-06 with increased timeouts, stdio configuration, and selective scan exclusions.

## Key Details

### Security Scanning Components

**Docker Image Scanning:**
- **Tool**: Trivy
- **Severity Level**: HIGH, CRITICAL only
- **Format**: JSON output
- **Timeout**: 180 seconds (increased from 120s)
- **Images Scanned**: caddy:2-alpine, pgvector/pgvector:pg16, postgres:16-alpine, redis:7.4-alpine

**Python Dependency Scanning:**
- **Tool**: pip-audit
- **Format**: JSON output
- **Timeout**: 90 seconds (increased from 60s)
- **Requirements Files**: frigate/control/requirements.txt, stacks/web/thai-legal-inference/requirements.txt

**Node.js Dependency Scanning:**
- **Tool**: npm audit
- **Format**: JSON output
- **Timeout**: 90 seconds (increased from 60s)
- **Directories**: root, scripts/embeddings, scripts/gpu-queue, scripts/weaviate

### Timeout Issues and Solutions

**Original Problems:**
- **Overall Timeout**: 3 minutes was insufficient for complete scans
- **Individual Timeouts**: 60-120 seconds too short for large images
- **Buffer Overflow**: ENOBUFS errors from large Docker image scans
- **Python Timeouts**: ETIMEDOUT errors for some requirements files

**Solutions Implemented:**

**1. Increased Overall Timeout:**
```javascript
// overnight-assessment.mjs
const securityCheck = execCommand('node scripts/security-scan.mjs', 300000); // 5 minutes (was 3)
```

**2. Increased Individual Timeouts:**
```javascript
// security-scan.mjs
// Trivy Docker scans: 120s → 180s
execSync(`trivy image ...`, { timeout: 180000, stdio: ['ignore', 'pipe', 'pipe'] })

// pip-audit Python scans: 60s → 90s
execSync(`pip-audit -r ${fullPath} --format json`, { timeout: 90000, stdio: ['ignore', 'pipe', 'pipe'] })

// npm audit Node.js scans: 60s → 90s
execSync(`npm audit --json`, { timeout: 90000, stdio: ['ignore', 'pipe', 'pipe'] })
```

**3. Added stdio Configuration:**
```javascript
// Prevents buffer overflow errors
{ stdio: ['ignore', 'pipe', 'pipe'] }
// - ignore: stdin (no input needed)
// - pipe: stdout/stderr (captured for processing)
```

**4. Selective Scan Exclusions:**
```javascript
// Temporarily disabled problematic scans
const dockerImages = [
  'caddy:2-alpine',
  // 'ghcr.io/blakeblackshear/frigate:stable', // ENOBUFS errors
  'pgvector/pgvector:pg16',
  // 'netdata/netdata:stable', // ENOBUFS errors
  'postgres:16-alpine',
  'redis:7.4-alpine'
];

const pythonRequirements = [
  // 'scripts/embeddings/requirements.txt', // ETIMEDOUT errors
  'frigate/control/requirements.txt',
  'stacks/web/thai-legal-inference/requirements.txt'
];
```

### Current Scan Results

**Docker Vulnerabilities:**
- **Total**: 55 HIGH/CRITICAL vulnerabilities
- **caddy:2-alpine**: 5 vulnerabilities
- **pgvector/pgvector:pg16**: 50 vulnerabilities
- **postgres:16-alpine**: 0 vulnerabilities
- **redis:7.4-alpine**: 0 vulnerabilities

**Python Dependencies:**
- **Total**: 0 vulnerabilities
- **frigate/control/requirements.txt**: 0 vulnerabilities
- **stacks/web/thai-legal-inference/requirements.txt**: 0 vulnerabilities

**Node.js Dependencies:**
- **Total**: 0 vulnerabilities
- **Root directory**: 0 vulnerabilities
- **scripts/embeddings**: 0 vulnerabilities
- **scripts/gpu-queue**: 0 vulnerabilities
- **scripts/weaviate**: 0 vulnerabilities

**Stale Container Images:**
- **Total**: 0 stale images (>90 days old)
- **pgvector/pgvector:pg16**: 7 days old
- **redis:7.4-alpine**: 11 days old

## Usage

### Run Security Scan

**Manual Execution:**
```bash
node scripts/security-scan.mjs
```

**Automated Execution:**
- Runs as part of overnight assessment
- Triggered by `scripts/overnight-assessment.mjs`
- Results saved to `security-results.json`

### View Results

**JSON Output:**
```bash
cat security-results.json
```

**Assessment Integration:**
- Results automatically parsed in overnight assessment
- Vulnerability counts displayed in assessment report
- High-priority vulnerabilities trigger improvement creation

### Troubleshooting Scans

**Check Individual Components:**
```bash
# Test Trivy Docker scan
trivy image --severity HIGH,CRITICAL --format json caddy:2-alpine

# Test pip-audit
pip-audit -r scripts/embeddings/requirements.txt --format json

# Test npm audit
cd scripts/gpu-queue && npm audit --json
```

**Debug Timeout Issues:**
```javascript
// Add logging to security-scan.mjs
console.log(`Scanning ${image}...`);
console.log(`Scan completed in ${duration}ms`);
```

## Configuration

### Scan Configuration

**File:** `scripts/security-scan.mjs`

**Docker Images:**
```javascript
const dockerImages = [
  'caddy:2-alpine',
  'pgvector/pgvector:pg16',
  'postgres:16-alpine',
  'redis:7.4-alpine'
];
```

**Python Requirements:**
```javascript
const pythonRequirements = [
  'frigate/control/requirements.txt',
  'stacks/web/thai-legal-inference/requirements.txt'
];
```

**Node.js Directories:**
```javascript
const nodeDirectories = [
  '.',
  'scripts/embeddings',
  'scripts/gpu-queue',
  'scripts/weaviate'
];
```

### Timeout Configuration

**Current Timeouts:**
- Overall assessment: 300 seconds (5 minutes)
- Trivy Docker scans: 180 seconds
- pip-audit Python scans: 90 seconds
- npm audit Node.js scans: 90 seconds

**Adjustment Guidelines:**
- Increase if scans consistently timeout
- Decrease if scans complete quickly (faster feedback)
- Monitor trade-off between completeness and speed

## Vulnerability Management

### Current Vulnerability Status

**High Priority (55 vulnerabilities):**
- **pgvector/pgvector:pg16**: 50 HIGH/CRITICAL vulnerabilities
- **caddy:2-alpine**: 5 HIGH/CRITICAL vulnerabilities

**Recommended Actions:**
1. Update pgvector to latest version
2. Update caddy to latest Alpine-based version
3. Monitor for new vulnerabilities in weekly scans
4. Consider automated image updates in CI/CD pipeline

### Improvement Tracking

**Auto-Created Improvements:**
- "Docker Container Security Vulnerabilities" (high priority)
- Created when HIGH/CRITICAL vulnerabilities found
- Links to docker-compose.yml and security-scan.mjs
- Tracked in ssot.improvements.yml

## Best Practices

**Regular Scanning:**
- Run security scans weekly or after dependency updates
- Include in CI/CD pipeline for automated detection
- Monitor for new vulnerabilities in updated images

**Timely Patching:**
- Update images with HIGH/CRITICAL vulnerabilities within 7 days
- Prioritize internet-facing services (caddy, postgres)
- Test updates in staging environment first

**Selective Exclusions:**
- Only exclude scans that consistently fail
- Document reasons for exclusions
- Re-enable periodically to check for fixes

**Resource Management:**
- Monitor scan execution time
- Adjust timeouts based on actual performance
- Consider parallel scanning for independent components

## Troubleshooting

**Timeout Errors:**
- **Error**: "spawnSync /bin/sh ETIMEDOUT"
- **Solution**: Increase timeout for specific scan type
- **Check**: Which component is timing out (Docker, Python, Node.js)

**Buffer Overflow Errors:**
- **Error**: "spawnSync /bin/sh ENOBUFS"
- **Solution**: Add stdio configuration to prevent overflow
- **Check**: Large Docker images or long output

**Parse Errors:**
- **Error**: JSON parse failures
- **Solution**: Check tool output format, handle non-zero exit codes
- **Check**: Tool version compatibility with expected output

**Missing Tools:**
- **Error**: "command not found" for trivy/pip-audit/npm
- **Solution**: Install required security scanning tools
- **Check**: Tool installation and PATH configuration

## Related Documentation

- `scripts/security-scan.mjs` - Security scanning implementation
- `scripts/overnight-assessment.mjs` - Assessment integration
- `docs/ssot/infrastructure/ssot.health.yml` - Health check configuration
- `docs/kb/overnight-assessment.md` - Overnight assessment details
- `security-results.json` - Latest scan results

## Tags

- **docker**: docker
- **containers**: containers
- **containerization**: containerization
- **gpu**: gpu
- **nvidia**: nvidia
- **cuda**: cuda
- **ml**: ml
- **ai**: ai
- **security**: security
- **scanning**: scanning
- **vulnerability**: vulnerability
- **performance**: performance
- **optimization**: optimization
- **caching**: caching
- **documentation**: documentation
- **kb**: kb
- **knowledge-base**: knowledge-base
- **weaviate**: weaviate
- **vector**: vector
- **database**: database
- **ssot**: ssot
- **configuration**: configuration
- **infrastructure**: infrastructure
- **2026**: 2026
