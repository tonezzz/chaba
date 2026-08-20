---
category: operations
---

# Implementation

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
