---
category: operations
---

# Key Details

### Technical Details
- **Container Runtime**: Docker (primary), Podman (installed and configured)
- **Orchestration**: Docker Compose for multi-container stacks
- **GPU Support**: NVIDIA Container Toolkit for GPU workloads
- **Network**: Custom Docker networks for service isolation
- **Storage**: Docker volumes for persistent data
- **Podman Configuration**: Optimized runtime with crun, security policies, and registry mirrors

### Podman Configuration
- **Runtime**: crun (optimized for performance)
- **Security Policy**: signedBy instead of insecureAcceptAnything
- **Registry Mirrors**: GCR, USTC for faster image pulls
- **Pull Policy**: missing pull policy for optimization
- **Downloads**: Parallel downloads enabled
- **Configuration Files**: `/etc/containers/policy.json`, `/etc/containers/registries.conf`

### Container Categories
- **Web Services**: Caddy, web stack, status API
- **Data Services**: PostgreSQL, Redis, Weaviate
- **AI/ML Services**: GPU embedding service, Thai legal inference
- **Monitoring**: Health check services, GPU monitoring
- **Integration**: Yomi MCP server, workflow automation

### GPU Container Configuration
```yaml
# GPU container example
services:
  gpu-service:
    image: nvidia/cuda:12.1.0-runtime-ubuntu22.04
    deploy:
      resources:
        reservations:
          devices:
            - driver: nvidia
              count: 1
              capabilities: [gpu]
```

## Usage/Commands

### Container Management
```bash
# List running containers
docker ps

# List all containers (including stopped)
docker ps -a

# View container logs
docker logs <container-name>

# Execute command in container
docker exec -it <container-name> /bin/bash

# Stop container
docker stop <container-name>

# Start container
docker start <container-name>

# Restart container
docker restart <container-name>
```

### System Cleanup
```bash
# Remove stopped containers
docker container prune

# Remove unused images
docker image prune -a

# Remove unused volumes
docker volume prune

# Full system cleanup (including build cache)
docker system prune -a -f --volumes
```

### Podman Operations
```bash
# Check Podman version
podman version

# List containers
podman ps

