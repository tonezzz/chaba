---
kind: procedure
status: active
subject: tony-omen
attribute: mouse-stuttering
outcome: good
last_verified: 2026-09-21
confidence: 0.8
---

# tony-omen mouse stuttering → fixed by restarting tony-omen

Symptom (2026-09-21): pointer/mouse stuttering observed directly on
tony-omen's own desktop session (`:0` console seat) — witnessed
firsthand, not via a remote display path.

Root cause: undiagnosed. Assumed to be one or more local processes
hogging CPU/IO; the user did not dig into per-process usage before
restarting. If it recurs, check `top`/`ps aux --sort=-%cpu` and IO
(`iotop`, `vmstat 1`) before rebooting so the culprit is captured.

Resolution: a full restart of tony-omen cleared the stuttering; lighter
remedies were not confirmed to help.

Lesson: for desktop input stutter on tony-omen, a reboot is a proven
fix — but spend a minute grabbing the top CPU/IO offenders first so the
next occurrence can be attributed.
