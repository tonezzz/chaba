---
category: operations
---

# Container Management

## What it is

Container orchestration and management for Chaba infrastructure using Docker containers for service deployment, GPU workloads, and application isolation.

## Context/Background

Chaba infrastructure uses Docker containers extensively for service deployment and isolation. Container management includes deployment, health monitoring, resource allocation, and cleanup operations. Created 2026-08-10 to document container patterns and best practices.

## Key Details

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

# Pull image with optimized mirrors
podman pull docker.io/library/nginx:latest

# Run container with GPU support
podman run --device nvidia.com/gpu=all nvidia/cuda:12.1.0-runtime-ubuntu22.04 nvidia-smi

# Check security policy
cat /etc/containers/policy.json

# View registry configuration
cat /etc/containers/registries.conf
```

### GPU Container Operations
```bash
# Check GPU access in container
docker exec <gpu-container> nvidia-smi

# Run GPU container
docker run --gpus all nvidia/cuda:12.1.0-runtime-ubuntu22.04 nvidia-smi

# Monitor GPU usage in containers
nvidia-smi --query-gpu=index,name,utilization.gpu,memory.used,memory.total --format=csv
```

### Health Monitoring
```bash
# Check container health status
docker ps --format "{{.Names}}: {{.Status}}"

# Find unhealthy containers
docker ps --filter "health=unhealthy"

# View container health logs
docker inspect --format='{{json .State.Health}}' <container-name>
```

## Troubleshooting

### Container Won't Start
- Check logs: `docker logs <container-name>`
- Verify image exists: `docker images | grep <image-name>`
- Check resource availability: `docker system df`
- Verify GPU access for GPU containers: `nvidia-smi`

### GPU Container Issues
- Verify NVIDIA Container Toolkit: `docker run --rm --gpus all nvidia/cuda:12.1.0-base-ubuntu22.04 nvidia-smi`
- Check GPU driver: `nvidia-smi` on host
- Verify container runtime: `docker info | grep -i runtime`
- Check GPU availability: `nvidia-smi --query-gpu=index,name --format=csv`

### Container Network Issues
- Check network: `docker network ls`
- Inspect network: `docker network inspect <network-name>`
- Test connectivity: `docker exec <container> ping <other-container>`
- Check DNS: `docker exec <container> nslookup <hostname>`

### Storage Issues
- Check volumes: `docker volume ls`
- Inspect volume: `docker volume inspect <volume-name>`
- Clean up unused volumes: `docker volume prune`
- Check disk space: `docker system df`

### Resource Exhaustion
- Check container stats: `docker stats`
- Monitor disk usage: `docker system df`
- Clean up resources: `docker system prune -a -f --volumes`
- Check system resources: `df -h`, `free -h`

## Related Documentation

- **[health-check.md](health-check.md)** - Health check system with container monitoring
- **[gpu-embedding-service.md](gpu-embedding-service.md)** - GPU container configuration
- **[system-automation.md](system-automation.md)** - Automated container cleanup
- **[workflows-mcp-integration.md](workflows-mcp-integration.md)** - Container management workflows

## Tags

- **docker**: Container runtime and management
- **containers**: Container orchestration and deployment
- **gpu**: GPU container configuration
- **monitoring**: Container health monitoring
- **cleanup**: Container resource management