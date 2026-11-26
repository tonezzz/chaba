# Sacred Father source revision audit

Date: 2026-10-28
Project: `kk-video-c9f99fee6146`
Source decision: `OST_-_v1_01.pdf` supersedes the original; the original is preserved as v1.

## Verified inputs

| Revision | Pages | Bytes | SHA-256 |
|---|---:|---:|---|
| Original `OST_-.pdf` | 39 | 5,011,217 | `c9f99fee6146867d141a7061bdfdc71c6b15d3a617308db9420b57d67efa7cd6` |
| Current `OST_-_v1_01.pdf` | 40 | 5,821,084 | `5a6ef65431865b1b4957b70023d3e83cbdcaf19a5ebaa4896c6f2cd31ad06d34` |

The local project manifest and private Drive project manifest now point to v1_01 and retain both hashes. The private audit pack verified both source hashes against the materialized files.

## Image inventory

- Original: 15 embedded image objects extracted.
- v1_01: 17 embedded image objects extracted.
- v1_01 image objects occur on PDF pages 2, 3, 4, 5, 6, 9, 12, 15, 18, 21, 24, 27, 30, 33, 36, and 39; page 2 has two.
- The v1_01 contact sheet shows portrait/cast-reference boards on pages 2-3 and storyboard/shot collages on later pages. I did not identify any people or infer that they are family members.
- The current preview did not use these PDF images. Its visuals remain prompt-generated and derived from generated frames.
- Extracted images and private contact sheets are in Drive under `gdrive:ada-nest/packs/kk-video-c9f99fee6146-pdf-image-audit/out/`; they were not sent to LTX, Telegram as files, or a public sink.

## Text comparison

The private `pdftotext -layout -nopgbrk` diff found 12,797 normalized characters in both versions, with two added and two removed normalized lines. The differences are typographic/extraction-level; no new story event was identified. The full diff stays private at `gdrive:ada-nest/packs/kk-video-c9f99fee6146-pdf-text-diff/out/text-diff.patch`.

The separate page-fingerprint pass initially marked extraction fragments 4–38 as changed. Sequence alignment shows 13 of 14 substantial fragments match in order after a two-fragment offset; one 635-character fragment is unmatched. `pdftotext` form-feed boundaries do not reliably equal physical PDF page numbers, so these fragment numbers are not reliable page references. Review the private diff before changing the script or prompts.

## Runtime and gates

- R4 preflight passed 21 checks with zero warnings.
- The CPU-only image audit completed and landed `report.md`, `audit.json`, image lists, and extracted image files under `gdrive:ada-nest/packs/kk-video-c9f99fee6146-pdf-image-audit/out/`.
- The CPU-only text diff completed; it made no model calls and retained no separate extracted-text files.
- The preview pack was skipped because `kk-video-c9f99fee6146-source-image-use-approved` is not done. This prevents a stale render or repeated TTS retry before image/story review.
- No video shot was rerendered; no narration/provider change or public publication occurred.

## Next gates

1. Review the private extracted images and identify any specific pages approved for private visual reference.
2. Review the unmatched text fragment against v1_01; update requirements, scene plan, prompts, and embeddings if needed.
3. Only after those reviews, satisfy the source-image approval gate and selectively rerender affected shots. Edge TTS remains a separate unresolved blocker.
