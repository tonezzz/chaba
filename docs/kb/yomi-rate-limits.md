---
category: operations
---

# LINE API Rate Limit Management (2026-08-06)

### Rate Limit Code 103
- **Error Message**: `認証が一時的に制限されています。しばらく経ってからもう一度お試してください。`
- **Translation**: "Authentication is temporarily restricted. Please try again later."
- **Cause**: Too many login attempts in short period
- **Duration**: Typically 1-24 hours
- **Impact**: yomi-fetch.timer finds 0 conversations, cannot download new messages

### Mitigation Strategies
1. **Wait for restriction to lift** - Monitor periodically, attempt login every 2 hours
2. **Exponential backoff** - Implement retry logic with increasing delays (1min, 5min, 15min, 1hr, 4hr)
3. **Rate limit detection** - Parse error codes and trigger automatic retry logic
4. **Login attempt throttling** - Limit login attempts to once per hour maximum
5. **Session persistence** - Maintain valid session longer to reduce login frequency

### Implementation Plan
- Add rate limit detection to `fetch-conversations.mjs`
- Implement exponential backoff for login retries
- Add login attempt logging to track frequency
- Monitor session validity and proactively refresh before expiry
- Document LINE API rate limit policies

### Current Status
- **Rate Limit Active**: Yes (2026-08-06)
- **Last Login Attempt**: Failed with code 103
- **Next Action**: Wait for restriction to lift, then re-login
- **Improvement**: LINE API Rate Limit Mitigation added to ssot.improvements.yml
- **Variable daily summary quality** → Some conversations show rich extraction (events/actions/topics) while others have empty arrays despite having messages. Check `/api/yomi/summary-quality` for per-conversation metrics (2026-08-05).
- **Systemd service failure** → If `yomi-api.service` fails but API runs manually, check logs: `journalctl -u yomi-api.service`. May need to restart service or fix configuration (2026-08-05).
- **Database cleanup required** → Some conversations have `last_message_time: null` despite having messages, and duplicate entries with corrupted chat_id fields containing keyMaterial JSON. Use SQL to fix null timestamps and remove duplicates (2026-08-05).

## UI Improvements (Post-Improvement Session)

The Yomi web UI was streamlined for better usability:

### Consolidated Refresh Actions
- Single refresh button in header (previously multiple refresh controls)
- Refresh indicator shows active fetching/processing
- Automatic refresh on page load

### Actions Menu
- Three-dot menu (⋮) for per-conversation actions
- Options: Refresh, Open in new tab, Mark as read
- Cleaner interface with fewer visible buttons

### Collapsible Categories
- Category chips toggle visibility of conversations
- Active filters highlighted with category colors
- Group/ungroup toggle for conversations
- Real-time count updates per category

### Conditional Scroll Controls
- Scroll-to-top button appears only when needed
- Smooth scrolling behavior
- Responsive to viewport changes

## LINE API Rate Limit Mitigation (2026-08-12)

### Problem
LINE API authentication rate limit (code 103) was preventing Yomi message downloads due to too many login attempts.

### Solution Implemented

**Exponential Backoff Retry Logic:**
- Delays: 1min, 5min, 15min, 1hr, 4hr for rate limit errors
- Applied to both conversation list fetching and single conversation fetching
- Maximum 5 retry attempts before giving up

**Rate Limit Detection:**
- Parses error codes: 103, "rate limit", "temporarily restricted", Japanese error message
- Detects LINE session validation failures
- Identifies authentication-related errors

**Login Attempt Throttling:**
- Maximum 1 login attempt per hour tracked in `login-attempts.json`
- Prevents automated login attempts from triggering rate limits
- Session validation before attempting fetch operations

**Session Management:**
- New API endpoint: `GET /api/yomi/session-status` - validates LINE session and tracks login attempts
- New API endpoint: `POST /api/yomi/login` - triggers LINE login process with proper throttling
- UI integration: Session status indicator and login button in Yomi web interface
- Desktop notifications for session expiration events

### Implementation Details

**File**: `scripts/yomi/fetch-conversations.mjs`
- Added `isRateLimitError()` function for error detection
- Added `recordLoginAttempt()` and `shouldAttemptLogin()` for throttling
- Added `validateSession()` for pre-fetch session validation
- Modified `fetchSingle()` and `fetchAll()` to support retry logic with exponential backoff

**File**: `scripts/yomi/yomi-api.mjs`
- Added `handleSessionStatus()` endpoint for session validation
- Added login endpoint that invokes Yomi CLI with proper environment setup
- Changed default Node executable from `/usr/local/bin/node` to `node` for portability

**File**: `stacks/web/public/apps/yomi/index.html`
- Added session status indicator (valid/invalid/checking states)
- Added login button with throttling status display
- Implemented polling for session status after login initiation
- Added desktop notification integration for session events

### Benefits
- Prevents future rate limit disruptions
- Automatic recovery from temporary restrictions
- Reduced manual intervention for session management
- Better user experience with visible session status
- Configurable throttling limits to prevent API abuse

### Configuration
```bash
# Login attempt tracking file
LOGIN_ATTEMPT_FILE: /home/tony/CascadeProjects/chaba/stacks/web/public/apps/yomi/fetch-data/login-attempts.json

# Rate limiting
MAX_LOGIN_ATTEMPTS_PER_HOUR: 1

# Retry configuration
MAX_RETRIES: 5
BACKOFF_DELAYS: [60000, 300000, 900000, 3600000, 14400000] # 1min, 5min, 15min, 1hr, 4hr
```

