# Dispatch outcome — yomi-line-session-expired-idc03 (2026-11-25)

## What was found

The card framed this as a plain expired LINE session. Diagnosis on idc03
showed **two stacked failures**:

1. **Plumbing bug (fixed):** `yomi-update-all`/`yomi-update-active` run
   `podman run` as container-root with no `HOME` override. Yomi resolves its
   data dir via `os.homedir()` → `/root/.local/share/yomi`, which is NOT the
   mounted `/home/tony/.local/share/yomi`. Result: `session.restore.skip
   reason="no_saved_auth_token"` and `Wrote 0` every run — the on-disk
   `line-credentials.json` was never even read. Journal shows 0 rows written
   for every run since at least 2026-11-22 (earlier history vacuumed).
2. **Genuinely expired LINE session (needs Tony):** after fixing HOME, a
   manual run finds the credentials but LINE rejects them —
   `Access token refresh required` on getProfile/getMessageBoxes; the
   refresh token is dead too. The Sep-2 `line-credentials.json` is a
   fleet-wide identical copy (idc03, idc02, tony-dell; tony-omen has an
   older Aug-26 one) and the local yomi MCP on tony-macbook fails the same
   way — no host holds a live session.

## What changed

- `docs/ssot/infrastructure/ssot.jobs.yml`: added `-e HOME=/home/tony` to the
  `yomi-update-all` and `yomi-update-active` podman exec lines (lands via the
  normal dispatch merge + unit re-render).
- **Live on idc03 (interim, reversible):**
  - `~/.config/systemd/user/yomi-update-all.service.d/home.conf` and
    `yomi-update-active.service.d/home.conf` — ExecStart drop-ins with the
    same `-e HOME=/home/tony` (marked "remove after re-render lands").
  - `~/.config/yomi/yomi-api.env`: appended `HOME=/home/tony`; restarted
    `yomi-api.service` (hand unit, not in ssot.jobs.yml). Its
    `/api/yomi/session-status` now answers
    `{"valid":false,...,"canAttemptLogin":true}`.
- Runbook: `docs/ssot/jobs/infrastructure/2026-11-25-yomi-idc03-home-data-dir.yml`
- Board: progress comms + a `/request` to Tony with the exact re-login
  command (`node /home/tony/.yomi/mcpb/run.mjs login --phone
  +66809006872 --region TH` on idc03; pwless 180s patch already applied).

## Verification done

- `systemctl --user start yomi-update-all.service` after the drop-in: log
  now shows `session.restore.start`, `e2ee.keys.imported`, and fails only at
  LINE auth (`Access token refresh required`) — proving credentials are now
  visible; only the expired token remains.
- `curl 127.0.0.1:3000/api/yomi/session-status` on idc03 → valid:false,
  canAttemptLogin:true.

## Still blocked on Tony

LINE passwordless re-login requires his phone (PIN + approve, ~3 min). Once
he runs the command, `line-credentials.json` refreshes on idc03 and the next
hourly `yomi-update-all` should write >0 rows (drop-ins already live). After
the ssot.jobs.yml merge re-renders the units, delete the two
`.d/home.conf` drop-ins.

lessons:
- Podman one-shot units running as root get homedir()=/root — any tool that
  resolves state via $HOME/.local/share silently reads an empty dir even
  when the real data dir is volume-mounted elsewhere. Always pass
  `-e HOME=/home/<user>` (or the tool's *_DATA_DIR override) in container
  exec lines.
- "session.resume_failed / No persisted LINE session" can mean "file not
  found", not "token expired" — check `[LINE] session.restore.skip
  reason=no_saved_auth_token` vs `validation_failed` to tell them apart.
- yomi's line-credentials.json is a fleet-shared copy (identical mtime/hash
  across hosts); one re-login anywhere can be scp'd to the others.
- yomi-api.service on idc03 is a hand-managed unit outside ssot.jobs.yml —
  job-rendered fixes don't reach it; check `systemctl --user cat` before
  assuming SSOT coverage.
