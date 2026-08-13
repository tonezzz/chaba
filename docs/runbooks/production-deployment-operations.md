# Production Deployment Operations Runbook

## Overview

This runbook provides procedures for deploying the Chaba infrastructure to production environments, including environment configuration, secrets management, and deployment workflows.

## Prerequisites

- Docker and Docker Compose installed
- Production server access
- SSL/TLS certificates (if using HTTPS)
- Real API keys for production services
- Backup strategy in place
- Monitoring and logging infrastructure

## Environment Configuration

### Development vs Production

**Development Mode:**
- `NODE_ENV=development` (default)
- Placeholder API keys acceptable
- Direct project directory mounts
- Verbose logging and error details
- Hot reload enabled
- Source maps enabled

**Production Mode:**
- `NODE_ENV=production` (required)
- Real API keys from secrets
- Only static asset mounts
- Structured logging
- Error handling with generic messages
- Source maps disabled
- Performance optimizations enabled

### Environment Files

**Development:** `.env`
```bash
NODE_ENV=development
GEMINI_API_KEY=placeholder
OPENAI_API_KEY=placeholder
```

**Production:** `.env.production`
```bash
NODE_ENV=production
GEMINI_API_KEY=your_real_gemini_key
OPENAI_API_KEY=your_real_openai_key
```

## Secrets Management

### Option 1: Environment Variables (Simple)

**Setup:**
```bash
# Copy production template
cp .env.example .env.production

# Edit with real values
nano .env.production
```

**Required Production Values:**
- `GEMINI_API_KEY` - Real Google Gemini API key
- `OPENAI_API_KEY` - Real OpenAI API key
- `AP_ENCRYPTION_KEY` - Strong encryption key
- `AP_JWT_SECRET` - Strong JWT secret
- Database passwords (use strong passwords)

### Option 2: Docker Secrets (Recommended)

**Generate Secrets:**
```bash
cd stacks/web
./scripts/generate-secrets.sh
```

**Update API Keys:**
```bash
nano secrets/gemini_api_key.txt
nano secrets/openai_api_key.txt
```

**Deploy with Secrets:**
```bash
docker compose -f docker-compose.yml -f docker-compose.prod.yml -f docker-compose.secrets.yml --profile production up -d
```

## Deployment Procedures

### Initial Production Deployment

**1. Prepare Environment:**
```bash
cd /home/tony/CascadeProjects/chaba/stacks/web

# Generate secrets
./scripts/generate-secrets.sh

# Update API keys
nano secrets/gemini_api_key.txt
nano secrets/openai_api_key.txt
```

**2. Configure Environment:**
```bash
# Copy production environment template
cp .env.example .env.production

# Update with production values
nano .env.production
```

**3. Deploy Services:**
```bash
# Build and start production services
docker compose -f docker-compose.yml -f docker-compose.prod.yml --profile production up -d --build

# Check service status
docker compose -f docker-compose.yml -f docker-compose.prod.yml --profile production ps
```

**4. Verify Deployment:**
```bash
# Check web server
curl http://localhost:8080/api/health

# Check database
docker compose exec postgres pg_isready

# Check Redis
docker compose exec redis redis-cli ping

# Check service logs
docker compose logs -f web
```

### Production Update Deployment

**1. Pull Latest Changes:**
```bash
cd /home/tony/CascadeProjects/chaba
git pull origin master
```

**2. Backup Current State:**
```bash
# Database backup
docker compose exec postgres pg_dump -U chaba chaba > backup_$(date +%Y%m%d).sql

# Backup configuration
cp stacks/web/.env.production stacks/web/.env.production.backup
```

**3. Deploy Update:**
```bash
cd stacks/web

# Rebuild and restart services
docker compose -f docker-compose.yml -f docker-compose.prod.yml --profile production up -d --build --force-recreate
```

**4. Verify Update:**
```bash
# Health checks
curl http://localhost:8080/api/health
curl http://localhost:8080/api/yomi/health

# Check logs for errors
docker compose logs --tail=50 web
docker compose logs --tail=50 helm
```

