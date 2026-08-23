# Tony-Dell Overnight Git Push 2026-08-18

## What it is

Tony-Dell Overnight Git Push 2026-08-18

## Context/Background

**Date:** 2026-08-18
**Session Context:** 

## Key Details

### Technical Details
Tony-Dell overnight git push (2026-08-18):
- Cloned chaba master to /home/tony/CascadeProjects/chaba-tony-dell on tony-dell.
- Configured ~/.config/systemd/user/focus-dispatcher-overnight.service with ExecStartPre 'git -C ... pull --ff-only' and Environment SKIP_HEALTH=1, FOCUS_DISPATCHER_COMMIT=1, FOCUS_DISPATCHER_PUSH=1.
- Copied ~/.config/secrets/github-mcp.env to tony-dell and generated ~/.git-credentials using git-credential-store so unattended HTTPS push works.
- Verified overnight-focus-review.py dry-run and a real git push from tony-dell to GitHub.
- Updated ssot.night-jobs.yml, ssot.focus.current.yml, and ssot.focus.yml.

Conventions:
- For unattended git push on a secondary host, use a dedicated worktree, pull --ff-only in a systemd ExecStartPre, and store credentials in ~/.git-credentials (0600) via git-credential-store.
- SKIP_HEALTH=1 is required on tony-dell because node/mcp-health-client is not available there.
- Image 2 (imagen2-inference) is parked for a model-aware rebuild due to PyTorch/transformers vulnerabilities.

### Implementation
- **Status:** Documented
- **Date:** 2026-08-18
- **Location:** docs/kb/

## Related Documentation

- **[KB Migration Summary](kb-migration-summary-2026-08-13.md)** - Related migration work

## Tags

- **infrastructure**: System infrastructure changes
- **documentation**: Knowledge base documentation
- **migration**: System migration and updates
