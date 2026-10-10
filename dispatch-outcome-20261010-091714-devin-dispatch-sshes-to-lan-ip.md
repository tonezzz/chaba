# dispatch-outcome: devin-dispatch-lan-ip

## What was found

- The card's failure is live right now: from idc02 **and** idc03 (Ada's
  current home), `ssh 192.168.2.67` → Connection timed out, while
  `ssh -o BatchMode=yes tony-dell` / `tony-dell.taila0626a.ts.net` /
  `100.68.142.13` all succeed with key auth.
- The "LAN IP is mandatory" rule from
  `docs/ssot/ssot.learning.ada-devin-dispatch.2026-09-24.yml` is **stale**:
  `tailscale debug prefs` on tony-dell shows `RunSSH: false` — tailscaled
  no longer intercepts :22; plain sshd (0.0.0.0:22) answers on the tailnet
  IP. No interactive re-auth risk remains.
- ssh configs already key the tailnet path everywhere it matters:
  tony-omen `Host tony-dell`→100.68.142.13 (id_ed25519), mn01
  `Host tony-dell`→100.68.142.13 (id_ed25519_tonydell), idc03
  `Host tony-dell(-m2m)`→100.68.142.13 (id_tony_dell), idc02 resolves
  `tony-dell` via MagicDNS with default keys. Bonus bug: mn01 has **no**
  `tony-dell-lan` alias — the old `EVENT_SSH:-tony-dell-lan` default was
  already silently broken there.

## What changed (chaba worktree)

Scripts — every ssh-to-dell default now uses the tailnet name `tony-dell`
(all remain env-overridable):

- `scripts/ops/ssh-canary.sh` — `EVENT_SSH` default `192.168.2.67` →
  `tony-dell` (+comment). Canary still probes the LAN path — that's its
  job — but the alert channel no longer depends on the path it monitors.
- `scripts/ops/staleness-sentinel.sh` — same default flip (+comment).
- `scripts/ops/mn01-canary.sh` — same default flip (+header comment).
- `scripts/devin/job-run.sh` — `EVENT_SSH` default `tony-dell-lan` →
  `tony-dell`.
- `scripts/devin/devin-dispatch-watch.sh` — same (+comment).
- `scripts/devin/devin-dispatch-prune.sh` — same.
- `scripts/devin/dispatch-queue.sh` — usage example `tony-dell-lan` →
  `tony-dell`.

Docs — stale guidance corrected, history preserved:

- `docs/runbooks/ada-devin-handoff-workflow.md` — dispatch line, outcome
  channel table, and the "ssh must use the LAN IP" gotcha all reversed to
  tailnet with the RunSSH evidence.
- `docs/ssot/ssot.learning.ada-devin-dispatch.2026-09-24.yml` — lesson
  `tailscaled-ssh-intercepts-plain-ssh` marked `superseded: REVERSED
  2026-10-10`; prevention rewritten ("targets must survive LAN
  partitioning").
- `docs/ssot/jobs/ada/2026-09-22-ada-devin-dispatch.yml` — step-5 note
  tagged superseded.
- New job doc: `docs/ssot/jobs/infrastructure/2026-10-10-dispatch-ssh-tailnet.yml`.

Kanban — the remaining half lives in ada-pi (outside this worktree):

- New card `ada-dispatch-tailnet-target` (repo: ada-pi, queued) — flip
  `ADA_DEVIN_DISPATCH_HOST` default `192.168.2.67` → `tony-dell` in
  `backend/devin_dispatch.py` + `tools.d/devin.py`, with verification
  steps.

## Result

Chaba-side complete and verified. The actual Ada→dispatch ssh call
(`ssh 192.168.2.67 ~/.local/bin/devin-dispatch`) is in ada-pi, so voice
dispatch stays dead off-LAN until the sibling card lands — it's queued
for dispatch.

## How to verify

- `bash -n` clean on all six edited scripts; all touched YAML parses.
- `ssh -o BatchMode=yes -o ConnectTimeout=6 tony-dell true` from
  idc02/idc03/mn01/tony-omen (done live this session).
- Deployed `~/.local/bin` copies lead repo copies — the script changes
  take effect per-host on the next install/sync pass.
- `ssot-validate-all.mjs` not runnable here (no node on idc02); PyYAML
  parse used instead.

lessons:
- Alert channels must not depend on the path they monitor — EVENT_SSH's
  LAN-IP default meant a LAN outage also silenced the outage alarm.
- Dated infrastructure lessons expire: RunSSH flipped off and a rule
  written for it became the bug; mark superseded, don't silently edit.
- `ssh -G <alias>` + `tailscale debug prefs` settle "which path does
  service ssh actually take" in seconds.
