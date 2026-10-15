# Dispatch outcome — cmssurface-render-digest (re-dispatch / post-merge verify)

**Card:** cmssurface-render-digest · **Runner:** idc02 · **Branch:** dispatch/20261015-155511-cherry-picked-ghost-features-f
**Result:** no new code needed — the 13:28 dispatch already built, verified, and auto-merged both components (`apps/cms-render` + `scripts/ada/line-digest.py`, merge 4e9f2db9). Tony's 15:54 answer ("dispatch") re-armed the card; this run re-verified the merged state end-to-end. No commits to master, no pushes, no deploys.

## Why a second run

The first session finished staged-for-deploy; merge-sweep held the card in review on the open request `spec-is-locked-…`. Tony answered "dispatch" at 15:54 and the runner re-claimed the card — same spec, already landed. This run is the fulfill/verify pass.

## Re-verification (this session, live MDDB @100.102.134.91:11027)

- `pytest tests/ada/test_cms_render.py tests/ada/test_line_digest.py` — **31 passed** (scratch venv /tmp/cms-verify-venv; idc02 runner has no system pytest/fastapi).
- `/healthz` — ok, collections: ada-cms-pages 642, ada-cms-pages-kk 159, chaba-docs 40, ada-cms-automation 67.
- Eyeballed: `/` index (nav-section grouped), `/p/trip-southafrica` (mermaid + superseded banner), `/p/media-inbox` (relay-img thumbs linked, not copied), `/p/house-timeline`, `/p/ada-digest`, `/p/api/health-endpoints.md` (chaba-docs path key), `/p/media-*?c=ada-cms-pages-kk` (`lang="th"` Thai UI), 404 on unknown slug.
- `/k/{trip,media-inbox,digest,report,place-report,timeline,house-rules}` all 200 (house-rules listing empty — no `house-rule*` docs exist yet; template + dispatch covered by fixtures).
- RSS: digest/report/trip/media-inbox/page `.xml` all well-formed.
- `line-digest.py --dry-run --members tony` — renders 4-bullet week digest (~300 chars): 25 devices, 14 media items, ada-digest +32, 331 cards done.

## Changed in this run

- `docs/ssot/jobs/cms/2026-10-15-cms-render-line-digest.yml` — appended the re-verification evidence line.

## Remaining before production (operator steps — unchanged)

1. idc03: `python3 -m venv ~/.venvs/cms-render && pip install -r ~/CascadeProjects/chaba/apps/cms-render/requirements.txt`; install `systemd/chaba-cms-render.service`, `systemctl --user enable --now`.
2. idc02: append `stacks/idc02/cms.surf-thailand.com.caddy` to `~/.config/caddy/Caddyfile`, `caddy reload`.
3. CF dashboard: DNS + Access policy for `cms.surf-thailand.com`.
4. Digest: one real send to Tony (`LINE_DIGEST_MEMBERS=tony`, no `--dry-run`), eyeball, then widen members + `systemctl --user enable --now ada-line-digest.timer`.
