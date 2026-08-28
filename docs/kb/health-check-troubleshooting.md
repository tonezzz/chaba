---
category: operations
---

# Troubleshooting

### GPU tab shows "GPU Error"
- Check status-api container is running: `docker ps | grep status-api`
- Verify GPU endpoint works: `curl http://localhost:8080/api/gpu/status`
- Check thai-legal-inference container has GPU access and nvidia-smi
- Review status-api logs: `docker logs status-api`

### Location detection stuck on "Detecting..."
- Check if hostname resolution works for tony-dell.local and tony-omen.local
- Verify network connectivity from browser to local endpoints
- Try manual location selection from dropdown

### Services show "unknown" status
- Check SSOT config files are accessible via Caddy
- Verify service endpoints are reachable from the web container
- Review browser console for CORS or network errors

### Auto-refresh not working
- Check "Auto-refresh (30s)" checkbox is enabled
- Verify browser allows JavaScript execution
- Check for JavaScript errors in browser console

