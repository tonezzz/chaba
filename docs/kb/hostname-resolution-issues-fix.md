# Hostname Resolution Issues - /etc/hosts Configuration

## Context

Hostname resolution issues can cause web services to become inaccessible even when DNS resolution appears to work correctly. This commonly occurs when `/etc/hosts` file contains incorrect IP address mappings for local hostnames.

## Problem

**Symptoms:**
- Web services accessible via `localhost` but not via hostname (e.g., `tony-omen.local`)
- DNS resolution works (`nslookup` returns correct hostname) but HTTP connectivity fails
- Health checks pass when using hardcoded IPs but fail with hostname-based checks
- Browser shows "site can't be reached" for hostname URLs

**Root Cause:**
The `/etc/hosts` file contains an incorrect IP address mapping for the local hostname. For example:
```bash
# Incorrect mapping
192.168.1.52 tony-omen.local  # Wrong IP for local machine

# Correct mapping  
192.168.1.51 tony-omen.local  # Actual local machine IP
```

## Detection

**Manual Detection:**
```bash
# Check current /etc/hosts mapping
cat /etc/hosts | grep tony-omen.local

# Get actual local machine IP (most reliable method)
ip route get 1.1.1.1 | awk '{print $7}'

# Verify DNS resolution
nslookup tony-omen.local

# Test HTTP connectivity
curl -s -o /dev/null -w "%{http_code}" http://tony-omen.local:8080/
```

**Automated Detection:**
The universal health check workflow now includes hostname resolution verification:
- Compares resolved IP from DNS with actual local machine IP
- Outputs warning messages when mismatch detected
- Uses `ip route get` for reliable local IP detection
- Provides clear guidance for `/etc/hosts` correction

## Solution

**Immediate Fix:**
```bash
# Update /etc/hosts with correct IP mapping
sudo sed -i 's/192.168.1.52 tony-omen.local/192.168.1.51 tony-omen.local/' /etc/hosts

# Verify the fix
cat /etc/hosts | grep tony-omen.local

# Test HTTP connectivity
curl -s http://tony-omen.local:8080/
```

**Alternative Manual Edit:**
```bash
# Edit hosts file
sudo nano /etc/hosts

# Find and correct the tony-omen.local entry
# Change from: 192.168.1.52 tony-omen.local
# Change to:   192.168.1.51 tony-omen.local
```

## Prevention

**System Verification Improvements:**
1. **Hostname-based health checks:** All workflows now use `tony-omen.local` instead of hardcoded IPs
2. **Resolution verification:** Health checks compare DNS resolution with local IP
3. **Warning messages:** Clear output when hostname resolution issues detected
4. **Reliable IP detection:** Uses `ip route get` method for accurate local IP identification

**Workflow Updates:**
- `universal-health-check.yml`: Added hostname resolution verification
- `home-profile-health-check.yml`: Changed to hostname-based service checks
- Both workflows now detect and warn about `/etc/hosts` mapping issues

**SSOT Documentation:**
- Added `hostname_resolution_issues` recovery actions to `ssot.health.yml`
- Documented detection and fix procedures
- Included prevention measures for future occurrences

## Technical Details

**Local IP Detection Methods:**
```bash
# Most reliable (uses routing table)
ip route get 1.1.1.1 | awk '{print $7}'

# Fallback (first non-loopback, non-link-local interface)
ip addr show | grep "inet " | grep -v "127.0.0.1" | grep -v "169.254" | head -1 | awk '{print $2}' | cut -d'/' -f1
```

**Hostname Resolution Check:**
```bash
# Get resolved IP from DNS
RESOLVED_IP=$(nslookup tony-omen.local 2>/dev/null | grep -A 1 "Name:" | tail -1 | awk '{print $2}')

# Get actual local IP
LOCAL_IP=$(ip route get 1.1.1.1 2>/dev/null | awk '{print $7}' | head -1)

# Compare and warn if mismatch
if [ "$RESOLVED_IP" != "$LOCAL_IP" ] && [ -n "$LOCAL_IP" ] && [ -n "$RESOLVED_IP" ]; then
  echo "WARNING: tony-omen.local resolves to $RESOLVED_IP but local IP is $LOCAL_IP"
  echo "WARNING: Check /etc/hosts file for correct IP mapping"
fi
```

## Related Documentation

- `docs/ssot/infrastructure/ssot.health.yml` - Network connectivity recovery actions
- `workflows/monitoring/universal-health-check.yml` - Hostname-based health checks
- `workflows/monitoring/home-profile-health-check.yml` - Home profile verification
- `/etc/hosts` - System hostname resolution configuration file

## Tags

hostname-resolution, network-connectivity, etc-hosts, dns, health-checks, system-verification, troubleshooting