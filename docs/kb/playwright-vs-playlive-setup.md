---
category: operations
---

# Installation and Setup

### Playwright Setup
```bash
# Install in project
npm install -D @playwright/test

# Install browsers
npx playwright install

# Run tests
npx playwright test
```

### PlayLive Setup
```bash
# Located in chaba-tony-dell project
cd /home/tony/CascadeProjects/chaba-tony-dell/mcp-servers/mcp-playlive

# Start daemon
node playlived.mjs

# Or use systemd service
sudo systemctl start playlived
```

