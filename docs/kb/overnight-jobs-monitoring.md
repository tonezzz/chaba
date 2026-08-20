---
category: operations
---

# Monitoring Progress

### While Running
```bash
# Monitor the log file in real-time
tail -f logs/overnight-manual-TIMESTAMP.log

# Check if the process is still running
ps aux | grep overnight-jobs

# Check the last few lines of progress
tail -20 logs/overnight-manual-TIMESTAMP.log
```

### After Completion
```bash
# View the generated report
cat reports/overnight-assessment-TIMESTAMP.md

# Check for any errors in the log
grep -i error logs/overnight-manual-TIMESTAMP.log

# View summary of what was completed
grep "===.*===" logs/overnight-manual-TIMESTAMP.log
```

