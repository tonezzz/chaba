# Jarvis Modularization Troubleshooting Guide

## 🔧 **Docker Build Issues**

### Problem: Container Fails to Start
**Symptoms:**
```
mcp-bundle-test-1  | exec /app/entrypoint.sh: no such file or directory
```

**Root Cause:** Shell script compatibility between Windows and Alpine Linux

**Solution:**
1. Fix shell script for Alpine Linux compatibility
2. Ensure proper line endings and executable permissions
3. Add proper PATH setup for Python venv

### Problem: Shell Script Execution Errors
**Symptoms:**
```
sh: ./entrypoint.sh: set: line 2: illegal option -
```

**Root Cause:** Windows-style line endings or shell compatibility issues

**Solution:**
1. Convert line endings from CRLF to LF
2. Ensure proper shebang line
3. Test shell script in Alpine environment

---

## 🚀 **Quick Fix Commands**

### Fix Shell Script
```bash
# Fix line endings and permissions
cd services/assistance/mcp-bundle
dos2unix entrypoint.sh
chmod +x entrypoint.sh

# Rebuild container
cd c:/chaba
docker-compose -f stacks/idc1-assistance-test/docker-compose.yml up -d --build
```

### Alternative: Use Direct Node.js Execution
```bash
# Run without entrypoint script
docker run --rm -it --name mcp-test \
  -p 127.0.0.1:3151:3050 \
  -v "$(pwd)/stacks/idc1-assistance-test/mcp-config/mcp.json:/app/mcp-config/mcp.json:ro" \
  -v "$(pwd)/mcp/mcp-news:/app/mcp-servers/mcp-news:ro" \
  -v mcp-news-data:/data/mcp-news \
  mcp-bundle-test:local \
  /bin/sh -c "cd /app && export PATH=/opt/venv/bin:$PATH && timeout 30 node /usr/src/app/index.js serve --transport http --host 0.0.0.0 --port 3050"
```

---

## 🔍 **Debugging Docker Containers**

### Check Container Logs
```bash
# Check container status
docker ps -a | grep mcp-test

# View container logs
docker logs mcp-test

# Inspect container filesystem
docker run --rm -it --name mcp-debug mcp-bundle-test:local /bin/sh -c "ls -la /app && cat /app/entrypoint.sh"
```

### Test Container Interactively
```bash
# Interactive shell for debugging
docker run --rm -it --name mcp-debug \
  -p 127.0.0.1:3151:3050 \
  -v "$(pwd)/stacks/idc1-assistance-test/mcp-config/mcp.json:/app/mcp-config/mcp.json:ro" \
  -v "$(pwd)/mcp/mcp-news:/app/mcp-servers/mcp-news:ro" \
  -v mcp-news-data:/data/mcp-news \
  mcp-bundle-test:local /bin/sh

# Inside container:
ls -la /app
cat /app/entrypoint.sh
export PATH=/opt/venv/bin:$PATH
timeout 30 node /usr/src/app/index.js serve --transport http --host 0.0.0.0 --port 3050
```

---

## 🔧 **Common Issues & Solutions**

### Volume Mount Issues
**Problem:** `no such file or directory` errors
**Solution:** Verify volume paths and permissions

```bash
# Check volume mounts
docker inspect mcp-bundle-test-1 | grep Mounts

# Verify source paths
ls -la "$(pwd)/mcp/mcp-news"
ls -la "$(pwd)/stacks/idc1-assistance-test/mcp-config/mcp.json"
```

### Network Issues
**Problem:** Connection refused or port conflicts
**Solution:** Check port availability and network configuration

```bash
# Check port usage
netstat -an | grep :3151

# Check Docker network
docker network ls
docker network inspect idc1-stack-net
```

### Configuration Issues
**Problem:** Missing mcp.json or configuration errors
**Solution:** Verify file paths and JSON syntax

```bash
# Check MCP configuration
docker run --rm-it --name mcp-config-test \
  -v "$(pwd)/stacks/idc1-assistance-test/mcp-config/mcp.json:/app/mcp-config/mcp.json:ro" \
  mcp-bundle-test:local /bin/sh -c "cat /app/mcp-config/mcp.json | head -20"
```

---

## 🚀 **Testing After Fix**

### Verify Container Start
```bash
# Check if container is running
docker ps | grep mcp-test

# Check logs for startup
docker logs mcp-test
```

### Test Endpoints
```bash
# Health check
curl http://127.0.0.1:3151/health

# List tools
curl -X POST http://127.0.0.1:3151/tools/list

# Test mcp-news
curl -X POST http://127.0.0.1:3151/tools/call \
  -H "Content-Type: application/json" \
  -d '{"name": "news_help", "arguments": {}}'
```

### Test Integration
```bash
# Test via WebSocket (once backend is deployed)
wscat -c ws://127.0.0.1:8000/ws/live?session_id=test
# Send: "current news"
```

---

## 📞 **When to Escalate**

### Contact Support If:
- Docker build continues to fail after fixes
- Container starts but mcp-news tools don't appear
- Integration tests fail despite container running
- Production deployment issues after test success

### Gather Debug Information:
```bash
# System information
docker version
docker-compose version
docker info

# Container details
docker inspect mcp-bundle-test:local
docker logs mcp-test

# Network diagnostics
docker network ls
docker ps -a
```

---

## 🎯 **Expected Timeline**

1. **Immediate** (5-10 min): Fix Docker build issues
2. **Short Term** (15-30 min): Deploy and test mcp-news integration
3. **Medium Term** (1-2 hours): Complete testing and validation
4. **Long Term** (1 week): Production deployment and monitoring

---

## 📚 **Success Indicators**

- ✅ Container starts without errors
- ✅ Health endpoint returns 200 OK
- ✅ mcp-news tools appear in tools list
- ✅ News skill integration works via WebSocket
- ✅ All modular components function correctly
- ✅ Error handling works as expected

---

## 🔗 **Rollback Plan**

If issues persist:

1. **Quick Rollback**: Use original main.py.backup
2. **Container Rollback**: Stop and remove test container
3. **Configuration Rollback**: Revert to original configuration
4. **Document Issues**: Add to troubleshooting guide

---

## 📞 **Related Documentation**

- [MODULARIZATION_STRATEGY.md](MODULARIZATION_STRATEGY.md)
- [MODULARIZATION_GUIDE.md](MODULARIZATION_GUIDE.md)
- [MODULARIZATION_STATUS.md](MODULARIZATION_STATUS.md)
- [DEBUG.md](../services/assistance/DEBUG.md)

---

## 🎯 **Contact Information**

For additional support:
- Check the troubleshooting guide first
- Gather debug information as shown above
- Provide specific error messages and logs
- Include system environment details

This troubleshooting guide will be updated as new issues are discovered and resolved.
