# doc-v2 subs report

cues: 16 (from subtitles-th-v6.srt; index==shot#)
shots without EN line in script.yml: none

## SRT files (store: doc-pilot/subs/)
- subtitles-th-v7.srt — canonical TH, v6 timings verbatim
- subtitles-en-v1.srt — EN parallel lines, same timings
- subtitles-bi-v1.srt — TH line + EN line per cue

## preview muxes (store: doc-pilot/final-v7/)
- soft-th: ok
- soft-bi: ok
- burn-th: ok
- burn-en: ok
- SKIP soft-en: e-decis/.dispatch-scratch/packtest-subs/final-v7/ss1-hybrid-v7-subs-en.mp4.
Error opening output files: Invalid argument

note: previews carry the v6 audio (VO only, no music bed).
doc-v2-delivery rebuilds the v7 master with the ducked bed
and lets you pick the subtitle track.
