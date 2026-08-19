---
knowledge_key: mcp-kbman-github-token-auth
type: architecture
title: mcp-kbman GitHub Token Authentication
category: operations
description: Alternative container deployment approach using GitHub token authentication instead of OAuth
tags: [mcp-kbman, github, authentication, container]
created: '2026-08-11'
updated: '2026-08-11'
---

# mcp-kbman GitHub Token Authentication

## Overview

Alternative container deployment approach for mcp-kbman using GitHub token authentication instead of OAuth. Based on analysis of [know-ops-mcp](https://github.com/gyeo-ri/know-ops-mcp) GitHub backend implementation.

## Why GitHub Token Auth?

**Advantages over OAuth:**
- Simpler authentication flow (no browser interaction)
- Bearer token instead of complex OAuth dance
- Easier container deployment
- Better rate limits (5000/hr vs 60/hr for unauthenticated)
- No interactive authentication required

**Advantages over GDrive mount:**
- No filesystem permission issues in containers
- Better container isolation
- Native GitHub integration
- Multi-device sync via Git

## Implementation Details

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

## GitHub Token Setup

### Create Personal Access Token

1. Go to GitHub Settings → Developer Settings → Personal Access Tokens
2. Generate new token (classic) or fine-grained token
3. Required scopes:
   - `repo` (for classic tokens)
   - `contents:read` and `contents:write` (for fine-grained tokens)
4. Copy token and store securely

### Configure Environment

```bash
# Add to ~/.bashrc or ~/.zshrc
export GITHUB_TOKEN=ghp_xxx
export GITHUB_REPO=yourname/kb-repo
```

### Token Storage Options

**Option 1: Environment Variable (Recommended)**
```bash
export GITHUB_TOKEN=ghp_xxx
```

**Option 2: Config File**
```bash
# ~/.config/mcp-kbman/config.toml
[github]
token = "ghp_xxx"
repo = "yourname/kb-repo"
branch = "main"
subdirectory = "kb"
```

## Implementation Steps

### 1. Create GitHub Repository

```bash
# Create private repository for KB
gh repo create kb-repo --private --description "Personal Knowledge Base"
```

### 2. Migrate Existing KB

```bash
# Clone the repository
git clone git@github.com:yourname/kb-repo.git
cd kb-repo

# Copy existing KB content
cp -r /home/tony/GoogleDrive/Tony\ AI/KB/* .

# Commit and push
git add .
git commit -m "Initial KB migration"
git push origin main
```

### 3. Update mcp-kbman Configuration

Add GitHub backend to `config.py`:

```python
# GitHub Configuration
github_token: str = os.getenv("GITHUB_TOKEN", "")
github_repo: str = os.getenv("GITHUB_REPO", "")
github_branch: str = os.getenv("GITHUB_BRANCH", "main")
github_subdirectory: str = os.getenv("GITHUB_SUBDIRECTORY", "")
```

### 4. Implement GitHub Storage Class

Based on know-ops-mcp `GitHubStorage` class with:
- Token-based authentication
- Base64 content encoding
- Git Trees API for listing
- Rate limit handling
- Caching layer

### 5. Update Search Sources

```python
search_sources: list[str] = [
    "github:yourname/kb-repo:main:kb",  # GitHub backend
    "/home/tony/CascadeProjects/chaba/docs"  # Project documentation
]
```

## Comparison with Current Setup

### Current Setup (GDrive Mount)
- ✅ Working perfectly (95.7% coverage, 224 documents)
- ✅ Simple filesystem access
- ✅ No authentication complexity
- ❌ Container permission issues
- ❌ Rclone mount dependency

### GitHub Token Auth
- ✅ No container permission issues
- ✅ Better container isolation
- ✅ Native GitHub integration
- ✅ Multi-device sync via Git
- ✅ Simple token authentication
- ❌ Requires GitHub repository setup
- ❌ Additional implementation complexity
- ❌ API rate limits (though generous)

## Recommendation

**Keep current GDrive setup for now** because:
- Working perfectly with 95.7% coverage
- Simple and reliable
- No additional complexity needed
- Container infrastructure ready for future migration

**Document GitHub approach for future use** when:
- Container deployment becomes necessary
- Multi-device sync requirements increase
- GitHub integration becomes primary workflow

## References

- [know-ops-mcp GitHub Backend](https://github.com/gyeo-ri/know-ops-mcp)
- [GitHub REST API Documentation](https://docs.github.com/en/rest)
- [GitHub Personal Access Tokens](https://docs.github.com/en/authentication/keeping-your-account-and-data-secure/managing-your-personal-access-tokens)
- [Git Trees API](https://docs.github.com/en/rest/git/trees)