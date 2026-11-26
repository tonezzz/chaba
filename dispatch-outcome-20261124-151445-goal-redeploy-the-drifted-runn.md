# Dispatch outcome — redeploy drifted runner-agent (2026-11-24)

Card: `persona-name-leaks-tool-result` (spec carried the runner-agent redeploy goal).

## Task

Copy `scripts/board/runner-agent.py` from the chaba repo to `~/.local/bin/runner-agent`
on tony-macbook, tony-dell, idc02, idc03 via scp; done when the installed copy matches
the repo version on all targets without drift.

## What was found / done

- Source of truth used: this worktree's `scripts/board/runner-agent.py`,
  sha256 `52cbc072f2695ad9b528884791999a4c7eb9aee667a4e733e306143e1272ce5d`.
  Worktree HEAD == `origin/master` (`493880325b`), so the deployed bytes are the
  canonical master version.
- Pre-check (sha256 of `~/.local/bin/runner-agent` AND each host's exec checkout
  `~/CascadeProjects/chaba/scripts/board/runner-agent.py`): **all four hosts were
  already converged** — the drift had self-healed via runner-agent `_self_update` /
  `chaba-repo-sync` before this dispatch ran, matching the known-pitfalls pattern.
- Ran the scp anyway per spec: `scp scripts/board/runner-agent.py <host>:.local/bin/runner-agent`
  then `chmod 755` on each host.
- Post-deploy verify on every host: `~/.local/bin/runner-agent` sha256 =
  `52cbc072f2695ad9b528884791999a4c7eb9aee667a4e733e306143e1272ce5d`, mode `-rwxr-xr-x`,
  size 225692 bytes.

## Result

PASS — installed runner-agent is byte-identical to the repo (origin/master) version on
all four target hosts: tony-macbook, tony-dell, idc02, idc03.

## Side observation (not actioned — out of scope)

- idc02 `~/CascadeProjects/chaba-tony-dell` is a legacy checkout with **no chaba-role
  stamp** still holding an older `runner-agent.py` (`adfa0c57…`). It is referenced by
  live units (gpu-queue, gpu-queue-processor, yomi-api, web-srv-sync, vps-lane.conf)
  but none execute `scripts/board/runner-agent.py` from it — `runner-agent.service`
  runs `%h/.local/bin/runner-agent`. If that checkout is meant to be retired or
  re-stamped, that is separate hygiene work.

## How to verify

```sh
for h in tony-macbook tony-dell idc02 idc03; do
  ssh "$h" 'sha256sum ~/.local/bin/runner-agent'
done
# expect 52cbc072f2695ad9b528884791999a4c7eb9aee667a4e733e306143e1272ce5d on all four
sha256sum scripts/board/runner-agent.py   # repo side, same hash
```

## lessons:

- runner-agent drift flags flap: `_self_update`/`chaba-repo-sync` often heal before a
  dispatch lands — always sha256 BOTH `~/.local/bin/runner-agent` and the exec
  checkout copy first; if already converged, still run the spec'd scp to re-assert.
- idc02 has a role-less legacy `~/CascadeProjects/chaba-tony-dell` checkout still
  mounted by gpu-queue/yomi-api/web-srv units — stale files there are harmless for
  runner-agent but a hygiene loose end worth a future card.
