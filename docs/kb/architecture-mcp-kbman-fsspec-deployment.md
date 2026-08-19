---
knowledge_key: mcp-kbman-fsspec-container-deployment
type: architecture
title: mcp-kbman fsspec Container Deployment
category: operations
description: Container-friendly Google Drive access using fsspec with service account authentication
tags: [mcp-kbman, fsspec, container, google-drive, service-account]
created: '2026-08-11'
updated: '2026-08-11'
---

# mcp-kbman fsspec Container Deployment

## Overview

Container-friendly deployment approach for mcp-kbman using fsspec with Google Drive service account authentication. This solves the permission issues with rclone mounts in containers while maintaining Google Drive as the storage backend.

## Why fsspec?

**Advantages over OAuth:**
- Service account authentication (no browser interaction)
- Container-friendly authentication
- Standard fsspec interface (well-established ecosystem)
- No interactive authentication required

**Advantages over GitHub token auth:**
- Keeps Google Drive as storage backend (current architecture)
- No migration needed
- Better performance (direct API access)
- Familiar storage location

**Advantages over rclone mount:**
- No filesystem permission issues in containers
- No mount dependency
- Better container isolation
- Native Python integration

## Implementation

### Backend Implementation

**gdrive_fsspec_backend.py:**
```python
from gdrive_fsspec import GoogleDriveFileSystem

class GDriveFsspecBackend:
    def __init__(self):
        self._fs = GoogleDriveFileSystem(
            creds=service_account_credentials,
            token="service_account"
        )
    
    def read_file(self, path: str) -> str:
        full_path = f"{self._folder_path}/{path}"
        with self.fs.open(full_path, 'r') as f:
            return f.read()
```

**Search Indexer Integration:**
```python
# In search/indexer.py
if config.settings.use_fsspec_backend:
    from gdrive_fsspec_backend import get_gdrive_backend
    self._gdrive_backend = get_gdrive_backend()

def _read_file_content(self, file_path: Path):
    if self._gdrive_backend and str(file_path).startswith('/home/tony/GoogleDrive'):
        relative_path = str(file_path).replace('/home/tony/GoogleDrive/Tony AI/KB/', '')
        return self._gdrive_backend.read_file(relative_path)
    # Fallback to local filesystem
    with open(file_path, 'r', encoding='utf-8') as f:
        return f.read()
```

### Configuration

**config.py:**
```python
# fsspec Configuration
gdrive_service_account_json: str = os.getenv("GDRIVE_SERVICE_ACCOUNT_JSON", "/config/service_account.json")
use_fsspec_backend: bool = os.getenv("USE_FSSPEC_BACKEND", "false").lower() == "true"
```

**requirements.txt:**
```
gdrive-fsspec>=0.4.0
```

### Container Configuration

**docker-compose.yml:**
```yaml
services:
  mcp-kbman:
    volumes:
      - /home/tony/.config/service_account.json:/config/service_account.json:ro
      - /home/tony/.cache/mcp-kbman:/cache
    environment:
      - USE_FSSPEC_BACKEND=true
      - GDRIVE_SERVICE_ACCOUNT_JSON=/config/service_account.json
      - GDRIVE_FOLDER_PATH=/Tony AI/KB
```

## Service Account Setup

### 1. Create Service Account in GCP Console

1. Go to [Google Cloud Console](https://console.cloud.google.com/)
2. Create a new project or select existing project
3. Navigate to IAM & Admin → Service Accounts
4. Click "Create Service Account"
5. Name: `mcp-kbman-drive`
6. Click "Create and Continue"

### 2. Enable Google Drive API

1. Navigate to APIs & Services → Library
2. Search for "Google Drive API"
3. Click "Enable"

### 3. Download Service Account Key

1. Go to IAM & Admin → Service Accounts
2. Click on the service account
3. Go to "Keys" tab
4. Click "Add Key" → "Create new key"
5. Select "JSON" format
6. Download and save securely

### 4. Share KB Folder with Service Account

1. Open Google Drive
2. Right-click on "Tony AI/KB" folder
3. Share with service account email
4. Grant "Editor" permissions

### 5. Configure Credentials

```bash
# Save service account key
mkdir -p ~/.config
mv ~/Downloads/service-account-key.json ~/.config/service_account.json
chmod 600 ~/.config/service_account.json
```

## Deployment Options

### Host-Based Deployment (Current)

**Configuration:**
```bash
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

## References

- [gdrive-fsspec GitHub](https://github.com/fsspec/gdrive-fsspec)
- [fsspec Documentation](https://filesystem-spec.readthedocs.io/)
- [Google Cloud Service Accounts](https://cloud.google.com/iam/docs/service-accounts)
- [Google Drive API Documentation](https://developers.google.com/drive/api)