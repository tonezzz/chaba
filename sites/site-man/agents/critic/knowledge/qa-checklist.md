# QA Checklist (Draft)

1. Verify node-1 health (`/api/health`).
2. Confirm glama and other API keys loaded.
3. Run `npm test` for affected packages.
4. Ensure Tony sandboxes render on desktop + iPhone webviews.
5. Confirm restart mechanism works via `/api/app/restart`.
