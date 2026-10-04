# Session Transcript Assessment — 2026-10-04

Mining the idc02-migration / audit-remediation transcript (threads
`history_b27ea98e`, `history_3410e8e8` + continuation) for recurring
issues and scenario-able behaviors. Issues are grouped by whether they
were tooling defects, contract drift, or judgment/process lessons.

## Issues observed

| # | Issue | Class | Resolution |
|---|-------|-------|------------|
| 1 | `ssot-validate-all` result cache replayed stale warnings — keyed by file hash only, so a run between content-edit and rule-edit cached old-code verdicts under the new hash | tooling defect | fold script's own sha256 into `__configHash` (f9e07478) |
| 2 | `security-audit.sh` hardcoded `chaba-tony-dell` paths + dell-only checks (gdrive mount) — meaningless or noisy on other hosts | tooling defect | repo-relative paths; gdrive check gated on rclone remote existing (63c6abc5) |
| 3 | Audit heuristics mismatched reality: git-tracked "secret"-named files flagged, user units flagged for missing `User=` (invalid in user units), ephemeral wildcard binds flagged | tooling defect | tracked-file skip, system-target-only check, TCP-only + persistence re-check (63c6abc5) |
| 4 | `password_auth: "deviation — reason"` failed the audit's exact-match enum (`deviation`/`yes`/`needs-verification`) — declared-but-wrong-shape deviation | contract drift | normalize to bare `deviation`; reason lives in `deviations:` list (f9e07478) |
| 5 | Undeclared wildcard listeners on 4/6 hosts — all turned out to be intended services (m2m ssh, yt-live, ha-live, cast-server, caddy edge) | contract drift | declared in `ssot.security.<host>.yml` — 6/6 posture PASS |
| 6 | gdrive FUSE mount "active" but returning EIO — mount-presence ≠ mount-health; backups silently broken | real incident | `rclone-gdrive.service` restart; lesson: health checks must verify access, not mount table |
| 7 | Recurring non-fast-forward pushes / autostash juggling under concurrent sessions | process friction | standing rebase+pop discipline; no automation yet |
| 8 | `ADA_HIT_MAX_CHARS=2000` truncation: `sync-ssot-to-mddb.py` sits at char 7234 of the only bank doc naming it — Ada could see the doc but not the answer | retrieval gap | seeded curated `procedure/sync-ssot-to-mddb` doc in `ada-ha-bank-developer-tony`; `developer-recall-runbook` now PASSes |
| 9 | `infrastructure-ssot` bank stale (Sep 30) — posture facts undeclared to Ada | sync gap | `sync-ssot-to-mddb.py` run — 100 files synced |

## Scenario-able behaviors extracted

| Behavior | Scenario | Status |
|----------|----------|--------|
| Correct the "wildcard bind = open to the internet" false premise; recall declared posture (caddy :80/:443, ssh tailnet-fenced) | `idc02_edge_posture` (smoke) | **created + verified PASS** (d1d76f5, 636f533) |
| Recall exact runbook command from a curated procedure bank doc | `developer-recall-runbook` (existing, chronic fail since Sep 29) | **fixed root cause** — verified PASS live |
| Verify access, not presence, when judging mount/service health | not yet — no suitable Ada tool surface; candidate for host-logs/ops tooling rather than voice scenario | open |
| Distinguish "undeclared intended service" from rogue listener before baselining | Devin-side workflow; could become a `tools`-suite scenario if Ada gains an audit-triage tool | open |

## Notes for the scenario/benchmark system itself

- **Interim-filler truncation**: Gemini emits "one moment" utterances as
  completed responses; post-filler tool calls do not reset the settle
  window, so default `settle_s: 5–8` truncates the real answer. Any
  scenario asserting on answer content after tool-heavy turns needs
  `settle_s ≥ 30–45`.
- **calls_any on follow-up turns** is a bad expectation when the prior
  turn already fetched the facts — answering from context is the desired
  behavior.
- **`ADA_HIT_MAX_CHARS=2000` head-truncation** is a systemic recall
  hazard for long KB docs: any fact past char 2000 is invisible in
  surfaced hits. Improvement candidate: excerpt around the match span
  rather than the doc head (backend change, not done here — flagged).
