#!/bin/bash
# Manual execution script for overnight assessment
# Run this before going to sleep to start the overnight jobs immediately

TIMESTAMP=$(date +%Y%m%d-%H%M%S)
echo "Starting overnight assessment jobs..."
echo "This will run comprehensive system analysis in the background."
echo "Logs will be saved to logs/overnight-manual-$TIMESTAMP.log"
echo "Report will be saved to reports/overnight-assessment-$TIMESTAMP.md"
echo ""

cd /home/tony/CascadeProjects/chaba
nohup ./scripts/overnight-jobs-expanded.sh > logs/overnight-manual-$TIMESTAMP.log 2>&1 &

echo "Overnight assessment started in background."
echo "Process ID: $!"
echo "You can now safely go to sleep."
echo ""
echo "To monitor progress:"
echo "  tail -f logs/overnight-manual-$TIMESTAMP.log"
echo ""
echo "To check if it's still running:"
echo "  ps aux | grep overnight-jobs"