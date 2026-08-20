---
category: operations
---

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
