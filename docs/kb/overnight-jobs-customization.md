---
category: operations
---

# Customization

### Change Assessment Schedule
Edit `systemd/overnight-assessment.timer`:
```ini
[Timer]
OnCalendar=*-*-* 03:30:00  # Change to 3:30 AM
```

### Add/Remove Assessment Areas
Edit `scripts/overnight-jobs-expanded.sh` and comment out or add sections as needed.

### Change Output Locations
Edit the variables at the top of `scripts/overnight-jobs-expanded.sh`:
```bash
REPORT_DIR="/path/to/your/reports"
LOG_DIR="/path/to/your/logs"
```

