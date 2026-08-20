---
category: operations
---

# GitHub Token Setup

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

