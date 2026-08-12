#!/bin/bash
set -e

echo "🚀 Deploying MDDB Knowledge Base..."

# Variables
MDBB_DIR="/home/tony/CascadeProjects/chaba-kbman/stacks/web/mddb"
WEB_STACK_DIR="/home/tony/CascadeProjects/chaba-kbman/stacks/web"

# Step 1: Create directory structure
echo "📁 Creating directory structure..."
mkdir -p "$MDBB_DIR/vaults"
mkdir -p "$MDBB_DIR/config"
mkdir -p "$MDBB_DIR/logs"

# Step 2: Create .env file if not exists
if [ ! -f "$MDBB_DIR/.env" ]; then
    echo "🔐 Creating .env file..."
    cat > "$MDBB_DIR/.env" << EOF
MDDB_LOG_LEVEL=INFO
TZ=Asia/Bangkok
EOF
    echo "✅ .env file created"
else
    echo "✅ .env file already exists"
fi

# Step 3: Pull latest image
echo "📦 Pulling latest MDDB image..."
docker pull tradik/mddb:latest

# Step 4: Start container
echo "🐳 Starting MDDB container..."
cd "$MDBB_DIR"
docker compose up -d

# Step 5: Wait for container to be healthy
echo "⏳ Waiting for container to be healthy..."
sleep 15

# Step 6: Verify deployment
echo "🔍 Verifying deployment..."
if docker exec mddb curl -f http://localhost:11023/health > /dev/null 2>&1; then
    echo "✅ MDDB HTTP API is responding"
else
    echo "❌ MDDB HTTP API health check failed"
    docker logs mddb --tail 20
    exit 1
fi

# Step 7: Test gRPC endpoint
echo "🔍 Testing gRPC endpoint..."
if docker exec mddb curl -f http://localhost:11024 > /dev/null 2>&1; then
    echo "✅ MDDB gRPC API is responding"
else
    echo "⚠️  MDDB gRPC API health check failed (may be expected)"
fi

# Step 8: Display access information
echo ""
echo "🎉 Deployment successful!"
echo "📍 Access MDDB at:"
echo "   - HTTP API: http://localhost:11023"
echo "   - gRPC API: http://localhost:11024"
echo "   - MCP Server: http://localhost:9001"
echo "   - Web Interface: https://kb.tony-omen.local (after Caddy config)"
echo ""
echo "📋 Management commands:"
echo "   - View logs: docker logs -f mddb"
echo "   - Restart: docker compose restart"
echo "   - Stop: docker compose down"
echo "   - Update: docker compose pull && docker compose up -d"
echo ""
echo "📝 Next steps:"
echo "1. Update Caddy configuration with kb.tony-omen.local route"
echo "2. Configure MCP integration in ~/.config/devin/mcp_config.json"
echo "3. Test MCP tools availability (should show 77 tools)"
echo "4. Migrate existing KB content to MDDB vaults"
echo "5. Configure LLM integrations if needed"