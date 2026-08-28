---
title: "Journal — KB structure, memories, and tony-omen session fix"
category: operations
date: 2026-07-21
tags: [journal, kb, tony-omen]
status: completed
---

# 2026-07-21 — KB structure improvements and tony-omen fix

## Quick capture

- Fixed recurring GDM "Session Already Running" on `tony-omen`.
- Removed Chrome Remote Desktop to prevent the blocker from returning.
- Assessed KB structure and added per-device change logs, a memory index, richer templates, and a backup plan.

## Done today

1. **tony-omen "Session Already Running" fix**
   - Diagnosed cause: xrdp + Chrome Remote Desktop registered active `Type=x11` logind sessions; GDM 50 refuses a second graphical session and its Force Stop button is broken.
   - Cleared stuck xrdp session `c9`, stopped xrdp/CRD, restarted GDM.
   - Applied permanent xrdp PAM fix (`XDG_SESSION_TYPE=tty`) so RDP no longer blocks local login.
   - Removed `chrome-remote-desktop` package and unused dependencies.

2. **KB structural improvements**
   - Updated `.windsurfrules`, `README.md`, and `meta/workflow.md` to invoke helper scripts with `bash` because the GDrive mount is `noexec`.
   - Added `meta/memories.md` as a first-check index for recurring issues.
   - Created per-device change logs:
     - `hardware/tony-dell/changes.md`
     - `hardware/tony-omen/changes.md`
     - `projects/android-box/changes.md`
   - Added `meta/backup.md` with off-site git remote and local-copy options.
   - Enriched templates (`hardware.md`, `project.md`, `task.md`, `journal.md`) with `Changes`, `Decisions / why`, and `Blockers` sections.
   - Updated `hardware/README.md` to act as a quick-status dashboard.

3. **Git workflow**
   - Confirmed local git identity is set (`Tony` / `tony@local`) so `kb-end.sh` commits work on any synced PC.
   - Committed all KB changes.

## Decisions / why

| Decision | Reason |
|----------|--------|
| Invoke KB helper scripts with `bash` | The GDrive FUSE mount is `noexec`; shebang execution fails even with `+x` |
| Keep `xrdp`, remove Chrome Remote Desktop | xrdp can be made GDM-safe via PAM; CRD always spawns a conflicting X11 session and has no clean workaround |
| Add `meta/memories.md` | The memory system returned nothing for the session blocker; an explicit index prevents rediscovery |
| Use `changes.md` per device/project | Decisions and reasons are now scannable without reading full notes or git history |
| Keep backup remote URL as a placeholder | Cannot create the user’s private repo without credentials; setup steps documented in `meta/backup.md` |

## Notes

- `tony-omen.local` resolved to `192.168.1.48` today; mDNS name was not always reliable earlier in the session.
- KB commit history is clean and the working tree is now unmodified.

## Open questions

- Which off-site backup option should we use? (private GitHub/GitLab repo, self-hosted, or periodic USB copy)
- Should we also add a `hardware/android-box/` folder instead of keeping the Android box under `projects/`?

## Tomorrow / next

- Decide and set up the off-site backup.
- Consider adding a per-project `changes.md` template or rule.
