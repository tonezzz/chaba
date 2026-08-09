# Yomi Media Analysis HTTP 500 Error

## What it is

HTTP 500 errors occurring in the daily2 media analysis feature due to missing Gemini API environment variables in the yomi-api systemd service configuration.

## Context/Background

The daily2 media analysis feature was failing with HTTP 500 errors when attempting to analyze media content from LINE conversations. The root cause was missing environment variables required for Gemini vision model integration in the systemd service configuration.

## Key Details

### Root Cause
- **Missing Environment Variable**: `GEMINI_API_KEY` was not set in the yomi-api systemd service
- **Configuration Gap**: When media analysis feature was added to yomi-api, the GEMINI_API_KEY override from yomi-process service was not replicated
- **Service Override Pattern**: GEMINI_API_KEY was stored in `/etc/systemd/system/yomi-process.service.d/override.conf` but missing from yomi-api service configuration
- **Impact**: Media analysis jobs failed with "GEMINI_API_KEY environment variable not set" error
- **Service Affected**: `/etc/systemd/system/yomi-api.service`

### Systemd Override Pattern
Systemd service overrides in `.service.d/override.conf` are used for sensitive environment variables that shouldn't be in the main service file.

**yomi-process Service Override**:
- **File**: `/etc/systemd/system/yomi-process.service.d/override.conf`
- **Contains**: `GEMINI_API_KEY` environment variable
- **Purpose**: Keeps sensitive API key out of main service file for security

**yomi-api Service Override (Missing)**:
- **File**: `/etc/systemd/system/yomi-api.service.d/override.conf`
- **Required**: Same `GEMINI_API_KEY` configuration as yomi-process
- **Issue**: When media analysis was added to yomi-api, this override was not created

**Fix Applied**:
Created `/etc/systemd/system/yomi-api.service.d/override.conf` with the same GEMINI_API_KEY configuration as yomi-process service.

### Verification Method
Tested media analysis via API endpoints to confirm successful job completion:
- Verified proper model usage (gemini-2.5-flash, gemini-2.5-flash-lite)
- Confirmed token counting was working correctly
- Checked job status transitions from pending → processing → completed
- Validated error messages were resolved after override configuration

### Systemd Service Configuration
**File**: `/etc/systemd/system/yomi-api.service`

**Required Environment Variables**:
- `GEMINI_API_KEY` - Gemini API authentication key
- `GEMINI_VISION_MODEL_PRIMARY` - Primary vision model for media analysis
- `GEMINI_VISION_MODEL_FALLBACK` - Fallback vision model
- `CONTEXT_MESSAGES_BEFORE` - Number of messages before media to include as context
- `CONTEXT_MESSAGES_AFTER` - Number of messages after media to include as context
- PostgreSQL connection variables (DATABASE_URL, etc.)

### Database Job Failures
**Table**: `media_analysis_jobs`

**Error Pattern**: Jobs failing with error message:
```
GEMINI_API_KEY environment variable not set
```

**Impact**: All media analysis jobs in the queue failing until environment variables configured.

### API Status Check Behavior
**Endpoint**: Status check endpoint for media analysis

**Failure Mode**: When media analysis jobs fail due to missing environment variables:
- Returns HTTP 500 status code
- Includes error details in response
- Frontend displays as "Status check failed"

## Technical Details

### Environment Variable Configuration
The yomi-api service requires the following environment variables for media analysis:

```ini
[Service]
Environment="GEMINI_API_KEY=your_api_key_here"
Environment="GEMINI_VISION_MODEL_PRIMARY=gemini-2.5-flash"
Environment="GEMINI_VISION_MODEL_FALLBACK=gemini-2.5-flash-lite"
Environment="CONTEXT_MESSAGES_BEFORE=5"
Environment="CONTEXT_MESSAGES_AFTER=5"
Environment="DATABASE_URL=postgresql://user:pass@localhost/dbname"
```

### Media Analysis Flow
1. Media analysis job created in `media_analysis_jobs` table
2. yomi-api service attempts to process job
3. Service reads environment variables for Gemini API configuration
4. If `GEMINI_API_KEY` missing, job fails immediately
5. Status check endpoint returns HTTP 500 with error details
6. Frontend displays "Status check failed" to user

## Usage/Commands

### Check Systemd Service Configuration
```bash
# View current yomi-api service configuration
sudo systemctl cat yomi-api.service

# Check if service is running
sudo systemctl status yomi-api.service

# View service logs for errors
sudo journalctl -u yomi-api.service -n 50
```

