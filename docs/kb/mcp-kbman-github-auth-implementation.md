---
category: operations
---

# Implementation Details

### GitHub Storage Architecture

Based on know-ops-mcp implementation:

```python
# Simple token authentication
headers = {
    "Authorization": f"Bearer {token}",
    "Accept": "application/vnd.github+json",
    "X-GitHub-Api-Version": "2022-11-28",
}

# Base64 content encoding
content = base64.b64encode(content.encode("utf-8")).decode("ascii")

# Git Trees API for listing (up to 100k entries)
GET /repos/{owner}/{repo}/git/trees/{branch}?recursive=true
```

### Caching Strategy

```python
# XDG-aware cache directory
cache_dir = ~/.cache/mcp-kbman/

# Write-through caching
def write(name, content):
    backend.write(name, content)  # GitHub
    disk.write(cache_dir, name, content)  # Local cache

# Zero network requests for cached reads
def read(name):
    cached = disk.read(cache_dir, name)
    if cached:
        return cached  # No network call
    return backend.read(name)  # Only on cache miss
```

### Rate Limit Handling

```python
# Automatic retry on 429 or 403 with rate limit exhausted
if r.status_code == 429 or (r.status_code == 403 and rate_limit_exhausted):
    wait_time = compute_retry_after(r.headers)
    time.sleep(wait_time)
    retry()
```

## Container Configuration

### Environment Variables

```yaml
environment:
  - GITHUB_TOKEN=ghp_xxx  # Personal Access Token
  - GITHUB_REPO=yourname/kb-repo
  - GITHUB_BRANCH=main
  - GITHUB_SUBDIRECTORY=kb
  - CACHE_DIR=/cache
  - SEARCH_INDEX_DIR=/cache/search_index
  - PRE_GENERATED_DIR=/cache/pre_generated
```

### Docker Compose Setup

```yaml
services:
  mcp-kbman:
    build:
      context: .
      dockerfile: Containerfile
    container_name: mcp-kbman
    restart: unless-stopped
    volumes:
      # Mount project docs
      - /home/tony/CascadeProjects/chaba/docs:/home/tony/CascadeProjects/chaba/docs:ro
      # Mount local cache directory (writable)
      - /home/tony/.cache/mcp-kbman:/cache
      # Mount config directory
      - /home/tony/.config/mcp-kbman:/config
    environment:
      - GITHUB_TOKEN=${GITHUB_TOKEN}
      - GITHUB_REPO=${GITHUB_REPO}
      - GITHUB_BRANCH=main
      - GITHUB_SUBDIRECTORY=kb
      - CACHE_DIR=/cache
      - SEARCH_INDEX_DIR=/cache/search_index
      - PRE_GENERATED_DIR=/cache/pre_generated
```

