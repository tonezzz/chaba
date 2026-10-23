# Dispatch outcome — omen-dedicate-nest (2026-10-23, runner idc02)

## Result

All six card steps processed. The substantive fix: **travel-slim is now
durably exited on tony-omen** — the 2026-10-12 session only *started* the
scorers (unit stayed `disabled`), so the 2026-10-19 reboot silently killed
open-jev again. This run made it persistent and removed the mechanism that
would keep knocking it down.

## What changed

**On tony-omen (applied via ssh):**
- `open-jev.service` (:8777, gemma-3-4b) + `open-jev-student.service`
  (:8778, gemma-3-1b): `enable --now` — both `/health` ok (4b load_s 141s).
- `open-jev-leash.timer`: `disable --now` — retired (no "bench leftovers"
  exist when scorers are meant to stay up).
- `~/.config/systemd/user/ada-pi-orch-bench.service`: ExecStartPost scorer
  stop → no-op; ExecStartPre health-wait kept; comment updated; backup at
  `.bak-travelslim`; daemon-reload done.
- Memory after: ~24G used / ~5G avail of 31G — stable, no OOM. Watch item.

**Repo (commit `5dd3b2f4` on `dispatch/20261023-130505-…`, not pushed):**
- `systemd/ada-pi-orch-bench.service` — same ExecStartPost change (hand
  unit is the deployed source of truth per ssot.jobs.yml).
- `systemd/open-jev-leash.{service,timer}` — deleted.
- `ssot.health.home.system.yml` — both scorers `expected_state: active`;
  leash-timer entry removed.
- `ssot.audit.hosts.yml` — leash.timer dropped from expected units;
  open-jev "stop residue" known_failed entries re-labeled (a failure now
  is a real crash).
- `ssot.jobs.yml` — orch-bench note documents the no-op ExecStartPost.
- `ssot.host-capacity.yml` — dell re-measured (220G disk/78G free post-SSD,
  ~4G mem avail), `tony_macbook` role → `primary-desktop + portable-dev`,
  omen note updated (~5G avail watch; GNOME decision pending).
- New trail doc `docs/ssot/jobs/nest/2026-10-23-omen-travel-slim-exit.yml`.

## Per-step findings

1. **host-capacity** — role was already `lan-hub + nest-gpu-lane`; added
   desktop→macbook note + refreshed dell/omen measurements.
2. **travel-slim** — exited durably (above). The 10-19 Mon 04:30
   orch-bench ran clean (`Result=success`) under the old lifecycle; next
   run Mon 10-26 should pass ExecStartPre instantly and leave scorers up.
3. **ollama/kanban-brief** — omen :11434 serving (gpt-oss:20b etc.);
   kanban-brief's LLM actually rides idc02 :11434 (qwen2.5:7b, `chat-local`
   chain) — also serving. **Separate flake found**: `chaba-kanban-brief`
   on idc03 failed every 30-min run 10:02→13:02 with `RemoteDisconnected`
   on the MDDB `add` POST (:11027) — writes appear to land anyway (page
   updated 13:00) but the unit exits 1. Same signature as nest-mgr's
   intermittent tick errors. Flagged in the job doc; not fixed here.
4. **nest-mgr→CMS** — verified: `ada-cms-pages/nest-tony-omen` last
   published 13:10 ICT (8 nodes, 3 active) — the lane reports fine.
5. **GNOME vs headless+CRD** — board request raised. Current state:
   gdm greeter on tty1 with no interactive session (idle 2d) +
   chrome-remote-desktop session already active → effectively headless+CRD
   today; recommended formalizing by disabling gdm3.
6. **offload duty** — card's premise is stale: triggers not firing (dell
   disk 63% used post-SSD, idc03 ~50% mem). placement_policy already sends
   non-LAN load to idc02/con01; omen's lane is GPU/LAN. No moves made.

## How to verify

- `ssh tony-omen 'curl -s http://100.75.102.88:8777/health && curl -s http://100.75.102.88:8778/health'` → both `ok:true`
- `ssh tony-omen 'systemctl --user is-enabled open-jev open-jev-student; systemctl --user is-active open-jev-leash.timer'` → enabled/enabled, inactive
- After Mon 10-26 04:30: `ssh tony-omen 'systemctl --user show ada-pi-orch-bench -p Result; systemctl --user is-active open-jev'` → success + still active
- CMS: `ada-cms-pages/nest-tony-omen` refreshes ~15min

## Open items

- Board request pending: GNOME posture (rec: disable gdm3, keep CRD).
- kanban-brief / nest-mgr MDDB publish `RemoteDisconnected` flake on
  idc03 :11027 — worth its own card if it persists.
- Omen mem headroom (~5G avail) with scorers resident — watch.
