#!/bin/bash
# Deploy Skill Creator UI to idc1.surf-thailand.com
# Run this on the idc1 host

set -e

echo "========================================"
echo "🚀 Deploying Skill Creator to idc1"
echo "========================================"
echo ""

# Configuration
SKILL_CREATOR_PORT=8090
CADDYFILE="/etc/caddy/Caddyfile"
DOMAIN="assistance.idc1.surf-thailand.com"

echo "1. Checking if Skill Creator is running on port $SKILL_CREATOR_PORT..."
if lsof -Pi :$SKILL_CREATOR_PORT -sTCP:LISTEN -t >/dev/null 2>&1; then
    echo "   ✅ Skill Creator is running on port $SKILL_CREATOR_PORT"
else
    echo "   ⚠️  Skill Creator not running on port $SKILL_CREATOR_PORT"
    echo "   Starting server..."
    cd /home/chaba/chaba/services/autoagent/control-panel
    WIKI_API_URL=http://localhost:3008 nohup /home/chaba/chaba/.venv/bin/python control-server.py --port $SKILL_CREATOR_PORT > /tmp/skill-creator.log 2>&1 &
    sleep 3
    if lsof -Pi :$SKILL_CREATOR_PORT -sTCP:LISTEN -t >/dev/null 2>&1; then
        echo "   ✅ Server started successfully"
    else
        echo "   ❌ Failed to start server"
        exit 1
    fi
fi
echo ""

echo "2. Backing up Caddyfile..."
cp $CADDYFILE ${CADDYFILE}.backup.$(date +%Y%m%d-%H%M%S)
echo "   ✅ Backup created"
echo ""

echo "3. Adding Skill Creator route to Caddyfile..."

# Check if skills route already exists
if grep -q "/skills" $CADDYFILE; then
    echo "   ⚠️  Skills route already exists in Caddyfile"
else
    # Add the skills route to the assistance block
    cat >> $CADDYFILE << 'EOF'

# Skill Creator UI
handle_path /skills/* {
    reverse_proxy 127.0.0.1:8090
}

# Skill Creator root redirect
handle /skills {
    redir /skills/ 308
}
EOF
    echo "   ✅ Skills route added"
fi
echo ""

echo "4. Validating Caddyfile..."
if caddy validate --config $CADDYFILE 2>&1; then
    echo "   ✅ Caddyfile is valid"
else
    echo "   ❌ Caddyfile validation failed"
    exit 1
fi
echo ""

echo "5. Reloading Caddy..."
systemctl reload caddy
if [ $? -eq 0 ]; then
    echo "   ✅ Caddy reloaded successfully"
else
    echo "   ❌ Failed to reload Caddy"
    exit 1
fi
echo ""

echo "========================================"
echo "✅ Deployment Complete!"
echo "========================================"
echo ""
echo "Skill Creator is now available at:"
echo "   https://$DOMAIN/skills"
echo ""
echo "Test URL:"
echo "   curl https://$DOMAIN/skills | head -20"
echo ""
echo "To check logs:"
echo "   journalctl -u caddy -n 50 --no-pager"
echo "   tail -f /tmp/skill-creator.log"
