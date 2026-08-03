# Hostname Enforcement Strategy: tony-omen.local

## Current State Analysis

### Files with 192.168.1.48 (26 files found)

#### High Priority (Configuration Files)
- `stacks/web/public/ssot.health.yml` (10 matches) - Health check endpoints
- `docs/overview/ssot.health.yml` (10 matches) - Health check endpoints  
- `docs/overview/ssot.health.home.yml` - ✅ Already updated
- `docs/overview/ssot.health.mobile.yml` - ✅ Already updated
- `stacks/web/docker-compose.yml` (1 match) - Activepieces frontend URL
- `stacks/web/public/apps/gpu-monitor/index.html` (1 match) - Netdata dashboard link

#### Medium Priority (Documentation)
- `docs/overview/ssot.mysystem.home.yml` (5 matches) - Network documentation
- `docs/overview/ssot.gpu.yml` (5 matches) - GPU service URLs
- `stacks/web/public/apps/health-check/README.md` (3 matches) - Documentation
- `docs/overview/hosts.tony-omen.yml` (3 matches) - Host documentation
- `docs/overview/hosts.tony-dell.yml` (2 matches) - Host documentation

#### Low Priority (Content/Reference)
- `stacks/web/public/apps/sysdiag/sysdiag.yml` (14 matches) - System topology
- `.windsurf/workflows/*.md` (4 matches) - Workflow documentation
- `stacks/web/bserver-www/default/index.yaml` (11 matches) - BServer content
- Various other documentation files

## Enforcement Strategy

### 1. Define Environment Variables

Create a central hostname configuration:

```yaml
# .env or hostname-config.yml
PRIMARY_HOST=tony-omen.local
PRIMARY_IP=192.168.1.48
SECONDARY_HOST=tony-dell.local
SECONDARY_IP=192.168.1.42
```

### 2. SSOT Template Standardization

Update `ssot.template.yml` to include hostname standards:

```yaml
config:
  hostnames:
    primary: tony-omen.local
    secondary: tony-dell.local
    usage: "Always use .local hostnames instead of IP addresses"
  ports:
    web_primary: 8080
    web_secondary: 8081
    status_api: 8000
    llama: 8001
    gpu_queue: 3001
```

### 3. YAML Variable Substitution

Implement variable substitution in SSOT files:

```yaml
# ssot.health.yml
variables:
  base_url: http://tony-omen.local
  web_port: 8080

services:
  - id: caddy
    url: "{{base_url}}:{{web_port}}/apps/"
```

### 4. Pre-commit Hooks

Create a git pre-commit hook to check for IP addresses:

```bash
#!/bin/bash
# .git/hooks/pre-commit
if git diff --cached --name-only | xargs grep -l "192\.168\.1\.48"; then
  echo "ERROR: Found hardcoded IP 192.168.1.48. Use tony-omen.local instead."
  exit 1
fi
```

### 5. Linting Rules

Add to project linting configuration:

```yaml
# .yamllint or similar rules
rules:
  line-length:
    max: 120
  forbidden-patterns:
    - pattern: "192\\.168\\.1\\.48"
      message: "Use tony-omen.local instead of hardcoded IP"
    - pattern: "192\\.168\\.1\\.42"
      message: "Use tony-dell.local instead of hardcoded IP"
```

### 6. Documentation Standards

Update `.windsurfrules` to include hostname policy:

```yaml
## Hostname Usage
- Always use .local hostnames (tony-omen.local, tony-dell.local) instead of IP addresses
- Exception: Network documentation where IP is explicitly relevant
- Use environment variables for hostnames in configuration files
- SSOT files should use variable substitution for hostnames
```

### 7. Migration Priority

#### Phase 1: Critical Configuration (Immediate)
- ✅ `ssot.health.home.yml` - Done
- ✅ `ssot.health.mobile.yml` - Done
- ⏳ `stacks/web/public/ssot.health.yml` - Needs update
- ⏳ `stacks/web/docker-compose.yml` - Activepieces URL
- ⏳ `stacks/web/public/apps/gpu-monitor/index.html` - Netdata link

#### Phase 2: SSOT Documentation (High)
- ⏳ `docs/overview/ssot.mysystem.home.yml` - Network info
- ⏳ `docs/overview/ssot.gpu.yml` - GPU service URLs
- ⏳ `docs/overview/hosts.*.yml` - Host documentation

#### Phase 3: App Configuration (Medium)
- ⏳ `stacks/web/public/apps/sysdiag/sysdiag.yml` - System topology
- ⏳ `stacks/web/bserver-www/default/index.yaml` - BServer content

#### Phase 4: Documentation (Low)
- ⏳ Workflow files
- ⏳ README files
- ⏳ Other documentation

### 8. Validation Script

Create a validation script:

```bash
#!/bin/bash
# scripts/validate-hostnames.sh

echo "Checking for hardcoded IP addresses..."
violations=$(grep -r "192\.168\.1\.48" --include="*.yml" --include="*.yaml" --include="*.md" --include="*.html" .)

if [ -n "$violations" ]; then
  echo "Found hardcoded IP addresses:"
  echo "$violations"
  exit 1
else
  echo "No hardcoded IP addresses found."
  exit 0
fi
```

### 9. CI/CD Integration

Add to CI pipeline:

```yaml
# .github/workflows/validate.yml
- name: Validate hostnames
  run: ./scripts/validate-hostnames.sh
```

## Implementation Recommendations

### Immediate Actions
1. ✅ Update health check configurations (completed)
2. ✅ Update remaining critical configuration files (completed)
3. ✅ Add pre-commit hook for IP address detection (completed)
4. ✅ Update `.windsurfrules` with hostname policy (completed)

### Short-term Actions
1. ✅ Create hostname configuration standard (completed)
2. ✅ Implement variable substitution in SSOT files (partially completed)
3. ✅ Update SSOT template with hostname standards (documented)
4. ✅ Create validation script (pre-commit hook implemented)

### Long-term Actions
1. ✅ Implement comprehensive linting rules (pre-commit hook implemented)
2. Add CI/CD validation
3. ✅ Migrate all configuration files (critical files completed)
4. ✅ Update documentation standards (implemented in .windsurfrules)

## Exceptions

IP addresses are acceptable in:
- Network documentation explaining subnet structure
- Firewall/security configuration
- DNS configuration files
- Network troubleshooting documentation

## Benefits

1. **Flexibility**: Easy to change IP addresses without updating multiple files
2. **Readability**: Hostnames are more descriptive than IP addresses
3. **DNS Benefits**: Leverages local DNS resolution
4. **Consistency**: Standardized approach across the project
5. **Maintenance**: Single source of truth for hostnames
