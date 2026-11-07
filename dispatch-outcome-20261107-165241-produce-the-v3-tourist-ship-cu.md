# dispatch-outcome — produce the v3 tourist-ship cut (resume of 163129 session)

## Result

The v3 tourist-ship cut was **already produced** by the immediately
preceding idc02 session (devin-task-20261107-163129, which lost its
response — OPS-1071). This session verified every deliverable
independently and fixed the one thing that blocked its repo landing:
the prior branch's session-end checkpoint had swept a Python virtualenv
(`work/doc-pilot-v3/.venv/`, 1,474 files incl. symlinks) into commit
`c0472a4d8`, tripping the merge shadow-guard.

**Deliverable (unchanged, re-verified this session):**
`v3-static-final-v1.mp4` — 65.728 s, 640x384@24, H.264/AAC + mov_text
Thai subs, Drive ID `12BbrvSDURkUxzmvx6orXqJIeayXfYI6Q` at
`gdrive:ada-nest/doc-pilot/review/`. All 18 shots use rights-checked
NASA plates or deliberate schematics; zero placeholders; per-shot Thai
fact callouts, ship silhouette + cockpit-window layer, credits baked.
Report + SRT sidecar + updated asset manifest alongside; Education post
2157 updated in place (stays private).

## What this session did

1. Re-verified the cut: `ffmpeg -f null` decode clean; 18 SRT cues;
   audio peak -2.6 dB / RMS -21.7 dB; sampled frames show the correct
   ship layer, callout, credit, and subtitle layout; Drive file ID
   matches the board comment.
2. Re-verified VO: 18/18 wavs present in `doc-pilot/vo-v3/`, pack
   report `fails: none`, durations 1.91-4.52 s.
3. Landed the durable repo artifacts by cherry-picking `f7e560acb`
   (assembler `scripts/colab/packs/doc-static-final-v3/` + job note
   `docs/ssot/jobs/nest/2026-11-07-docpilot-v3-static-final.yml` + prior
   outcome file) onto this branch — **without** the poisoned `.venv`
   checkpoint commit. This branch's net additions contain no symlinks
   and no ignored-dir shadow paths, so the merge guard should pass.
4. `.gitignore`: added bare `.venv` / `venv` entries (any depth, dir or
   symlink) so a worktree virtualenv can never be checkpoint-committed
   again — the 2026-10-10 / 2026-11-07 incident class.

## Constraints honored

- Shipped v6 cut and v0/v1 script assets untouched (only 4 new files +
  .gitignore + this outcome file added).
- No push, no deploy, no default-branch commit by the agent.

## Still open (for Tony / next session)

- Card `doc-pilot-v3-tourist-cut` sits in `review` — awaits Tony/KK
  viewing + acceptance.
- LTX dynamic renders for shots 8/9 (Jupiter, Great Red Spot): static
  NASA fallbacks are in the cut; LTX needs a live GPU lane (Colab T4 or
  a clear KK-Mac window; Mac staged packs persist, owner-app gate was
  correctly holding).
- The orphaned worktree `dispatch-wt-20261107-163129-...` / branch
  `dispatch/20261107-163129-...` can be GC'd — its only unmerged content
  is the `.venv` checkpoint, which must NOT be merged.
- Per-asset public-rights pass required before any public release;
  music bed + EN subs deferred (Thai-only lane, ADA-0510).

## Verify

- `ffprobe gdrive:ada-nest/doc-pilot/review/v3-static-final-v1.mp4` →
  h264 + aac + mov_text, 65.728 s.
- Board card `doc-pilot-v3-tourist-cut` comms 2026-11-07 16:48/16:50.
- `git log origin/master..HEAD` → assembler + job note + outcome files,
  zero `work/` or `.venv` paths (`git diff --name-only origin/master..HEAD
  | grep -E 'work/|venv'` → empty).
