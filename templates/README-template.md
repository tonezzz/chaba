# {{STACK_NAME}} Stack ({{HOST}})

## Description
{{STACK_DESCRIPTION}}

## Services
{{#each services}}
- **{{name}}**: {{description}}
{{/each}}

## Quick Start
```bash
# Create environment file
cp .env.example .env

# Start stack
docker-compose up -d

# Check status
docker-compose ps
```

## Port Allocation
| Service | Port | Description |
|---------|------|-------------|
{{#each services}}
| {{name}} | {{port}} | {{description}} |
{{/each}}

## Environment Variables
{{#each env_vars}}
- `{{name}}`: {{description}} (default: {{default}})
{{/each}}

## Network Architecture
- External network: `{{STACK_NAME}}-{{HOST}}-net`
- Cross-stack communication: Use `service.{{target_stack}}-{{HOST}}-net:port`

## Troubleshooting
```bash
# View logs
docker-compose logs -f

# Health checks
docker ps --format "table {{.Names}}\t{{.Status}}"

# Restart services
docker-compose restart
```
