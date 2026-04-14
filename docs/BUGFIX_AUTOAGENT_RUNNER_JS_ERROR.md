# Bugfix: AutoAgent Runner JavaScript Error

## Date
2026-04-14

## Issue
The **Smart Research** button on the AutoAgent Runner panel (`http://idc1.surf-thailand.com:8059/runner`) was not working due to a JavaScript syntax error.

### Error Message
```
runner:257 Uncaught SyntaxError: Unexpected identifier 't' (at runner:257:62)
runner:67 Uncaught ReferenceError: setFreeCommand is not defined
```

## Root Cause
Corrupted UTF-8 characters in `control-server.py` HTML template. The emoji characters (🧠 Smart Research, 📚 Browse Wiki) contained replacement characters (`U+FFFD` at bytes `efbfbd`) which broke JavaScript parsing.

## Files Affected
- `services/autoagent/control-panel/control-server.py` (lines 340, 342)
- `stacks/autoagent-test/control-server.py` (lines 386, 388)

## Fix Applied
Replaced corrupted emoji characters with proper Unicode emojis:

```python
# Before (broken):
<span class="preset" onclick='setFreeCommand(...)'> Smart Research</span>
<span class="preset" onclick='setCommand(...)'> Browse Wiki</span>

# After (fixed):
<span class="preset" onclick='setFreeCommand(...)'>🧠 Smart Research</span>
<span class="preset" onclick='setCommand(...)'>📚 Browse Wiki</span>
```

## Deployment
Restarted `autoagent-control-panel` container to apply changes:

```bash
docker restart autoagent-control-panel
```

## Prevention
- Use HTML entities (`&#x1F9E0;`) for complex emojis in inline JavaScript
- Validate UTF-8 encoding when editing files with non-ASCII characters
- Add automated tests for control panel JavaScript functionality

## Related
- AutoAgent Test Stack
- Smart Research
- Troubleshooting: Container Issues
