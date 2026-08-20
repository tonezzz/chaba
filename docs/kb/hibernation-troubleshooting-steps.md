---
category: operations
---

# Troubleshooting Steps

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

