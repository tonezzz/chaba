# Dispatch outcome — speed-probe: redeploy drifted runner-agent (attempt 3)

Date: 2026-11-24 ~08:05 +07 · Host: tony-macbook · Branch: dispatch/20261124-075921-redeploy-the-drifted-runner-ag

## Task

Redeploy the drifted runner-agent script on idc03, tony-macbook, idc02, tony-dell by
copying `scripts/board/runner-agent.py` from each host's chaba exec checkout
(`~/CascadeProjects/chaba`) to `~/.local/bin/runner-agent`, and verify each host
runs it without drift errors.

## What was found

**No live drift remained — the fleet had already self-healed.** Verified before
touching anything (per KNOWN_PITFALLS: check sha256 of BOTH paths first):

| host | installed `~/.local/bin/runner-agent` | exec-checkout `scripts/board/runner-agent.py` | origin/master blob | verdict |
|---|---|---|---|---|
| idc03 | 33a65f61… | 33a65f61… | 33a65f61… (b58f75984e) | MATCH |
| idc02 | 33a65f61… | 33a65f61… | 33a65f61… | MATCH |
| tony-dell | 33a65f61… | 33a65f61… | 33a65f61… | MATCH |
| tony-macbook | 33a65f61… | 33a65f61… | 33a65f61… | MATCH |
| mn01 (bonus) | 33a65f61… | 33a65f61… | — | MATCH |
| tony-omen (bonus) | 33a65f61… | 33a65f61… | — | MATCH |

sha256 `33a65f615c887eaec5321d1534154079b3b87a3c361859c1b428829a1f6f98f8`,
205985 bytes, last repo commit touching the file: `b58f75984e`
("runner-agent: GC stale dispatch worktree at lane start (OPS-1039)").

The tony-dell drift deferral at 2026-11-24 00:13 was transient: the installed
snapshot and checkout re-converged before this run (self-update path
`_self_update()` at runner-agent.py:4436, plus tony-dell's nightly
`runner-agent-converge.timer` — a checksum-gated ansible redeploy).

## What was done

Re-asserted the deploy anyway (idempotent, matches the spec literally):

```
install -m 0755 ~/CascadeProjects/chaba/scripts/board/runner-agent.py ~/.local/bin/runner-agent
```

run on idc03, idc02, tony-dell (via ssh) and locally on tony-macbook. Post-install
sha256 + `ls -l` confirmed `-rwxr-xr-x tony tony 205985` and identical hashes on
all four hosts.

## Verification (post-install, journals since 08:01 +07)

- **tony-macbook**: `runner-agent.service` Finished 08:02:16 cleanly; the local
  runner claimed THIS task at 07:59:44 — runs current code. 0 drift/traceback in
  24h journal.
- **idc02**: Finished 08:02:16; claimed + started two cards at 08:01:03
  (`fix-phantom-state…`, `live-voice-burn-context-replay`). Now at cap 3/3.
  0 drift.
- **tony-dell**: Finished 08:02:07; claimed `kk-ha-degraded-mode-explain…` at
  08:00:32. Has `runner-agent-converge.timer` (nightly checksum-gated ansible
  redeploy) — likely what healed the 00:13 drift flag. 0 drift in 24h.
- **idc03**: Finished every ~1min through 08:02:14; claim pass skipped on
  `disk headroom ~1.4GB < 2048MB floor` — pre-existing disk pressure, NOT drift.
  Worth a separate cleanup card if not already tracked.

Non-issues seen in journals: `claim POST failed: attempt cap reached` and
`waiting-cards warn — no explicit action.target_host/host` are normal
queue-cap/noise messages, unrelated to drift.

## Root cause of recurring drift flags

Drift is measured as installed-snapshot vs exec-checkout BYTES
(`_self_stale_check`, runner-agent.py:1665). It flaps whenever
`chaba-repo-sync.timer` pulls a newer `runner-agent.py` into the checkout and the
next runner tick hasn't yet run `_self_update()` (or self-update's mtime/compile
guard declines). Each flap emits a card deferral until the next ~1min tick heals
it. This card will keep re-firing on every runner-agent.py change unless the
check tolerates the self-update window or sync-runner-tools converges faster.

## How to verify

```
for h in idc03 idc02 tony-dell; do ssh $h 'sha256sum ~/.local/bin/runner-agent ~/CascadeProjects/chaba/scripts/board/runner-agent.py'; done
sha256sum ~/.local/bin/runner-agent ~/CascadeProjects/chaba/scripts/board/runner-agent.py   # tony-macbook
journalctl --user -u runner-agent.service --since "1 hour ago" | grep -i drift   # expect 0 on each host
```

Expected sha256 everywhere: `33a65f615c887eaec5321d1534154079b3b87a3c361859c1b428829a1f6f98f8`.

## Deliverables

- This outcome file (committed on the dispatch branch).
- Card comms on `speed-probe` with the verification table.

lessons:
- Drift flags flap transiently: chaba-repo-sync updates the checkout copy, and until the next runner-agent.timer tick runs _self_update() the byte-compare in _self_stale_check reports drift. Always sha256 BOTH ~/.local/bin/runner-agent AND ~/CascadeProjects/chaba/scripts/board/runner-agent.py before redeploying — the fleet usually self-heals within ~1min.
- tony-dell has runner-agent-converge.timer (nightly checksum-gated ansible redeploy) — it is the fleet's drift safety net; other hosts rely on _self_update() + sync-runner-tools.sh only.
- "attempt cap reached" / "waiting-cards warn — no explicit action.target_host/host" journal lines are normal queue noise, not drift or failure.
- idc03 runner-agent skips claims on disk headroom (<2048MB floor, ~1.4GB free) — unrelated to drift but will starve claims until disk is cleaned.
- Merge-sweep "verified gate" requires at least one commit on the dispatch branch — commit the dispatch-outcome file even for pure-ops tasks with no repo diff, or the attempt fails as "no delivered work".
