---
category: operations
---

# Usage

### Development Workflow
1. Work in raceman worktree for docker service changes
2. Test changes locally with raceman containers (port 8083)
3. Commit to raceman branch
4. Push to origin/raceman
5. Static file changes go to chaba-h3 for Plesk deployment

### Testing
```bash
# Start containers
cd /home/tony/CascadeProjects/chaba-raceman
docker compose up -d

# Check container status
docker compose ps

# Test service
curl -s http://tony-omen.local:8083/apps/raceman/

# View logs
docker compose logs raceman-web
docker compose logs raceman-php
```

## Deployment

### Docker Services (chaba-raceman)
- **Local URL**: http://tony-omen.local:8083/apps/raceman/
- **Status**: Active and running
- **Management**: docker compose in chaba-raceman worktree

### Static Files (chaba-h3)
- **Production URL**: https://chaba.h3.gizmo-thailand.com/apps/raceman/
- **Status**: Deployed to Plesk shared hosting
- **Management**: Git push to chaba.h3 branch

## Troubleshooting

### Container Issues
If raceman containers have issues:
```bash
cd /home/tony/CascadeProjects/chaba-raceman
docker compose logs raceman-web
docker compose logs raceman-php
docker compose restart
```

### Service Not Responding
If port 8083 is not accessible:
1. Check if containers are running: `docker compose ps`
2. Check port mapping: `docker compose ps` should show 0.0.0.0:8083->80
3. Test locally: `curl -s http://localhost:8083/apps/raceman/`
4. Check hostname resolution: `ping tony-omen.local`

### Static File Changes
If static file changes aren't appearing:
1. Ensure changes are in chaba-h3/public/apps/raceman/
2. Commit and push to chaba.h3 branch
3. Plesk deployment is automatic via git push

