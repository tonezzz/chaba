---
category: operations
---

# Troubleshooting

### Service Not Starting
- Check port 5000 is not in use: `lsof -i :5000`
- Verify Python virtual environment is intact
- Check CUDA is available: `nvidia-smi`
- Review service logs for errors

### Performance Issues
- Check GPU memory usage: `nvidia-smi`
- Verify CUDA device is available
- Check for other GPU processes consuming resources
- Review batch size configuration

### Integration Issues
- Verify Weaviate embeddings module configuration
- Check GPU queue database schema is updated
- Test service health endpoint independently
- Review orchestrator logs for errors

