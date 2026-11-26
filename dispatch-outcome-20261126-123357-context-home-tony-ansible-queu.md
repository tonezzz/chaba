# Dispatch outcome — gpu-timeslot-reservations (OPS-1407), attempt 2

## Why attempt 1 "failed" and what this run did

Attempt 1 did the engineering correctly — reservations implemented, deployed,
and verified live on idc02:/home/tony/ansible — but **committed nothing** to
the dispatch branch (52 files left staged in its worktree). Merge-sweep
correctly reported "no commits → not verified". This run's fix: land the
deliverable in git and re-verify.

## What changed in this worktree

- `.dispatch-scratch/ansible-mirror/` — **full refreshed snapshot** of the
  live `/home/tony/ansible` tree on idc02 (55 files, pulled via
  `sftp -o ProxyJump=tony-omen`; `.git`, `__pycache__`, runtime `audit.jsonl`
  excluded). The live tree now also contains the sibling
  gpu-dispatch-webui's `cancel_job()`/`cancel` CLI (queue_manager.py) and an
  unrelated `homeassistant-plug.yml` — the snapshot is the true current
  state, so all of it is captured. This mirror is the only versioned copy of
  the queue code (the idc02 checkout has a .git dir but all working files are
  untracked, no remote).
- `docs/ssot/jobs/infrastructure/2026-11-25-gpu-timeslot-reservations.yml` —
  attempt-1 trail + `attempt_2_landing` section (access notes, doc fixes,
  re-verification).
- `.dispatch-scratch/run-resv-test.py` — helper that runs the reservation
  test off-idc02 by pointing `scheduler.INVENTORY` at the mirror.

## Doc fixes pushed to live (idc02) as well

`containers.podman` argv-splits `command:` on whitespace with **no quote
handling** — the `bash -c "..."` job_cmd in GPU-JOBS.md Option C and
`jobs/examples/gpu-reserved-window.yaml` could never work (verified: container
inspect showed literal quotes in argv, bash exit 2). Both now use flat
`nvidia-smi dmon` commands and GPU-JOBS.md documents the limitation. Pushed
via sftp so mirror == live.

## Verification (this run)

- **Unit**: `test_gpu_reservations.py` from the mirror against idc02 Redis
  db15 via tony-dell's `~/.local/venv-sidecar` → **14/14 PASS**
  (dequeue order, hold acquire, placement refusal while held, atomic refuse,
  plain-job exclusion, release-on-complete, TTL expiry, stats.reservations).
- **Live on omen** (GTX 1650 shared with bge-rerank.service, which stayed
  `active` throughout — never stopped):
  - `gpu-rsv3-a/b` pair with `bash -c` cmds → both exit 2 (the argv-split
    bug above) — incidentally proved release-on-fail works live.
  - `gpu-rsv4-a` (`nvidia-smi dmon -s pucm -d 5 -c 30`, window 300s) acquired
    `gpu:hold:omen:0` (TTL counting down); `gpu-rsv4-b` stayed
    `status=waiting` with no retry penalty for A's full 144s run; after A
    completed (`reservation_state=released`), B dispatched, ran `nvidia-smi
    -L`, `Exited (0)`, released its own hold. End state: `holds=[]`, queue
    empty, all 4 test containers removed.
- Access path note: idc02 sshd is **sftp-only** for `tony`, and tony-dell's
  tailscale IP is refused on :22 (omen→idc02 works). File ops:
  `sftp -o ProxyJump=tony-omen tony@idc02`. Queue ops: gpu-dispatch-webui
  `POST /api/jobs` on `100.123.163.11:8795` (confirm:true) or Redis :6379.

## How to verify

```bash
# unit test (any tailnet host with redis-py; scheduler.INVENTORY patched to mirror)
cd .dispatch-scratch && ~/.local/venv-sidecar/bin/python run-resv-test.py
# live queue state
curl -s http://100.123.163.11:8795/api/state | python3 -m json.tool | head -40
ssh tony-omen 'systemctl --user is-active bge-rerank.service'
```

lessons:
- A dispatch that edits files OUTSIDE its worktree (live /home/tony/ansible on idc02) must still commit a mirror/snapshot into the worktree — uncommitted staged files = failed dispatch at merge-sweep.
- idc02 sshd is sftp-only for tony and currently refuses tony-dell's IP on :22; omen is the working jump (`sftp -o ProxyJump=tony-omen`). Queue mutations don't need ssh at all — gpu-dispatch-webui :8795 or Redis :6379.
- containers.podman `command:` argv-splits on whitespace with no quote handling — `bash -c "..."` job_cmd arrives broken (exit 2); only flat argv commands work through dispatch_job.yml.
- scheduler.INVENTORY/ANSIBLE_DIR are hardcoded to /home/tony/ansible — running queue code off-idc02 needs those module attrs patched (see .dispatch-scratch/run-resv-test.py).
