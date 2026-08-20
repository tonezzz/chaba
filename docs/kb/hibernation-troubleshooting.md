---
category: operations
---

# Hibernation Troubleshooting - Kernel Parameter Mismatch
## What it is

System hibernation was failing with error "Sleep verb 'hibernate' is not configured or configuration is not supported by kernel" despite having correct swap configuration and GRUB parameters.

## Context/Background

Created 2026-08-07 as part of Chaba infrastructure documentation.


## Context
System hibernation was failing with error "Sleep verb 'hibernate' is not configured or configuration is not supported by kernel" despite having correct swap configuration and GRUB parameters.

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

## See also

- [Hibernation Troubleshooting Steps](hibernation-troubleshooting-steps.md)
- [Hibernation Troubleshooting Technical](hibernation-troubleshooting-technical.md)
