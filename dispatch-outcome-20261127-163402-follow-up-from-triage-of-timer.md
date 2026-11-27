# Dispatch outcome — mddb-idc03-oom-coldstart-publisher-window

Card: `mddb-idc03-oom-coldstart-publisher-window` (doing → awaiting Tony on host changes)
Date: 2026-11-27 · Runner: con01 · Repo: chaba (worktree only; no push, no deploy)

## What was found (read-only diagnosis on idc03)

**OOM cause (done-condition a):** system-wide memory exhaustion, not a
cgroup limit and not an mddb leak per se. `journalctl -k` shows 19 global
OOM kills on 2026-11-27 (`constraint=NONE, global_oom`): ~10× mddbd
(anon-rss ~2.8–4.0GB at kill) and ~9× node processes (~2.9–3.8GB; one
scope resolved to **yomi-api**, killed 4×). Swap is 4Gi/4Gi full; box is
15Gi/4core. Kills accelerated through the day (11:03 → 16:54 ICT).

Proximate config drift on `mddb.service`: two stale drop-ins
(`~/.config/systemd/user/mddb.service.d/memory.conf` + `mem.conf`,
Ansible-generated 2026-11-26 from the now-retired `quadlet_services`
inventory) override the quadlet to `GOMEMLIMIT=12000MiB`,
`MemoryHigh=24G`/`MemoryMax=28G` — cgroup bounds that can never trigger
on 15Gi — and re-impose `gemini-ollama-proxy@11435` over the quadlet's
`ollama/bge-m3@11436`. Same stale-redeploy pattern as the embed-probe
incident. `mddb-cms`/`mddb-ops` have no cgroup bound at all (cms peaked
7.1G RSS); `mddb-cms` also lacks `MDDB_HTTP_WRITE_TIMEOUT` (30s default)
which produced the `/v1/add` "response not delivered" →
RemoteDisconnected that failed media-inbox-update-kk.

**Cold-start window (done-condition b):** mddb-fork binds the health
listener early and serves ONLY `/health`+`/v1/health` (503
`warming_up`) until "mddb HTTP listening" — ~104s after restart; all
other routes 404. `/v1/health` is the correct readiness probe; no
server change required.

## What changed (in this worktree)

- `scripts/ada/media-inbox-update.py` — `_post()` now routes through
  `scripts/lib/mddb_http.py` (bounded transport retry, landed earlier
  today) inside a readiness gate: polls `{MDDB}/health` (200s budget >
  ~104s worst cold start), re-checks on warmup-404 or exhausted
  transport retries, then one more gated attempt. Non-404 HTTP errors
  and persistent outages still raise loudly. Publish timeout 120→130s
  (above the requested 120s server write deadline). `main()` aborts
  early with a clear error if MDDB never becomes ready.
- `tests/ada/test_media_inbox_mddb_gate.py` — 12 new unit tests for
  `_healthy`/`wait_ready`/`_post` gating (18/18 pass with the existing
  mddb_http retry tests).
- `integrations/ada-voice/scripts.ops-health-report.mddb-gate.patch` —
  same gate+retry for `ada-voice/scripts/ops-health-report.py`
  (verified `patch --dry-run` clean against ada-voice HEAD). ada-voice
  is a separate repo — apply on the tony-dell edit point, deploy via
  `deploy-ada.sh`. NOTE: con01's ada-voice checkout has unrelated
  uncommitted edits to that file (CMS-plane routing); rebase if they
  land first (details in runbook).
- `docs/ssot/jobs/mddb/2026-11-27-idc03-oom-coldstart-publisher-window.yml`
  — full runbook: evidence, config-drift inventory, options, lessons.

## Result / how to verify

- Publisher resilience (b)+(c): **done in worktree** — merges via the
  normal dispatch close-out; oneshot timers pick it up on the next
  served-checkout pull, no restart needed.
- OOM bounding (a): **diagnosed, awaiting Tony** — board request
  `approval-needed-idc03-mddb-oom-loop-9-ki-1bd95c` raised with options:
  (A) delete the two stale drop-ins [recommended — restores quadlet
  GOMEMLIMIT=8000MiB + bge-m3 route; confirm provider intent],
  (B) `MDDB_HTTP_WRITE_TIMEOUT=120s` on mddb-cms(.container)
  (precedent: mddb-ops already has it), (C) optional real cgroup
  MemoryHigh/MemoryMax on the mddb units. Structural capacity remains
  with card `idc03-structural-capacity-15gb-4core-per-2d787f`.
- Verify: `python3 -m pytest tests/ada/test_media_inbox_mddb_gate.py
  tests/ada/test_mddb_http_retry.py -x -q`; live probe
  `curl -s http://100.102.134.91:11027/v1/health` → `status:healthy`.

## Follow-ups noted (not done here)

- ~15 sibling `scripts/ada/*-update.py` still use unguarded `_post` —
  adopting the same gate is mechanical now that the pattern exists in
  two repos.
- `stacks/idc03/mddb/mddb.container` SSOT is stale vs the live quadlet
  (image 2.15.4-lsn vs 2.18.10-merge, embedding envs, missing
  FREELIST_SYNC/OUTBOUND_ALLOWLIST) — needs a sync pass once the
  embedding-route authority question is answered.
- yomi-api OOM kills (4×) suggest its own memory growth issue —
  candidate for a separate card if it recurs.

lessons:
- mddb /v1/health during startup returns 503 warming_up from the early
  listener while every other route 404s — it IS the readiness probe;
  health-port-open does not mean routes-live.
- systemd drop-ins override quadlet Environment= — check
  `systemctl --user show -p Environment` for the EFFECTIVE env; stale
  ansible drop-ins silently re-impose retired config (same failure as
  the embed-probe redeploy).
- GOMEMLIMIT bounds Go heap only; RSS can far exceed it (mddb-cms:
  2GiB limit, 7.1G peak). Hard RSS bounds need cgroup
  MemoryHigh/MemoryMax set below physical RAM.
- When a dispatch card names a file in another repo (ada-voice), the
  clean deliverable is a verified `integrations/ada-voice/*.patch`
  artifact + runbook note, not edits to a foreign checkout.
