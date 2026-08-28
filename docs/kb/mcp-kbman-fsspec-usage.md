---
category: operations
---

# Environment variables (default)
USE_FSSPEC_BACKEND=false
# Uses rclone mount at /home/tony/GoogleDrive
```

**Advantages:**
- Working perfectly (95.7% coverage, 224 documents)
- Simple filesystem access
- No authentication complexity

### Container Deployment (fsspec)

**Configuration:**
```bash
# Environment variables
USE_FSSPEC_BACKEND=true
GDRIVE_SERVICE_ACCOUNT_JSON=/config/service_account.json
```

**Advantages:**
- Container-friendly
- No filesystem permission issues
- Better isolation
- Service account authentication

## Comparison Summary

| Approach | Container-Friendly | Current Storage | Auth Complexity | Performance |
|----------|-------------------|-----------------|-----------------|-------------|
| **Current (rclone mount)** | ❌ Permission issues | ✅ Google Drive | ✅ None | ✅ Excellent |
| **OAuth** | ❌ Browser required | ✅ Google Drive | ❌ Complex | ✅ Good |
| **GitHub token** | ✅ Container-friendly | ❌ GitHub (migration) | ✅ Simple | ✅ Good |
| **fsspec + Service Account** | ✅ Container-friendly | ✅ Google Drive | ✅ Simple | ✅ Excellent |

## Usage

### Enable fsspec Backend

```bash
# Set environment variable
export USE_FSSPEC_BACKEND=true
export GDRIVE_SERVICE_ACCOUNT_JSON=/home/tony/.config/service_account.json

# Start container
cd /home/tony/CascadeProjects/chaba-kbman/mcp-kbman
./start-container.sh
```

### Disable fsspec (Use rclone)

```bash
# Set environment variable
export USE_FSSPEC_BACKEND=false

# Start container (will use rclone mount if available)
cd /home/tony/CascadeProjects/chaba-kbman/mcp-kbman
./start-container.sh
```

## Troubleshooting

### Service Account Not Found

**Error:** `Service account credentials not found at /config/service_account.json`

**Solution:**
1. Verify service account key file exists
2. Check volume mount in docker-compose.yml
3. Verify file permissions

### Google Drive API Not Enabled

**Error:** `API not enabled for project`

**Solution:**
1. Enable Google Drive API in GCP Console
2. Verify service account has correct permissions
3. Check service account email format

### Folder Not Shared

**Error:** `File not found` or permission errors

**Solution:**
1. Share KB folder with service account email
2. Grant "Editor" permissions
3. Verify folder path in configuration