### Rollback Procedure

**1. Identify Previous Version:**
```bash
git log --oneline -10
```

**2. Checkout Previous Version:**
```bash
git checkout <previous_commit_hash>
```

**3. Redeploy:**
```bash
cd stacks/web
docker compose -f docker-compose.yml -f docker-compose.prod.yml --profile production up -d --build --force-recreate
```

**4. Restore Database (if needed):**
```bash
docker compose exec -T postgres psql -U chaba chaba < backup_YYYYMMDD.sql
```

## Service-Specific Production Notes

### Helm Service

**Development Configuration:**
```yaml
volumes:
  - /home/tony/CascadeProjects:/home/tony/CascadeProjects:ro
environment:
  - PROJECTS_PATH=/home/tony/CascadeProjects
```

**Production Configuration:**
```yaml
volumes:
  - ./public:/app/public:ro
environment:
  - NODE_ENV=production
  - PROJECTS_PATH=/app/projects
```

**Migration Steps:**
1. Build static assets locally
2. Copy to `./public` directory
3. Update `PROJECTS_PATH` to container path
4. Remove host directory mounts

### Yomi API

**Development Configuration:**
```yaml
volumes:
  - ../../scripts/yomi:/app/yomi
  - /home/tony/.yomi:/home/tony/.yomi:ro
```

**Production Configuration:**
```yaml
volumes:
  - ./public/apps/yomi/media:/app/media:ro
environment:
  - NODE_ENV=production
  - YOMI_MCP_PATH=/app/yomi/mcpb/run.mjs
```

**Migration Steps:**
1. Build Yomi application
2. Copy built files to container
3. Update MCP path to container location
4. Remove host directory mounts

### GPU Queue

**Development Configuration:**
```yaml
volumes:
  - ../../scripts/gpu-queue:/app/gpu-queue
```

**Production Configuration:**
```yaml
volumes:
  - gpu_queue_node_modules:/app/gpu-queue/node_modules
```

**Migration Steps:**
1. Build GPU queue application
2. Include in Docker image
3. Remove script directory mount
4. Use node_modules volume only

## Monitoring and Logging

### Production Monitoring

**Health Checks:**
```bash
# Web server health
curl http://localhost:8080/api/health

# Service-specific health
curl http://localhost:8080/api/yomi/health
curl http://localhost:8080/api/gpu-queue/health
```

**Container Monitoring:**
```bash
# Container status
docker compose ps

# Resource usage
docker stats

# Container logs
docker compose logs -f web
docker compose logs -f helm
docker compose logs -f yomi-api
```

### Log Aggregation

**Structured Logging:**
- Production logs should be structured JSON
- Include timestamps, service names, log levels
- Send to centralized logging system

**Log Rotation:**
```bash
# Configure log rotation in docker-compose
logging:
  driver: "json-file"
  options:
    max-size: "10m"
    max-file: "3"
```

## Security Considerations

### API Key Management

**Never commit secrets:**
```bash
# Add to .gitignore
.env.production
secrets/
*.key
*.pem
```

**Rotate secrets regularly:**
```bash
# Generate new secrets
./scripts/generate-secrets.sh

# Update services
docker compose -f docker-compose.yml -f docker-compose.prod.yml --profile production up -d --force-recreate
```

### Network Security

**Production Network:**
- Use private networks where possible
- Restrict external access to necessary ports only
- Implement firewall rules
- Use HTTPS with valid certificates

**Docker Security:**
```yaml
# Use read-only filesystems where possible
read_only: true

# Drop capabilities
cap_drop:
  - ALL
cap_add:
  - NET_BIND_SERVICE

# Run as non-root user
user: "1000:1000"
```

## Backup and Recovery

### Database Backups

**Automated Backups:**
```bash
# Add to cron
0 2 * * * cd /home/tony/CascadeProjects/chaba/stacks/web && docker compose exec postgres pg_dump -U chaba chaba > /backups/postgres_$(date +\%Y\%m\%d).sql
```

