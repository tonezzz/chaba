---
category: operations
---

# Technical Details

### Current MacBook Setup
- **macOS User**: kkkakk
- **Remote Access Profile**: Dedicated Chrome profile for Chrome Remote Desktop only
- **SSH Access**: Separate from Chrome Remote Desktop, user-specific
- **Network**: 192.168.1.50 on home network

### Profile Configuration
```yaml
Remote Access Profile:
  Purpose: Chrome Remote Desktop only
  Usage: Remote connections from Linux PC
  Browsing: Not used for regular browsing on MacBook
  Management: Dedicated to remote access function

Other Profiles:
  Purpose: Regular browsing, development, testing
  Usage: Local MacBook usage
  Chrome Remote Desktop: Not configured (avoids conflicts)
```

## Benefits

### Security
- Clear access control with single entry point
- No accidental access from unintended profiles
- Easy to audit and manage remote access

### Maintenance
- Clean profile without browsing clutter
- Easy to troubleshoot remote access issues
- Simple to reconfigure if needed

### Multi-User Support
- Other users can use MacBook independently
- No interference with remote access setup
- Concurrent access via different macOS accounts

