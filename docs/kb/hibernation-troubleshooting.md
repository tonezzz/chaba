# Hibernation Troubleshooting - Kernel Parameter Mismatch
## What it is

System hibernation was failing with error "Sleep verb 'hibernate' is not configured or configuration is not supported by kernel" despite having correct swap configuration and GRUB parameters.

## Context/Background

Created 2026-08-07 as part of Chaba infrastructure documentation.


## Context
System hibernation was failing with error "Sleep verb 'hibernate' is not configured or configuration is not supported by kernel" despite having correct swap configuration and GRUB parameters.

## Root Cause
System was running older kernel (7.0.0-28-generic) without updated hibernation parameters, while GRUB configuration had been updated for newer kernel (7.0.0-29-generic). The `/sys/power/disk` showed `[disabled]` indicating hibernation was not enabled in the current kernel.

## Technical Details

### Configuration Status
- **GRUB Configuration**: Correct
  - `resume=UUID=e440de9e-3603-423f-8022-595196c0ef30 resume_offset=34816`
  - Located in `/etc/default/grub` under `GRUB_CMDLINE_LINUX_DEFAULT`

- **Swap File**: Properly configured
  - Location: `/data/hibernate.swap` (32GB)
  - Physical offset: 34816 (verified via `filefrag -v`)
  - Also has `/swapfile` (16GB) as secondary swap

- **Initramfs**: Updated with resume configuration
  - Configured in `/etc/initramfs-tools/conf.d/resume`
  - Updated via `sudo update-initramfs -u`

- **Kernel Mismatch**: 
  - Running: 7.0.0-28-generic
  - GRUB configured for: 7.0.0-29-generic
  - This caused hibernation parameters to not be active

### System State
- Secure Boot: Enabled (confirmed via `mokutil --sb-state`)
- NVIDIA Drivers: Loaded (nvidia_uvm, nvidia_drm, nvidia_modeset modules present)
- Power States: Only `freeze mem` available (missing `disk` for hibernation)
- Disk Mode: `[disabled]` (should show `platform` or other modes)

## Verification Commands

### Check Current Configuration
```bash
# Check current kernel parameters
cat /proc/cmdline

# Check if hibernation is enabled
cat /sys/power/disk  # Should show "platform" instead of "[disabled]"

# Check available power states
cat /sys/power/state  # Should include "disk" for hibernation

# Verify kernel version
uname -r
```

### Verify Swap Configuration
```bash
# Show active swap devices
swapon --show

# Check physical offset of swap file
sudo filefrag -v /data/hibernate.swap

# Verify swap file UUID
findmnt -no UUID -T /data/hibernate.swap
```

### Test Hibernation
```bash
# Test hibernation via systemd
systemctl hibernate

# Check hibernation service status
systemctl status systemd-hibernate
```

## Solution

### Immediate Fix
1. Reboot to load newer kernel (7.0.0-29-generic) with updated hibernation parameters
2. After reboot, verify hibernation is enabled:
   ```bash
   cat /sys/power/disk  # Should show "platform" or other modes
   cat /sys/power/state  # Should include "disk"
   ```
3. Test hibernation:
   ```bash
   systemctl hibernate
   ```

### Configuration Updates (if needed)
```bash
# Update GRUB configuration
sudo update-grub

# Update initramfs with resume configuration
sudo update-initramfs -u

# Reboot to apply changes
sudo reboot
```

## Prevention

### After GRUB Configuration Changes
1. Always run `sudo update-grub` to update boot configuration
2. Always run `sudo update-initramfs -u` to update initramfs
3. Reboot to load new kernel with updated parameters
4. Verify kernel version matches between `/proc/version` and GRUB config

### Regular Verification
```bash
# Check kernel version matches GRUB config
uname -r
sudo grep -A 2 "linux.*vmlinuz" /boot/grub/grub.cfg | head -5

# Verify hibernation is enabled
cat /sys/power/disk
cat /sys/power/state
```

## Troubleshooting Steps

### If hibernation still fails after reboot
1. Check for conflicting kernel parameters:
   ```bash
   cat /proc/cmdline | grep -i nohibernate
   cat /proc/cmdline | grep -i noswap
   ```

2. Verify swap file is not corrupted:
   ```bash
   sudo swapoff /data/hibernate.swap
   sudo swapon /data/hibernate.swap
   ```

3. Check systemd sleep configuration:
   ```bash
   systemd-analyze cat-config systemd/sleep.conf
   ```

4. Review system logs for hibernation errors:
   ```bash
   sudo journalctl -xe | grep -i hibernate
   ```

### Common Issues
- **Secure Boot conflicts**: May prevent kernel module loading for hibernation
- **NVIDIA drivers**: Can cause hibernation issues; ensure proper suspend/resume hooks
- **Swap file fragmentation**: Use contiguous swap files for hibernation
- **Insufficient swap size**: Swap should be at least equal to RAM size

## Related Documentation
- `docs/kb/system-automation.md` - System automation and monitoring
- `docs/ssot/ssot.health.home.yml` - System health monitoring configuration

## Tags

- **monitoring**: monitoring
- **health**: health
- **metrics**: metrics
- **logging**: logging
- **documentation**: documentation
- **kb**: kb
- **knowledge-base**: knowledge-base
- **ssot**: ssot
- **configuration**: configuration
- **infrastructure**: infrastructure
- **hibernation**: hibernation
- **power**: power
- **system**: system
- **2026**: 2026
