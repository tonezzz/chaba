---
category: operations
---

# Part 1: Headroom Proxy Integration ✅

### Configuration Scripts Created

1. **Configuration Script**: `.windsurf/configure-devin-headroom.sh`
   - Provides 3 methods for Devin Desktop integration
   - Includes verification procedures
   - Documents environment variable setup

2. **Status Check Script**: `.windsurf/check-headroom-stats.sh`
   - Real-time monitoring of Headroom proxy performance
   - Displays compression ratios and cost savings
   - Shows detailed statistics and health status

### Integration Methods

**Method 1: Environment Variable (Recommended)**
```bash
export ANTHROPIC_BASE_URL=http://127.0.0.1:8787
```
Add to `~/.bashrc` or `~/.zshrc` for persistence.

**Method 2: Devin Desktop Settings**
- Configure custom API endpoint in Devin Desktop settings
- Set Base URL to: `http://127.0.0.1:8787`

**Method 3: Session-Specific**
```bash
ANTHROPIC_BASE_URL=http://127.0.0.1:8787 devin-desktop
```

### Current Status
- ✅ Headroom proxy running on port 8787
- ✅ Health check: All systems healthy
- ✅ Uptime: ~15 minutes (since start)
- ✅ Configuration scripts operational
- ⏳ Awaiting Devin Desktop integration by user

## Part 2: Monitoring Procedures ✅

### Monitoring Scripts Created

1. **Comprehensive Monitoring**: `.windsurf/monitor-token-usage.sh`
   - Complete overview of optimization infrastructure
   - MCP filtering effectiveness
   - Headroom performance metrics
   - Summary and recommendations

2. **Monitoring Guide**: `docs/kb/token-optimization-monitoring-guide.md`
   - Detailed monitoring procedures
   - Performance benchmarks
   - Troubleshooting procedures
   - Reporting templates

### Monitoring Schedule

**Daily**:
- Check Headroom proxy status
- Verify no errors in logs
- Quick stats check

**Weekly**:
- Run comprehensive monitoring script
- Verify MCP tool counts
- Check MCP server health
- Review token usage trends

**Monthly**:
- Detailed performance analysis
- Cost savings calculation
- Review filter effectiveness
- Check for software updates

### Current Monitoring Results

**Headroom Proxy Status**:
- Status: ✅ Running
- Uptime: ~15 minutes
- API requests: 0 (awaiting Devin integration)
- Compression: 0% (no traffic yet)
- Cost savings: $0.00 (no traffic yet)

**MCP Filtering Status**:
- Total tools: 22 (from 65+ original)
- Tool reduction: 66%
- All servers healthy
- All filters operational

## Usage Instructions

### Start Using Headroom Proxy

1. **Choose Integration Method**:
   ```bash
   # Run configuration script for options
   .windsurf/configure-devin-headroom.sh
   ```

2. **Apply Configuration**:
   - Add environment variable to shell profile (recommended)
   - Or configure in Devin Desktop settings
   - Restart Devin Desktop

3. **Verify Integration**:
   ```bash
   # Check proxy is receiving traffic
   .windsurf/check-headroom-stats.sh
   ```

### Monitor Performance

**Real-time Monitoring**:
```bash
