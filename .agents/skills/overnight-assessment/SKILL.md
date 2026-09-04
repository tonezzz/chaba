# Overnight System Assessment

Comprehensive overnight assessment leveraging existing Chaba monitoring infrastructure.

## Assessment Areas

### 1. Health Check Integration
- Call existing health check API: http://tony-omen.local:8080/api/health
- Parse SSOT configuration from /ssot.health.home.yml
- Check all service categories: web, api, datastore, gpu, queue, optional
- Identify failed services and suggest recovery actions

### 2. GPU & Queue Analysis  
- Call GPU status API: http://tony-omen.local:8080/api/gpu/status
- Call GPU queue API: http://tony-omen.local:3001/api/gpu-queue/status
- Analyze GPU utilization, memory, temperature trends
- Check for stuck jobs, failure patterns, queue backlog
- Review GPU service health (Thai Legal, Imagen2, Txt2Vid)

### 3. Yomi System Health
- Call Yomi health: http://tony-omen.local:8080/api/yomi/health
- Call rate limiter status: http://tony-omen.local:8080/api/yomi/rate-limiter-status
- Call summarization status: http://tony-omen.local:8080/api/yomi/summarization-status
- Analyze circuit breaker states and failure patterns
- Review rate limiter performance and queue times

### 4. Database & Cache Performance
- Check Postgres container status via Docker
- Test Weaviate API: http://tony-omen.local:8080/api/weaviate/v1/nodes
- Check Redis container status
- Analyze connection pool performance if metrics available

### 5. Application Log Analysis
- Check Docker logs for errors in key services
- Look for recurring error patterns
- Identify services with high error rates
- Check for resource exhaustion warnings

### 6. Configuration Validation
- Run ssot-validate skill on all SSOT YAML files
- Check for configuration drift between environments
- Validate hostname usage (.local vs IP addresses)
- Check for deprecated or inconsistent configurations

### 7. Security & Dependency Check
- Check for security vulnerabilities in dependencies
- Review container image ages and updates
- Check for exposed or unsecured endpoints
- Validate SSL/TLS configurations

### 8. Performance Trend Analysis
- Compare current metrics against historical baselines
- Identify performance degradation trends
- Check resource utilization patterns
- Analyze response time trends

## Output Format

Generate comprehensive markdown report with:
- Executive summary with health score
- Service status summary table
- Critical issues requiring immediate attention
- Performance analysis with trends
- Security findings
- Configuration validation results
- Prioritized improvement recommendations
- Historical comparison if data available

Save to: /home/tony/CascadeProjects/chaba-tony-dell/reports/overnight-assessment-YYYY-MM-DD.md