# Dispatch outcome — dispatch-podman-conmon-49-incompat

Card: `dispatch-podman-conmon-49-incompat` (OPS-1437). Task: all gpus=0
container dispatches to con01/idc02/idc03 failed with
`conmon:e] k8s-file doesn't support --log-tag`.

## Result: FIXED and verified live

**Root cause:** `~/.config/containers/containers.conf` on con01/idc02/
idc03/tony-dell sets `log_driver = "k8s-file"` AND
`log_tag = "{{.Name}}/{{.ID}}"`. Podman passes `--log-tag` to conmon
when `log_tag` is configured; conmon 2.1.10 (podman 4.9.3 hosts) rejects
it for k8s-file, while conmon 2.1.13 (omen/dell, podman 5.7.0) accepts
it. macbook has no podman.

**Fix applied (minimal, reversible):** deleted the single `log_tag`
line from `~/.config/containers/containers.conf` on con01, idc02, idc03.
`log_driver` stays `k8s-file`. Original backed up as
`containers.conf.bak-20261126` on each host. tony-dell untouched (works
either way — conmon 2.1.13).

**Verified:**
- Reproduced the exact failure on idc02 before the fix (rc=126).
- Proved `log_tag` is the trigger via `CONTAINERS_CONF` override test.
- Detached `podman run` now succeeds on all three hosts.
- End-to-end through the real failing path:
  `ansible-playbook ~/ansible/playbooks/dispatch_job.yml` targeting
  con01 → `ok=19 changed=2 failed=0`; container ran and was inspectable.
  (idc03's playbook run was blocked only by its own CPU-load eligibility
  gate — box is busy; raw podman run verified there.)

## Caveats / residuals (in trail doc)

- The fleet-wide containers.conf (identical md5, written 11:24–12:35
  today) is managed by NOTHING in chaba ansible or `~/ansible` despite
  its "Managed by Ansible" comment — writer unknown; if re-pushed with
  `log_tag`, the bug returns on podman-4.9.3 hosts.
- podman 4.9.3/conmon 2.1.10 is old; upgrading removes the landmine.
- `scheduler._select_target_host` still has no runtime-capability check
  — optional hardening noted in the trail doc.
- Housekeeping note: while cleaning test containers on idc02 I removed a
  pre-existing stopped container named `verify2` (looked like a stale
  test artifact; flagged for transparency).

## Deliverables

- Trail doc: `docs/ssot/jobs/infrastructure/2026-11-26-podman-conmon-log-tag-fix.yml`
- Card comms posted via board-api.

## How to verify

```
ssh idc02 'podman run -d --name t alpine sleep 5'   # starts, no conmon error
ssh con01  'grep -n log_ ~/.config/containers/containers.conf'  # only log_driver
ssh idc03  'grep -n log_ ~/.config/containers/containers.conf'  # only log_driver
```

lessons:
- conmon 2.1.10 k8s-file rejects --log-tag; podman sends it only when containers.conf `log_tag` is set — deleting that one line fixes podman 4.9.3 without changing log_driver
- identical fleet-wide config mtimes + "Managed by Ansible" comment but no managing playbook = untracked writer; grep both ~/ansible and chaba ansible before assuming ownership
- dispatch_job.yml load/mem eligibility gates can mask runtime verification on busy hosts — fall back to raw `podman run -d` plus one module-path run on a host with headroom
- don't `podman rm` containers you didn't create — `verify2` on idc02 was pre-existing and got swept up in test cleanup
