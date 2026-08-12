#!/bin/bash
set -e

echo "🔍 Verifying MDDB Deployment..."

# Check container status
echo "📊 Container status:"
docker ps | grep mddb || echo "❌ MDDB container not running"

# Check container health
echo "🏥 Container health:"
docker inspect --format='{{.State.Health.Status}}' mddb 2>/dev/null || echo "❌ Health check not available"

# Check volume mounts
echo "💾 Volume mounts:"
docker inspect --format='{{range .Mounts}}{{.Source}} -> {{.Destination}}{{"\n"}}{{end}}' mddb 2>/dev/null || echo "❌ Volume inspection failed"

# Check network connectivity
echo "🌐 Network connectivity:"
echo "HTTP API:"
docker exec mddb curl -f http://localhost:11023/health 2>/dev/null && echo "✅ HTTP API healthy" || echo "❌ HTTP API failed"
echo "gRPC API:"
docker exec mddb curl -f http://localhost:11024 2>/dev/null && echo "✅ gRPC API healthy" || echo "⚠️  gRPC API check failed"
echo "MCP Server:"
docker exec mddb curl -f http://localhost:9001 2>/dev/null && echo "✅ MCP Server healthy" || echo "⚠️  MCP Server check failed"

# Check logs for errors
echo "📋 Recent logs (last 20 lines):"
docker logs --tail 20 mddb

# Test MCP tools availability
echo "🔌 MCP Tools Test:"
echo "Testing MCP server connection..."
if docker exec mddb curl -f http://localhost:9000 2>/dev/null; then
    echo "✅ MCP Server is accessible"
    echo "📊 Expected: 77 MCP tools available"
else
    echo "⚠️  MCP Server not accessible via HTTP"
fi

# Check disk usage
echo "💿 Disk usage:"
docker exec mddb df -h /data 2>/dev/null || echo "❌ Disk usage check failed"

echo ""
echo "✅ Verification complete!"
echo ""
echo "🎯 Key Metrics:"
echo "   - Container Status: $(docker inspect --format='{{.State.Status}}' mddb 2>/dev/null || echo 'unknown')"
echo "   - Health Status: $(docker inspect --format='{{.State.Health.Status}}' mddb 2>/dev/null || echo 'unknown')"
echo "   - Uptime: $(docker inspect --format='{{.State.StartedAt}}' mddb 2>/dev/null || echo 'unknown')"