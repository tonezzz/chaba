# Rollback Playbook (Draft)

- Run `scripts/rollback-node-1.sh` from repo root to revert to previous release.
- Verify container restarted: GET /api/health, then visit `/` and `/tony` panels.
- Announce rollback status to ops chat with commit hash.
- Capture follow-up tasks in `state/status.json` for Critic agent review.
