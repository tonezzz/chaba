# dispatch-outcome: hands-off Colab release flow (devnest-colab-release-pinning)

## What was built

A pinned-release pipeline for the ada-nest Colab queue — no VM ever runs
unversioned or hand-uploaded code again.

**Layout (Drive):**
- `ada-nest/releases/<release_id>/` — immutable bundle built by
  `scripts/colab/publish-release.py` from `git archive origin/master`
  (working tree never read): `release.json` {schema:1, release_id, commit,
  generated_at, files{relpath:sha256}, packs+gap_packs{name:{sha256,files}}}
  + `queue/` (runner, JOBS, registry, cells, release_lib, notebook) +
  `packs/` + `gap-packs/` (code+inputs only).
- `queue/ACTIVE_RELEASE.json` — atomic pointer
  {release_id, release_sha256, commit, activated_at, previous}; flipped via
  tmp-upload + server-side moveto only after `rclone hashsum --download`
  verifies every remote artifact.
- `ada-nest/packs|gap-packs/<name>/` — now state-only workspaces
  (claim/done/failed/out); verified code is materialized into them at
  claim time, pruning dropped files, so PACK_DIR paths are unchanged.

**Enforcement:**
- Cell 1 reports `RELEASE-OK <id> commit <sha>` and validates the whole
  bundle (`RELEASE-BAD` refuses; no pointer → UNPINNED warn).
- Cell 2 refuses on pointer/hash/notebook/JOBS/runner/pack mismatch and
  spawns `releases/<id>/queue/runner.py` with NEST_RELEASE_* env;
  the runner re-verifies everything at startup including its own
  `__file__` hash — snapshot semantics (the release verified is the one
  that runs).
- done/failed markers carry `rel=` + `jh=`/`ph=`/`gh=`; a marker gates
  only while the recorded hash equals the code about to run. Pre-pinning
  markers get one rescue when workspace code is already byte-identical
  (in-place upgrade with `upgrade=legacy-ws-match`), else re-run.
- Publisher purges the legacy `queue/*.py` copies after first activation
  so unversioned paths fail loudly; mcp-colab `colab_pack_submit` refuses
  under pinning, `colab_pack_status`/`colab_session_status` report the
  release.
- Rollback = `publish-release.py --activate <release_id>` on idc02
  (re-verifies the old release remotely, repoints, redeploys notebook).
- `colab-release-publish.timer` (ssot.jobs.yml, idc02 — the host with the
  `gdrive:` remote) fires `*:7/15` behind chaba-repo-sync; no-ops when
  `scripts/colab` is unchanged since the active commit.

## Files changed

New: `scripts/colab/release_lib.py`, `scripts/colab/publish-release.py`,
`tests/colab/test_release_pinning.py`,
`systemd/generated/idc02/colab-release-publish.{service,timer}`,
`systemd/generated/idc02/chaba-jobs.{service,timer}`,
`docs/ssot/jobs/nest/2026-10-27-colab-release-pinning.yml`.

Modified: `scripts/colab/{queue-runner,gap-runner,preflight-cell,
queue-launcher-cell,queue-runner-cell,gap-launcher-cell,runtime_registry,
build-job-console}.py`, `scripts/colab/ada-nest-job-console.ipynb`,
`mcp-servers/mcp-colab/server.py`, `docs/kb/colab-mcp-jobs.md`,
`docs/ssot/infrastructure/ssot.jobs.yml`,
`tests/colab/{test_job_console,test_mcp_colab_control}.py`.

## Verification

- `python3 -m unittest discover -s tests/colab -t .` — **69 tests OK**:
  manifest/verify (missing/mismatch/extra), hash-aware markers + legacy
  rescue, materialize+prune, launcher gate (unpinned/tamper/notebook
  refuse, verified spawn), preflight RELEASE-OK/BAD, pinned runner E2E
  drain, publisher dry-run + full publish + rollback on a local remote.
- **Real Drive E2E** (idc02, throwaway remote `gdrive:ada-nest-release-
  e2e-test`, purged after): publish uploaded 60 files/27 packs/1 gap-pack,
  remote sha256 verify clean, atomic pointer flip, notebook deploy
  hash-verified; `--verify`, `--list`, `--activate` exercised. Found +
  fixed: gdrive has no sha256 metadata → hashsum needs `--download`.
- `render-jobs.py --check`: OK 88 jobs/8 hosts.

## Not done (needs merge + operator)

- **Live fresh-T4 verification** — blocked: the bundle builds from
  origin/master, which doesn't have this code until merge, and MCP can't
  push cells to a running notebook headless. Procedure documented in
  `docs/kb/colab-mcp-jobs.md` §Pinned releases: after merge, the idc02
  timer publishes → fresh T4 → cell 1 `RELEASE-OK` → queue start →
  `runner.id.release` set → markers gain `rel=`/`ph=`.
- The timer unit installs on idc02 on the next unit-install pass (it's
  rendered into `systemd/generated/idc02/`).
