---
bank: tony-projects
key: public-host-review
kind: note
last_verified: '2026-09-21'
scope: tony
source: voice
status: active
subject: public-host
valid_from: '2026-09-21'
written_by: ada_remember
---
Review of the public host plan on idc01: strengths are hardened SSH, firewall, automated deploys, and all three Ada instances healthy. Main risk: MDDB is a single instance with backups as the only safety net until a standby follower exists. Gaps: data-security hardening deferred, scheduled jobs not yet moved, Gemini and Home Assistant tokens should be rotated after the transcript leak.
