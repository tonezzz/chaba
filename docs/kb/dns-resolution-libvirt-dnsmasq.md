---
category: operations
---

# DNS Resolution: Avahi Interface Restriction Fix
## What it is

**Fix applied**: Restricted Avahi to `wlo1` interface only via `/etc/avahi/avahi-daemon.conf`:


## Status: RESOLVED (2026-08-05)

**Fix applied**: Restricted Avahi to `wlo1` interface only via `/etc/avahi/avahi-daemon.conf`:
```
allow-interfaces=wlo1
```
`tony-omen.local` now resolves to `192.168.1.48` correctly.

---

## Original Issue

DNS resolution issue where `tony-omen.local` resolved to a Docker bridge IP (172.20.0.x) or libvirt/VM network IP instead of the actual host IP (192.168.1.48), causing service connection failures.

## Context/Background

Identified 2026-08-05 during DNS investigation for hostname compliance enforcement. The issue occurs because libvirt's dnsmasq service responds to `.local` hostname queries with VM network addresses instead of the actual host IP.

## Key Details

### Root Cause

**libvirt dnsmasq Service**:
- libvirt runs its own dnsmasq instance for VM network management
- This dnsmasq responds to `.local` hostname queries
- Returns VM network IP addresses (typically 192.168.122.x range) instead of host IP
- Overrides system-level mDNS/Bonjour resolution for `.local` domains

**Resolution Flow**:
```
DNS Query: tony-omen.local
    ↓
System resolver checks:
    ↓
1. libvirt dnsmasq (responds first)
    ↓ Returns: 192.168.122.1 (VM network)
    ↓
2. System mDNS/Bonjour (never reached)
    ↓ Would return: 192.168.1.48 (actual host)
```

### Impact

**Service Connection Failures**:
- Health checks fail when using `tony-omen.local`
- Docker services unreachable via `.local` hostname
- Web stack services return connection errors
- API endpoints unreachable from other machines

**Affected Services**:
- Caddy web server (port 8080)
- Status API (port 8000)
- Yomi API (port 3000)
- GPU Queue API (port 3001)
- All services relying on hostname resolution

### Current Workaround

**Use IP Address Directly**:
- Use `192.168.1.48` instead of `tony-omen.local` for service configuration
- Documented in `docs/overview/hosts.tony-omen.yml`:
  ```yaml
  - label: Local domain
    text: tony-omen.local resolves to a libvirt/VM network, not the Docker host; use 192.168.1.48 for services.
  ```

**Location-Specific Health Configs**:
- `ssot.health.home.yml` - Uses IP addresses for home network
- `ssot.health.mobile.yml` - Uses IP addresses for mobile network
- Avoids `.local` hostname resolution entirely

## Resolution Options

### Option 1: Disable libvirt dnsmasq (Recommended)

**Steps**:
```bash
# Stop libvirt dnsmasq service
sudo systemctl stop libvirtd
sudo systemctl disable libvirtd

# Or disable dnsmasq specifically in libvirt config
sudo virsh net-destroy default
sudo virsh net-undefine default
```

**Pros**:
- Restores proper `.local` resolution
- Allows use of `tony-omen.local` consistently
- Aligns with hostname enforcement strategy

**Cons**:
- May affect VM network functionality
- Requires VM network reconfiguration if needed
- Potential impact on libvirt-managed VMs

### Option 2: Configure dnsmasq to Ignore .local

**Steps**:
```bash
# Edit libvirt dnsmasq configuration
sudo nano /etc/libvirt/qemu/networks/default.xml

# Add to dnsmasq:options section
<dnsmasq:option value='no-hosts'/>
<dnsmasq:option value='bogus-priv'/>
```

**Pros**:
- Preserves libvirt VM network functionality
- Allows selective `.local` handling

**Cons**:
- Complex configuration
- May not fully resolve conflict
- Requires libvirt service restart

### Option 3: Use Different Hostname Scheme

**Approach**:
- Use `tony-omen.home` instead of `tony-omen.local`
- Configure system DNS to resolve `.home` to correct IP
- Update all service configurations

**Pros**:
- Avoids libvirt dnsmasq conflict entirely
- Clean separation of concerns

**Cons**:
- Requires DNS server configuration
- Updates to all service configurations
- Deviates from `.local` convention

### Option 4: Continue Using IP Addresses (Current)

**Approach**:
- Continue using `192.168.1.48` for service configuration
- Document the libvirt dnsmasq issue
- Update hostname enforcement strategy with exception

**Pros**:
- No service disruption
- Works reliably
- Minimal configuration changes

**Cons**:
- Loses benefits of hostname abstraction
- IP address changes require updates
- Deviates from hostname enforcement policy

## Recommended Action

**Short-term**: Continue current workaround (Option 4)
- Document the issue clearly
- Use IP addresses in service configurations
- Update hostname enforcement strategy with libvirt exception

**Long-term**: Disable libvirt dnsmasq (Option 1)
- If VM network functionality is not critical
- Enables consistent `.local` hostname usage
- Aligns with hostname enforcement strategy

## Testing DNS Resolution

```bash
# Check current resolution
nslookup tony-omen.local
dig tony-omen.local
host tony-omen.local

# Check libvirt dnsmasq status
sudo systemctl status libvirtd
sudo netstat -tulpn | grep dnsmasq

# Check mDNS/Bonjour status
sudo systemctl status avahi-daemon
```

## Related Documentation

- **[hostname-enforcement-strategy.md](../assessments/hostname-enforcement-strategy.md)** - Hostname compliance enforcement
- **[mdns-assessment.md](../assessments/mdns-assessment.md)** - mDNS/Bonjour architecture and limitations
- **[hosts.tony-omen.yml](../overview/hosts.tony-omen.yml)** - Host documentation with current workaround

## Tags

- **dns**: Domain name system resolution
- **libvirt**: Virtualization network management
- **dnsmasq**: DNS forwarding service
- **hostname**: Hostname resolution issues
- **troubleshooting**: Network debugging
