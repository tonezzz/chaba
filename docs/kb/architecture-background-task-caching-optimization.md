---
category: operations
---

# Performance Optimization

### Tuning Guidelines
- **High-frequency changes**: Reduce intervals (30s file index)
- **Low-frequency changes**: Increase intervals (10min search index)
- **Memory constraints**: Reduce cache size and TTL
- **CPU constraints**: Increase intervals and reduce concurrent tasks

### Monitoring
- **Task execution time**: Track in task results
- **Cache hit rates**: Monitor cache statistics
- **Memory usage**: Monitor cache size
- **Error rates**: Track task error counts

### Best Practices
- **Start conservative**: Longer intervals, smaller caches
- **Monitor performance**: Adjust based on actual usage
- **Cache hot data**: Focus on frequently accessed data
- **Clean up regularly**: Automatic cache cleanup prevents bloat

