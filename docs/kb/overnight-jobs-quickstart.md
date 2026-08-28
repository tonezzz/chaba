---
category: operations
---

# Quick Start

### Option 1: Manual Execution (Recommended for Tonight)
```bash
cd /home/tony/CascadeProjects/chaba
./scripts/run-overnight-now.sh
```

This will:
- Start the assessment immediately in the background
- Save logs to `logs/overnight-manual-TIMESTAMP.log`
- Generate report in `reports/overnight-assessment-TIMESTAMP.md`
- Allow you to go to sleep while it runs

### Option 2: Systemd Timer (Automated Daily)
```bash
# Install the systemd service and timer
sudo cp systemd/overnight-assessment.service /etc/systemd/system/
sudo cp systemd/overnight-assessment.timer /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable overnight-assessment.timer
sudo systemctl start overnight-assessment.timer

# Check timer status
sudo systemctl status overnight-assessment.timer

