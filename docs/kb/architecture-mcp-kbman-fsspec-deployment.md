---
category: operations
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

## References

- [gdrive-fsspec GitHub](https://github.com/fsspec/gdrive-fsspec)
- [fsspec Documentation](https://filesystem-spec.readthedocs.io/)
- [Google Cloud Service Accounts](https://cloud.google.com/iam/docs/service-accounts)
- [Google Drive API Documentation](https://developers.google.com/drive/api)

## See also

- [Mcp Kbman Fsspec Implementation](mcp-kbman-fsspec-implementation.md)
- [Mcp Kbman Fsspec Usage](mcp-kbman-fsspec-usage.md)
