# dispatch-outcome: ada-flood-news.service exit 2 on idc02 — FIXED

## Root cause

Not a CLI arg problem — an environment problem. The fetch phase always
succeeded; the failure was the CMS publish step. Journal ordering was
misleading: `== <page>: error <urlopen error [Errno 111] Connection
refused>` lines are stderr (unbuffered) while item listings are stdout
(block-buffered, flushed at exit), so errors printed before the fetch
output.

The refused connection was MDDB. idc02's `~/CascadeProjects/chaba`
checkout is ~1379 commits behind origin/master (and dirty), so its
`scripts/ada/flood-news-update.py` still defaults `MDDB_BASE_URL` to
`http://100.74.146.0:11023` — idc01, which has not served MDDB since
the leader moved to idc03 (`100.102.134.91`) on 2026-10-05/06. The
in-repo script already defaults to idc03; only the deployed copy was
stale. Writes must go to the leader — idc02's own `mddb.service` is a
read-only follower.

## Changes (in this worktree)

- `docs/ssot/infrastructure/ssot.jobs.yml` — job `ada-flood-news` gains
  `env: {MDDB_BASE_URL: http://100.102.134.91:11023/v1}` (idc03 leader —
  same pin log-shipper already uses) + note update.
- `systemd/generated/idc02/ada-flood-news.service` — re-rendered via
  `scripts/render-jobs.py`; gains `Environment="MDDB_BASE_URL=..."`.
- `docs/ssot/jobs/infrastructure/2026-10-09-ada-flood-news-mddb-env-pin.yml`
  — job record / trail.
- `ssot.audit.hosts.yml` — **unchanged**: card step 4 was stale; idc02's
  `known_failed` is already `[]`, no `ada-flood-news` entry existed.

## Deployed

Rendered unit scp'd to idc02 `~/.config/systemd/user/` + `daemon-reload`
(couldn't use `render-jobs.py --install` on-host — it would render the
stale manifest from the 1379-behind checkout).

## Verify

```
ssh idc02 'systemctl --user start ada-flood-news.service'
# RC=0, Result=success, ExecMainStatus=0
```

Journal confirms real work, not a skip: `updated
ada-cms-pages|flood-report|en (+1256c)` and `|th`; registry reachable
again (interval gating resumed for the nongdon/pattaya-rayong pages).
`render-jobs.py --check` OK 43 jobs; `ssot-validate-all.mjs` 1793 valid,
0 errors.

## Follow-up worth a card

idc02's chaba checkout being ~1379 commits behind with local
modifications affects every job exec'd from it (`chaba-kb-audit`,
`ada-flood-news`, ...). Reconciling it (git-safe-pull or re-clone) is its
own job — the env pin only heals ada-flood-news.
