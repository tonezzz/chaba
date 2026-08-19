---
category: troubleshooting
---

# PlayLive Screen Timeout: DPMS Session Closure

## What it is

DPMS (Display Power Management Signaling) screen power management causes PlayLive Chrome CDP sessions to close unexpectedly, breaking browser automation with "Target page, context or browser has been closed" errors. Resolved with a time-based screen timeout scheduler that balances PlayLive compatibility with power savings.

## Context/Background

Identified during PlayLive automation operations where Chrome CDP sessions would fail after periods of inactivity. The root cause was DPMS screen power management turning off the display, which caused Chrome CDP connections to terminate. This created a conflict between power saving needs and PlayLive's requirement for persistent browser sessions.

## Key Details

### Root Cause

**DPMS Screen Power Management**:
- Linux DPMS (Display Power Management Signaling) automatically powers off displays after timeout
- When screen turns off, Chrome CDP (Chrome DevTools Protocol) sessions terminate
- PlayLive relies on persistent CDP connections for browser automation
- Session closure causes "Target page, context or browser has been closed" errors

**Failure Pattern**:
```
PlayLive CDP Session Active
    ↓
Screen timeout reached (DPMS activates)
    ↓
Display powers off
    ↓
Chrome CDP connection terminates
    ↓
PlayLive automation fails with session closure error
```

### Impact

**PlayLive Automation Failures**:
- Browser sessions close unexpectedly during automation workflows
- Long-running operations fail after screen timeout
- Intermittent "Target page, context or browser has been closed" errors
- Unreliable automation for E2E testing and verification

**Operational Impact**:
- Recurring PlayLive failures requiring manual intervention
- Lost automation state and session data
- Disrupted AI-driven browser workflows
- Reduced reliability of automated verification

### Solution

**Time-Based Screen Timeout Scheduler**:
- Cron-based scheduler running every 5 minutes on tony-dell
- Disables DPMS during active hours (7am-10pm) for PlayLive compatibility
- Enables DPMS during off-hours (10pm-7am) for power saving
- Uses xset commands to control screen timeout and DPMS state

**Schedule Configuration**:
- **Daytime (7am-10pm)**: 15-minute timeout, DPMS disabled
- **Nighttime (10pm-7am)**: 1-minute timeout, DPMS enabled
- **Check interval**: Every 5 minutes via cron
- **Transition handling**: Automatic at 7am and 10pm boundaries

## Implementation

### Scheduler Script

**Location**: `/home/tony/screen-timeout-scheduler.sh` on tony-dell.local

**Script Logic**:
```bash
#!/bin/bash
# Screen timeout scheduler for PlayLive compatibility

HOUR=$(date +%H)
DAY_START=7
DAY_END=22  # 10pm in 24-hour format

if [ $HOUR -ge $DAY_START ] && [ $HOUR -lt $DAY_END ]; then
    # Daytime: Disable DPMS for PlayLive compatibility
    xset s 900 900  # 15-minute timeout
    xset s off      # Disable DPMS
    xset -dpms      # Turn off DPMS
else
    # Nighttime: Enable DPMS for power saving
    xset s 60 60    # 1-minute timeout
    xset s on       # Enable DPMS
    xset +dpms      # Turn on DPMS
fi
```

### Cron Configuration

**Cron Entry**:
```cron
*/5 * * * * /home/tony/screen-timeout-scheduler.sh
```

**Schedule Details**:
- Runs every 5 minutes
- Checks current hour and applies appropriate screen settings
- Automatic transitions at 7am (enable PlayLive mode) and 10pm (enable power saving)
- Minimal overhead: simple bash script with xset commands

### xset Commands

**Daytime Configuration (PlayLive Compatible)**:
```bash
xset s 900 900    # Set 15-minute screen timeout (900 seconds)
xset s off        # Disable screensaver
xset -dpms        # Disable DPMS (Display Power Management Signaling)
```

**Nighttime Configuration (Power Saving)**:
```bash
xset s 60 60      # Set 1-minute screen timeout (60 seconds)
xset s on         # Enable screensaver
xset +dpms        # Enable DPMS for screen power management
```

## Configuration

### Timeout Values

| Period | Hours | Timeout | DPMS | Purpose |
|--------|-------|---------|------|---------|
| Daytime | 7am-10pm | 15 minutes | Disabled | PlayLive compatibility |
| Nighttime | 10pm-7am | 1 minute | Enabled | Power saving |

### Host Configuration

**Primary Host**: tony-dell.local
- PlayLive daemon runs on tony-dell
- Chrome CDP endpoint on tony-dell
- Screen timeout scheduler runs on tony-dell
- Display connected to tony-dell for DPMS control

**Environment Requirements**:
- X server running (for xset commands)
- Display accessible (DISPLAY environment variable set)
- Cron daemon active
- xset utility installed (standard X11 tool)

## Technical Details

### DPMS and CDP Interaction

**Why DPMS Affects CDP**:
- Chrome CDP maintains a connection to the browser process
- Display power state changes can trigger browser cleanup
- Some Chrome builds terminate CDP sessions when display state changes
- PlayLive's persistent session model assumes stable display state

**Chrome Behavior**:
- CDP is designed for testing/automation scenarios
- Display state changes are considered environment changes
- Some Chrome versions are more sensitive to DPMS than others
- Headless Chrome would avoid this issue (but PlayLive uses live Chrome)

### Scheduler Design Rationale

**5-Minute Check Interval**:
- Frequent enough to ensure timely transitions
- Minimal system overhead
- Handles clock adjustments and system wake from sleep
- Reduces risk of missed schedule boundaries

**15-Minute Daytime Timeout**:
- Long enough to avoid interruption during active work
- Short enough to provide some power saving during idle periods
- DPMS disabled is the key factor for PlayLive compatibility
- Timeout value is secondary when DPMS is disabled

**1-Minute Nighttime Timeout**:
- Aggressive power saving during unused hours
- Quick screen-off when not in use
- DPMS enabled allows full power management
- PlayLive not expected to be used during nighttime hours

### Alternative Approaches Considered

**Option 1: Disable DPMS Entirely**
- Pros: Maximum PlayLive compatibility
- Cons: No power saving, increased energy consumption
- Rejected: Not environmentally responsible

**Option 2: Use Headless Chrome**
- Pros: No display dependency
- Cons: Loses live browser debugging capability, requires PlayLive changes
- Rejected: Reduces PlayLive's utility for interactive debugging

**Option 3: Chrome Flags to Ignore Display State**
- Pros: No infrastructure changes
- Cons: Chrome flags may not be reliable, version-dependent
- Rejected: Uncertain effectiveness, maintenance burden

**Option 4: Time-Based Scheduler (Selected)**
- Pros: Balances automation needs with power saving, simple implementation
- Cons: Requires cron and xset setup
- Selected: Best balance of reliability and efficiency

## Verification

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

## Troubleshooting

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

## Related Documentation

- **[ssot.apps.playlive.yml](../ssot/apps/ssot.apps.playlive.yml)** - PlayLive SSOT documentation with screen power management limitation note
- **[playlive-authentication.md](./playlive-authentication.md)** - PlayLive basic authentication implementation
- **[playwright-vs-playlive.md](./playwright-vs-playlive.md)** - PlayLive vs Playwright comparison and architecture

## Tags

- **playlive**: Browser automation daemon
- **dpms**: Display Power Management Signaling
- **screen-timeout**: Display power management configuration
- **chrome-cdp**: Chrome DevTools Protocol
- **automation**: Browser automation reliability
- **infrastructure**: System configuration and scheduling
- **power-management**: Energy saving configuration
- **troubleshooting**: Session closure debugging