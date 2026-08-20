---
category: operations
---

# Universal health check with auto profile detection
mcp_call_tool server_name=workflows tool_name=execute_workflow \
  arguments='{"workflow": "universal-health-check", "inputs": {"profile": "auto", "skip_optional": true}}'

# System maintenance with disk threshold
mcp_call_tool server_name=workflows tool_name=execute_workflow \
  arguments='{"workflow": "system-cleanup", "inputs": {"disk_threshold": 85, "docker_prune": true}}'

# GPU health check with custom thresholds
mcp_call_tool server_name=workflows tool_name=execute_workflow \
  arguments='{"workflow": "gpu-health-check", "inputs": {"vram_warning": 75, "temp_warning": 70}}'
```

