# yt-vtt-dub QC gate

`yt-vtt-dub.py` gains `--qc` / `--qc-only` / `--qc-report`. The gate runs on
the final spoken cue list (post rolling-caption dedup, sentence
groups, `--th-file`, `--fix-map`) immediately before the compress/TTS
passes. Five checks per cue:

| check | rule |
|---|---|
| `cps-high`/`cps-low` | chars/sec vs the cue's OWN caption span (real VTT duration, or the group's karaoke word span — NOT the fit window; turn splits leave ~0.2s fit windows under real speech). th 2-30 ch/s, en 3-36 ch/s (~2x natural = unspeakable). |
| `thin` | text covering <12% of a >=5s span with <=12 chars — a dedup/truncated-translation fragment. |
| `residue` | >=60% prefix shared with the previous kept cue (>=8 chars) — rolling-caption tail the dedup couldn't strip (dedup only removes a prefix that is an exact suffix of the running text; a trailing difference defeats it). |
| `untranslated` | TH cue that is pure Latin (>=2 words) or Latin-dominant (>=3 Latin words AND more Latin than Thai chars) — a missed translation. Proper names alone don't flag. Note: a merged-subs cue whose TH line is 100% English never reaches the gate — parse_vtt drops it pre-dedup, which is already safe quarantine. |
| `markers` | raw speaker markers (>>, leading >) or bracketed stage directions [applause]/[laughter]/etc that edge-tts would read aloud. |

Gate behavior: flagged cues leave the synth list (voice indices are
remapped); the burn VTT is written from the group table BEFORE the
gate runs, so flagged text still shows on screen — the report is the
diff between what you hear and what you read. Report:
`<out>.qc.json` (or `--qc-report`), containing the flag list + reasons;
the same table prints to stdout. `--qc-only` scores and exits (no TTS,
no render) for caption review.

Latent bug fixed on the way: dropping a <3-char group used to shift
voice_of onto the wrong cue (group index vs filtered-cue index);
cues + voice_of now build in one index space.

## fix-map watch-list (TH mis-read dictionary)

- shared seed: `scripts/ops/yt-dub-fixmap.th.json` — applied to every
  TH render by yt-live.sh automatically.
- per-video dict: `~/.cache/yt-live-subs/fixmap/<vid>.json` on the
  cast host — merged after the seed, overrides it.
- `--fix-map` now accepts comma-separated JSON paths (merge in
  order): `--fix-map seed.th.json,VID.th.json`.
- adding an entry: hear a mis-read in a render -> reproduce it
  with a one-line edge-tts call -> pick the fix class:
  - `ZWSP` — insert a zero-width space at the true syllable break
    (โล่งอก -> โล่ง‌อก) — preferred, keeps spelling
  - `respell` — hyphen/ZWSP-respelled form (ตากลม -> ตา‌กลม) when
    the cluster boundary is ambiguous
  - `phonetic` — full respell for ทร-clusters (ทราบ -> ซาบ, ทรง -> ซง)
    and loanwords whose written form misleads the segmenter
  -> put it in the per-video dict first; promote to the seed when
  the same mis-read shows on a second video. Digit/number fixes
  are context-dependent (year vs score vs phone number) — they
  stay per-video by design.
- seeded classes (v15 note): โล่งอก (verified), ambiguous
  consonant clusters (ตากลม/ตา-กลม), ทร-clusters read /s/
  (ทราบ/ทรง/ทรมาน), loanword segmentation anchors (ออนไลน์,
  ไฮไลต์). Numbers documented as a class, not seeded — respell
  digits in the per-video dict.

yt-live.sh wires `--qc` unconditionally for voice renders and merges
seed+per-video fix-maps; dub.qc.json rides into the media cache with
dub.mp4 (clean_dir clears it on the next cast). yt-pipeline-install
ships the seed JSON into `~/.local/bin`.
