---
category: operations
---

# Troubleshooting

### Ollama Container Issues
**Symptoms**: Container not starting, GPU not accessible
**Solutions**:
- Check GPU availability: `nvidia-smi`
- Verify Docker GPU support: `docker run --rm --gpus all nvidia/cuda:11.0.3-base-ubuntu20.04 nvidia-smi`
- Check container logs: `docker logs ollama`

### Model Download Issues
**Symptoms**: Model pull fails, slow download
**Solutions**:
- Check network connectivity
- Verify disk space availability
- Retry model pull: `docker exec ollama ollama pull nomic-embed-text`

### MDDB Integration Issues
**Symptoms**: Vector search not working, embedding errors
**Solutions**:
- Verify MDDB environment variables
- Check Ollama connectivity from MDDB container
- Test embedding generation directly
- Review MDDB logs for errors

### GPU Resource Issues
**Symptoms**: Out of memory errors, slow performance
**Solutions**:
- Monitor GPU usage: `nvidia-smi`
- Check for conflicting GPU processes
- Consider smaller model if needed
- Optimize batch sizes for embedding generation

## Maintenance

### Model Updates
```bash
# Update model
docker exec ollama ollama pull nomic-embed-text

# Check for newer versions
docker exec ollama ollama list
```

### Container Maintenance
```bash
# Restart container
docker restart ollama

# View logs
docker logs ollama --tail 50

# Check resource usage
docker stats ollama
```

### Index Maintenance
```bash
# Reindex specific collection
curl -X POST http://tony-omen.local:11023/v1/vector-reindex \
  -H "Content-Type: application/json" \
  -d '{"collection":"kb-system","force":true}'

# Check vector stats
curl http://tony-omen.local:11023/v1/vector-stats
```

