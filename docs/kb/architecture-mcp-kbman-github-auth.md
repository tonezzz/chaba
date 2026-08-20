---
category: operations
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

## References

- [know-ops-mcp GitHub Backend](https://github.com/gyeo-ri/know-ops-mcp)
- [GitHub REST API Documentation](https://docs.github.com/en/rest)
- [GitHub Personal Access Tokens](https://docs.github.com/en/authentication/keeping-your-account-and-data-secure/managing-your-personal-access-tokens)
- [Git Trees API](https://docs.github.com/en/rest/git/trees)

## See also

- [Mcp Kbman Github Auth Implementation](mcp-kbman-github-auth-implementation.md)
- [Mcp Kbman Github Auth Recommendation](mcp-kbman-github-auth-recommendation.md)
- [Mcp Kbman Github Auth Setup](mcp-kbman-github-auth-setup.md)
