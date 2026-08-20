---
category: operations
---

# Verification

### Checking Current Settings

```bash
# Check current DPMS status
xset q | grep -i dpms

# Check current screen timeout
xset q | grep -i timeout

# Check cron job
crontab -l | grep screen-timeout

# Manual script test
/home/tony/screen-timeout-scheduler.sh
```

### Testing Schedule Transitions

```bash
# Test daytime configuration (force hour to 8am)
HOUR=8 /home/tony/screen-timeout-scheduler.sh
xset q | grep -i dpms  # Should show DPMS disabled

# Test nighttime configuration (force hour to 11pm)
HOUR=23 /home/tony/screen-timeout-scheduler.sh
xset q | grep -i dpms  # Should show DPMS enabled
```

### Monitoring PlayLive Session Stability

- Monitor PlayLive logs for session closure errors
- Verify long-running operations complete successfully
- Check that sessions persist across daytime hours
- Confirm no "Target page, context or browser has been closed" errors during daytime

