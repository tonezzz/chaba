# Dispatch outcome — shorten-the-thai-narration-lin (3rd re-queue)

Card: doc-pilot-short-film. The `spec:` field is still the stale shorten-line
text, but the queue that spawned this session was fired by Tony's
`go-v3` answer (2026-10-26 09:23: "Skip v6 polish; develop approved v3
tourist script"). Treated this session as the go-v3 execution.

## What was found

- **Literal spec already done:** shorten-line landed on master 07:10
  (`09ff83b8`, BEATS synced to v6-canonical; shot 15 =
  `ไกลออกไปคือแถบไคเปอร์ แหล่งรวมวัตถุน้ำแข็ง`). Verified again in this
  worktree — no further narration change needed; v6 cut untouched.
- **Stale-spec loop:** this is the 3rd dispatch spawned with the
  shorten-line spec after it was already merged — the answer-sweep
  re-queues the card on each new Tony answer but never refreshes `spec:`.
  Flagged on the board last run; still unfixed upstream.
- v3 script was not in the repo or post 2157 — only on
  `gdrive:ada-nest/doc-pilot/review/script-v3-tourist-review.yml`.
  Fetched via the host's `gdrive:` rclone remote (read-only).

## What changed

- New pack `scripts/colab/packs/doc-vo-v3/` — v3 VO generation pack:
  - `pack.yml` mirrors doc-vo-ss1 (VYNCX v2, tony-ref-8s, gpu_gb 3) with
    the 18 approved v3 Thai beats embedded; adds the non-finite-sample
    guard ss1 lacked (NaN peaks on shots 4/8 previously passed the
    `<0.01` check).
  - `inputs/script-v3-tourist.yml` — the approved script copied verbatim
    from gdrive, `status:` flipped to `approved-scope-2026-10-26` with
    provenance comment (approve-proposed-scope + go-v3 answers).
  - `inputs/tony-ref-8s.wav` + `ref_text_tony.txt` — same narrator ref
    as doc-vo-ss1 (self-contained pack, no cross-pack fetch).
- **Staged to the nest queue:** `nest-pack-submit.py` pushed it to
  `gdrive:ada-nest/packs/doc-vo-v3/` (verified with rclone lsf). Any
  capable worker (tony-omen GPU) claims it on its next pass; output
  publishes to `doc-pilot/vo-v3` — new files only, shipped v6 untouched.
- **Carded the rest of v3 production:** new kanban card
  `doc-pilot-v3-tourist-cut` (OPS-0904, backlog) carrying the full
  remaining-step spec — VO verify, storyboard v3, NASA asset/rights
  checks, renders, assembly+subs, post-2157 update. Keeps v3 work off
  the stale-spec epic card.

## Result / how to verify

- `python3 scripts/ada/nest-pack-submit.py scripts/colab/packs/doc-vo-v3 --dry-run`
  → "pack doc-vo-v3: valid".
- All 18 pack BEATS diffed equal to `script-v3-tourist.yml` shots[].th
  (assert script run during session).
- `rclone lsf gdrive:ada-nest/packs/doc-vo-v3/ -R` → pack.yml + 3 inputs.
- VO completion: watch `gdrive:ada-nest/doc-pilot/vo-v3/` for
  `v3-vo-*.wav` + vo-report.md, or `nest-queue-status.py` packs section.
- Board: card comms show this session's intent + result comments; new
  card `doc-pilot-v3-tourist-cut` in backlog.

## Notes

- Not pushed, per dispatch rules (committed on
  `dispatch/20261026-094110-shorten-the-thai-narration-lin`).
- `nest-queue-status.py` currently crashes on a missing claim dir for
  some other pack (RuntimeError: directory not found) — unrelated to
  this staging; worth a look by whoever owns that script.
- If the answer-sweep stale-spec issue keeps firing, the fix is upstream:
  refresh `spec:` (or clear `action`) when re-queueing on a new answer.
