#!/bin/bash
#
# Setup Cron Jobs for Documentation Infrastructure Automation
# Configures automated backups and verification
#

set -e

echo "Setting up cron jobs for documentation infrastructure automation..."
echo "=========================================="

# Backup cron job (daily at 3 AM)
echo "Adding daily backup cron job (3 AM)..."
(crontab -l 2>/dev/null | grep -v "backup-configs.sh"; echo "0 3 * * * /home/tony/CascadeProjects/chaba-tony-dell/scripts/backup-configs.sh >> /home/tony/CascadeProjects/chaba-tony-dell/docs/backups/backup.log 2>&1") | crontab -
echo "✓ Daily backup scheduled: 0 3 * * *"

# Verification cron job (weekly on Sunday at 2 AM)
echo "Adding weekly verification cron job (Sunday 2 AM)..."
(crontab -l 2>/dev/null | grep -v "verify-docs.sh"; echo "0 2 * * 0 /home/tony/CascadeProjects/chaba-tony-dell/scripts/verify-docs.sh >> /home/tony/CascadeProjects/chaba-tony-dell/docs/backups/verify.log 2>&1") | crontab -
echo "✓ Weekly verification scheduled: 0 2 * * 0"

echo "=========================================="
echo "Cron jobs configured successfully"
echo ""
echo "Current crontab:"
crontab -l
echo ""
echo "Logs location:"
echo "  Backup log: docs/backups/backup.log"
echo "  Verification log: docs/backups/verify.log"