**Manual Backup:**
```bash
docker compose exec postgres pg_dump -U chaba chaba > backup.sql
```

**Restore Backup:**
```bash
docker compose exec -T postgres psql -U chaba chaba < backup.sql
```

### Volume Backups

**Backup Volumes:**
```bash
# List volumes
docker volume ls

# Backup specific volume
docker run --rm -v chaba_postgres_data:/data -v $(pwd):/backup alpine tar czf /backup/postgres_data.tar.gz /data
```

**Restore Volume:**
```bash
docker run --rm -v chaba_postgres_data:/data -v $(pwd):/backup alpine tar xzf /backup/postgres_data.tar.gz
```

## Troubleshooting

### Common Production Issues

**Service Won't Start:**
```bash
# Check logs
docker compose logs <service>

# Check configuration
docker compose config

# Check resource usage
docker stats
```

**Database Connection Issues:**
```bash
# Check database health
docker compose exec postgres pg_isready

# Check database logs
docker compose logs postgres

# Verify credentials
docker compose exec postgres psql -U chaba -d chaba -c "SELECT 1"
```

**API Key Errors:**
```bash
# Check environment variables
docker compose exec <service> env | grep API_KEY

# Verify secrets are mounted
docker compose exec <service> ls -la /run/secrets/
```

**Performance Issues:**
```bash
# Check resource usage
docker stats

# Check database performance
docker compose exec postgres psql -U chaba -d chaba -c "SELECT * FROM pg_stat_activity"

# Check cache performance
docker compose exec redis redis-cli INFO stats
```

## Performance Optimization

### Production Optimizations

**Database Optimization:**
- Enable connection pooling
- Configure appropriate memory settings
- Add indexes for slow queries
- Regular vacuum and analyze

**Caching Strategy:**
- Configure Redis for session storage
- Enable CDN for static assets
- Implement application-level caching
- Use HTTP caching headers

**Resource Limits:**
```yaml
deploy:
  resources:
    limits:
      cpus: '2'
      memory: 2G
    reservations:
      cpus: '1'
      memory: 1G
```

## Maintenance Procedures

### Regular Maintenance

**Daily:**
- Check service health
- Review error logs
- Monitor resource usage
- Verify backups completed

**Weekly:**
- Review performance metrics
- Check for security updates
- Clean up old logs
- Verify backup integrity

**Monthly:**
- Update dependencies
- Review and rotate secrets
- Performance tuning
- Capacity planning

### Update Procedures

**Security Updates:**
```bash
# Update base images
docker compose pull

# Rebuild services
docker compose -f docker-compose.yml -f docker-compose.prod.yml --profile production up -d --build
```

**Application Updates:**
```bash
# Pull latest code
git pull origin master

# Test in staging first
# Then deploy to production
docker compose -f docker-compose.yml -f docker-compose.prod.yml --profile production up -d --build
```

## Disaster Recovery

### Recovery Procedures

**Complete System Recovery:**
1. Restore from backup
2. Verify database integrity
3. Start services
4. Run health checks
5. Monitor for issues

**Partial Recovery:**
1. Identify affected services
2. Restore specific components
3. Verify functionality
4. Update monitoring

**Data Recovery:**
1. Restore database from backup
2. Verify data integrity
3. Update application if needed
4. Test functionality

## References

- Docker Compose Documentation: https://docs.docker.com/compose/
- Docker Secrets: https://docs.docker.com/engine/swarm/secrets/
- PostgreSQL Performance: https://www.postgresql.org/docs/current/performance-tips.html
- Redis Best Practices: https://redis.io/docs/manual/patterns/
- Next.js Production: https://nextjs.org/docs/deployment

## Change Log

- **2026-08-13**: Initial production deployment runbook created
- **2026-08-13**: Added secrets management with Docker secrets
- **2026-08-13**: Added production-specific service configurations
- **2026-08-13**: Added monitoring and troubleshooting procedures