### Update Systemd Service Configuration
```bash
# Create override directory if it doesn't exist
sudo mkdir -p /etc/systemd/system/yomi-api.service.d

# Create override.conf with sensitive environment variables
sudo nano /etc/systemd/system/yomi-api.service.d/override.conf

# Add content (example):
[Service]
Environment="GEMINI_API_KEY=your_api_key_here"

# Reload systemd configuration
sudo systemctl daemon-reload

# Restart the service
sudo systemctl restart yomi-api.service

# Verify service is running
sudo systemctl status yomi-api.service

# Verify override is loaded
sudo systemctl cat yomi-api.service
```

### Check Database Job Status
```bash
# Connect to PostgreSQL
psql -U yomi_user -d yomi_database

# Check media analysis jobs for failures
SELECT job_id, status, error_message, created_at 
FROM media_analysis_jobs 
WHERE status = 'failed' 
ORDER BY created_at DESC 
LIMIT 10;
```

### Test API Status Check
```bash
# Test media analysis status endpoint
curl http://localhost:3000/api/yomi/media-analysis/status

# Check for HTTP 500 responses indicating environment variable issues
```

## Troubleshooting

### HTTP 500 on Media Analysis
**Symptom**: Media analysis returns HTTP 500 error

**Diagnosis Steps**:
1. Check yomi-api service logs: `sudo journalctl -u yomi-api.service -n 50`
2. Look for "GEMINI_API_KEY environment variable not set" error
3. Verify environment variables in service configuration: `sudo systemctl cat yomi-api.service`
4. Check if `GEMINI_API_KEY` is present in `[Service]` section

**Solution**: Add missing environment variables to systemd service and restart

### Service Fails to Start After Configuration Change
**Symptom**: yomi-api service fails to start after editing configuration

**Diagnosis Steps**:
1. Check service status: `sudo systemctl status yomi-api.service`
2. Review logs for syntax errors: `sudo journalctl -u yomi-api.service -n 20`
3. Verify systemd syntax: `sudo systemd-analyze verify /etc/systemd/system/yomi-api.service`

**Solution**: Fix syntax errors in service file, reload, and restart

### Environment Variables Not Taking Effect
**Symptom**: Environment variables added but service still fails

**Diagnosis Steps**:
1. Verify `daemon-reload` was run: `sudo systemctl daemon-reload`
2. Check service was restarted: `sudo systemctl restart yomi-api.service`
3. Verify variables in running process: `sudo systemctl show yomi-api.service --property=Environment`

**Solution**: Ensure daemon-reload and service restart performed after configuration changes

### Database Jobs Continue Failing After Fix
**Symptom**: Environment variables fixed but existing jobs still failing

**Diagnosis Steps**:
1. Check if jobs need to be retried: `SELECT * FROM media_analysis_jobs WHERE status = 'failed'`
2. Verify new jobs succeed: Trigger a new media analysis job
3. Check if job retry logic exists in the application

**Solution**: Manually retry failed jobs or implement job retry mechanism

## Prevention

### Configuration Management
- Document all required environment variables in deployment documentation
- Use environment variable management tools (systemd drop-in files, environment files)
- Validate environment variables on service startup
- Implement health checks that verify required environment variables
- **Check for service overrides**: When adding features to a service, check if related services have `.service.d/override.conf` files with sensitive variables
- **Replicate override patterns**: When moving functionality between services, ensure all override configurations are replicated
- **Document override locations**: Maintain a list of which services have override files and what they contain

### Monitoring
- Monitor media analysis job failure rates
- Alert on HTTP 500 errors from media analysis endpoints
- Track environment variable-related errors in logs
- Implement periodic validation of service configuration

### Testing
- Test service startup after configuration changes
- Validate environment variables are loaded correctly
- Test media analysis with sample data after configuration updates
- Implement integration tests for environment variable dependencies

## Related Documentation

- **[yomi.md](yomi.md)** - Yomi LINE web app comprehensive documentation
- **[yomi-daily2-calendar.md](yomi-daily2-calendar.md)** - Daily2 calendar page documentation
- **[gemini-api-limits.md](gemini-api-limits.md)** - Gemini API configuration and limits
- **[health-check.md](health-check.md)** - Health check dashboard and API endpoints


## Tags

- **yomi**: LINE conversation management
- **media-analysis**: Media content analysis feature
- **systemd**: Systemd service configuration
- **environment-variables**: Environment variable management
- **http-500**: HTTP error troubleshooting
- **gemini-api**: Gemini API integration
- **daily2**: Daily2 feature implementation
- **troubleshooting**: Error diagnosis and resolution
