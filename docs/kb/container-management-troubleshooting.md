---
category: operations
---

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

