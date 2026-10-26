# Dispatch outcome — shorten-the-thai-narration-lin

Card: doc-pilot-short-film (request `kuiper-shot15-pacing-v5`, Tony answer: `shorten-line` — shorten the Thai narration to fit one ~4s shot).

## What was found

- The in-repo narration source is `scripts/colab/packs/doc-vo-ss1/pack.yml` (`BEATS` list); the canonical `script.yml` lives on gdrive:ada-nest/doc-pilot/ and is mirrored in private Education post 2157 (lesson CPT, fetched via board-api `/lesson` `op=get`).
- The repo's BEATS still carried the v0 lines — including the NASA-flagged "millions of dwarf planets" wording for shot 15. The v6 hybrid cut (already produced in a sibling session, `ss1-hybrid-v6`/69.165s) uses the fact-checked script with shot 15 revoiced shorter: `ไกลออกไปคือแถบไคเปอร์ แหล่งรวมวัตถุน้ำแข็ง` (3.51s VO; end-frame hold cut 3.56s → 0.47s).

## What changed

`scripts/colab/packs/doc-vo-ss1/pack.yml` — BEATS synced to the v6-canonical 18-line script:

- shot 6: → `ดาวศุกร์ ร้อนที่สุดในระบบสุริยะ ใต้เมฆกรดซัลฟิวริกหนาทึบ`
- shot 7: → `โลกคือที่เดียวในระบบสุริยะที่เราพบสิ่งมีชีวิต`
- shot 15: → `ไกลออกไปคือแถบไคเปอร์ แหล่งรวมวัตถุน้ำแข็ง` (the shorten-line change)
- header comments updated to mark the lines as v6-canonical with provenance.

No cut/render/assembly changes — "keep the cut": v6 already ships these words; this commit makes the repo's only narration copy match it.

## Result / how to verify

- All 18 BEATS diffed line-by-line against the post-2157 Thai script table: exact match (script asserts `beats == canonical`).
- `yaml.safe_load` on the pack passes.
- Verify: `git show <sha> -- scripts/colab/packs/doc-vo-ss1/pack.yml`, or compare BEATS to the "บทภาษาไทย 18 ช็อต" table in Education post 2157.

## Notes

- The v4–v6 pipeline scripts (vo-repair/assemble-v2/align-v3, hybrid layers) were produced in Omen/dell worktrees and on gdrive — they were never committed to this repo, so the pack BEATS is the only narration text that could be committed here. If a future dispatch should commit the pipeline scripts too, that is a separate card.
- Committed on branch `dispatch/20261026-070638-shorten-the-thai-narration-lin`; not pushed, per dispatch rules.
