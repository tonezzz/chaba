---
category: operations
---

# Setup Instructions

1. **Make scripts executable:**
```bash
chmod +x scripts/*.mjs scripts/*.sh
```

2. **Set up automation:**
```bash
bash scripts/setup-automation.sh
```

3. **Verify installation:**
```bash
# Test GPU monitoring
node scripts/gpu-monitor.mjs

# Test system maintenance
node scripts/system-maintenance.mjs

# View dashboard
node scripts/monitoring-dashboard.mjs
```

