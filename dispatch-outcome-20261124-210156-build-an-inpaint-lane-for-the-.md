# Dispatch outcome — adobe-stock-inpaint-defect-repair (attempt 2, 2026-11-24)

Card: `adobe-stock-inpaint-defect-repair` (OPS-1109), runner tony-omen,
worktree `dispatch-wt-20261124-210156-build-an-inpaint-lane-for-the-`,
branch `dispatch/20261124-210156-build-an-inpaint-lane-for-the-`.

## Root cause of the prior failure (fixed this run)

The 2026-11-09 session finished the work but its branch could not push:
GitHub push protection (GH013) rejected the ref because the session-end
checkpoint committed `tmp/inpaint-lane/cloudflare.env` — live
`CF_API_ACCOUNT_ID` / `CF_API_TOKEN` / `CF_API_WORKER_TOKEN` values —
alongside scratch PNGs. Merge-sweep's landing of the relayed bundle hit
the same wall, and the card sat in verify-hold until Tony re-queued it.

The bundle itself (`adobe-stock-inpaint-defect-repair-970e5903b4.bundle`)
was still intact in idc03 `~/.local/share/devin-dispatch/patch-inbox/`.

## What changed

- Recovered the bundle, cherry-picked the three clean commits onto this
  branch (rebased onto origin/master, 4 commits total):
  - `inpaint-mask.py` — box/polygon → feathered mask PNG (white=regen)
  - `omen-inpaint.py` — ssh driver: scp → sd-cli masked denoise on
    tony-omen → scp back → land via `--lane local-file`
  - `land-render.py` — `--lane local-file` + **cf-inpaint u8-array fix**
    (image/mask = arrays of file bytes, not b64; verified live 2026-11-09)
  - `docs/ssot/jobs/nest/2026-11-08-adobe-stock-inpaint-lane.yml` —
    runbook with the FINAL lane comparison
  - `tests/adobe-stock/test_inpaint_lane.py` — 4 tests, all pass
  - prior session's dispatch-outcome doc preserved as history
- Extracted the checkpoint's non-secret tooling: `paste_patch.py` →
  `scripts/adobe-stock/inpaint-composite.py` (paste patch back inside
  the feathered mask — the required composite step for cf-inpaint's
  512² output and sd-cli full-frame denoise). Runbook updated to name it.
- `.gitignore`: added `*.env` and `/tmp/` — the exact leak vector
  (`cloudflare.env` was not covered by the bare `.env` rule).
- Lesson repair: the final lane evaluation had been filed under a
  space-separated topic slug, creating a duplicate
  (`lesson-a20f0c2294e2`). Re-filed the v3 content under the canonical
  card-named slug `compositional-image-generation-layers-inpainting`
  (upserted `lesson-a2b76aec5181` in place, next_review 2026-12-01) and
  marked the space-slug page superseded.
- Moved the secret-bearing bundle on idc03 to
  `patch-inbox/handled/` — out of merge-sweep's glob path so it can't
  re-fail GH013; retained for audit. Local scratch copy deleted.

## Deliverable status (verified, not just claimed)

- Lane comparison: runbook yml `lanes:` + `processing:` sections AND the
  "Inpaint lane evaluation — FINAL" block in the campaign
  `40-qc-review.md` on `gdrive:ada-nest/adobe-stock/campaigns/
  AS-2026-11-05-REMOTE-WORK-001/` (confirmed via rclone cat).
- Repaired candidates on gdrive `30-candidates/`: confirmed present —
  `comparison-e-omen-sdxl-inpaint-wheels` (winner, sha 1e9d1ade),
  `comparison-e-cf-inpaint-wheels` (sha 90c09847),
  `comparison-e-gemini-fix4-wheels` (control, sha 0dc1094c).
- Winner: omen sd-cli sdxl-lightning full-frame masked denoise +
  feathered-mask composite. cf-inpaint = fast/cheap but 512²-soft.
  flux-fill-local + kk-mac diffusers remain host-blocked (documented).
- Remaining gate is unchanged and is Tony's: visual QC of the wheels
  region across the landed candidates.

## How to verify

- `python3 -m pytest tests/adobe-stock/test_inpaint_lane.py` → 4 passed
- `git log --oneline origin/master..HEAD` → 4 commits
- `rclone lsf gdrive:ada-nest/adobe-stock/campaigns/AS-2026-11-05-REMOTE-WORK-001/30-candidates/ | grep inpaint`
- Lesson: `POST /lesson {"op":"get","slug":"lesson-a2b76aec5181","source":"mddb"}`

lessons:
- Dispatch session-end checkpoint commits ALL untracked leftovers — a scratch `cloudflare.env` under `tmp/` got committed and tripped GitHub push protection (GH013), silently killing the merge for 2 weeks. `.gitignore` now covers `*.env` + `/tmp/`; keep secrets in `~/.config/secrets/` only.
- patch-relay bundles in `$DISPATCH_DIR/patch-inbox/<cid>-*.bundle` are retried by merge-sweep's `inbox_relay` — a bundle that can never pass push protection should be moved to `patch-inbox/handled/` once its content is landed elsewhere.
- lesson-add.py upserts by topic slug derived from the `--topic` string — "compositional image generation..." (spaces) and "compositional-image-generation-..." (dashes) produced two different lesson pages. Keep topic strings byte-identical to the card spec.
- The bundle's prerequisite commit must exist locally before `git fetch <bundle>` works — fetch inside the worktree repo (which shares history) rather than a scratch repo.
