---
category: operations
---

# Troubleshooting

### PlayLive Sessions Still Closing

**Check DPMS Status**:
```bash
xset q | grep -i dpms
# Should show "DPMS is Disabled" during daytime (7am-10pm)
```

**Verify Script Execution**:
```bash
# Check cron logs
sudo journalctl -u cron | grep screen-timeout

# Manually run script
/home/tony/screen-timeout-scheduler.sh
echo $?  # Should return 0
```

**Check Display Environment**:
```bash
echo $DISPLAY
# Should be set (e.g., :0 or :1)
```

### Screen Not Turning Off at Night

**Verify Cron Job**:
```bash
crontab -l | grep screen-timeout
# Should show: */5 * * * * /home/tony/screen-timeout-scheduler.sh
```

**Check Current Time**:
```bash
date
# Should be after 10pm for nighttime mode
```

**Test Nighttime Configuration**:
```bash
# Force nighttime mode
HOUR=23 /home/tony/screen-timeout-scheduler.sh
xset q | grep -i timeout  # Should show 60 seconds
```

### xset Command Not Found

**Install X11 Tools**:
```bash
# Debian/Ubuntu
sudo apt-get install x11-xserver-utils

# RHEL/CentOS
sudo yum install xorg-x11-utils
```

### DISPLAY Variable Not Set

**Set Display for Cron**:
```bash
# Add to crontab:
*/5 * * * * export DISPLAY=:0 && /home/tony/screen-timeout-scheduler.sh

# Or add to script:
export DISPLAY=:0
```

