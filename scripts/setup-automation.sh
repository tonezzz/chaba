#!/bin/bash

# System Automation Setup Script
# Sets up cron jobs for GPU monitoring and system maintenance

SCRIPT_DIR="/home/tony/CascadeProjects/chaba/scripts"
LOG_DIR="/home/tony/CascadeProjects/chaba/logs/automation"

# Create log directory
mkdir -p "$LOG_DIR"

echo "Setting up system automation..."

# GPU Monitoring - every 5 minutes
(crontab -l 2>/dev/null | grep -v "gpu-monitor"; echo "*/5 * * * * $SCRIPT_DIR/gpu-monitor.mjs >> $LOG_DIR/gpu-monitor.log 2>&1") | crontab -

# System Maintenance - daily at 3 AM
(crontab -l 2>/dev/null | grep -v "system-maintenance"; echo "0 3 * * * $SCRIPT_DIR/system-maintenance.mjs >> $LOG_DIR/system-maintenance.log 2>&1") | crontab -

# Overnight Assessment - daily at 2 AM
(crontab -l 2>/dev/null | grep -v "overnight-assessment"; echo "0 2 * * * $SCRIPT_DIR/overnight-assessment.mjs >> $LOG_DIR/overnight-assessment.log 2>&1") | crontab -

echo "Automation setup complete!"
echo "Scheduled tasks:"
echo "  - GPU Monitoring: Every 5 minutes"
echo "  - System Maintenance: Daily at 3 AM"
echo "  - Overnight Assessment: Daily at 2 AM"
echo ""
echo "Logs will be saved to: $LOG_DIR"
echo ""
echo "Current crontab:"
crontab -l