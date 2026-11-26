# Dispatch outcome — kk-mac-video-library-rerender (2026-11-24)

## What was done

**Inventory + classification** — full job record at
`docs/ssot/jobs/devnest/2026-11-24-kk-mac-video-library-rerender.yml`.
Key correction vs card text: `/home/tony/ada-nest-videos` does not exist
on any live host — the archive lives at
`tony-dell:~/CascadeProjects/tony-chaba-dell/archive/ada-nest-videos/`.
ViMax working dirs also exist on `kk-mac:adanest:~/ViMax/.working_dir/`
(`idea2video-local` = Golden Hour Catch == vimax-run3-scene0 source;
`idea2video-real` = Evening's Catch/Peng, 4 descs, 0 videos).

Classified: reproducible = colab-scene0 (4 embeds), colab-scene1 (3
embeds), vimax-run3-scene0 (prompts verbatim, old lane was **t2v** not
i2v — `vimax_gen_video.py` never conditioned on first_frame),
kk-video-c9f99fee6146 (Sacred Father), doc-pilot (18 shots); partial =
vimax-real-run-interrupted, colab-i2v, ltx-test001; final-only =
golden-hour-catch teaser/reference, wp-embeds, ltx-embeds raw, ViMax
omen working dirs.

**Control pack queued (one at a time, concurrency=1)** —
`kk-mac-mlx-colab-scene0-control-20261124` on
`gdrive:ada-nest/kk-mac-video-pilot/packs/`: 4 shots, t2v, same T5
prompt embeds as the 2026-10-22 CUDA renders (bit-identical
conditioning), 640x384/49f/24fps/steps=8/seed=42, LTX-Video
0.9.8-distilled 2B via baisampayans/ltx-mlx. Old outputs untouched.

**Gated launcher armed on kk-mac** — `~/kk-video/run-mlx-control-gated.sh`
in tmux session `mlx-control` (12h budget, 120s polls, Drive heartbeat
every ~10min). Gates: HID idle >=600s, AC power, mem free >=40%, no
llama-server >10GB RSS, load1 <8, no creative/video apps, disk >=5GB.
The pack's own `prep:` re-checks the same gates at claim time
(defense in depth). Status at session end: **waiting — owner active
(HID idle 0s), gate working as designed**. When green it runs
`nest-worker.py --once` which claims, renders, writes done marker and
syncs `out/` artifacts back to Drive.

**Follow-on packs authored repo-side, NOT queued** (spec: no
full-library enqueue before control passes + KK review):
- `scripts/devnest/video-packs/kk-mac-mlx-colab-scene1-20261124/` —
  3 shots, same embed-injection pattern; stage instructions + embed
  sha256s in `inputs/provenance.json`.
- `scripts/devnest/video-packs/kk-mac-mlx-vimax-goldenhour-s0-20261124/` —
  the true prompt-adherence control: verbatim ViMax prompts
  (motion_desc+audio_desc), t2v, 768x512/49f, real T5 path (heavier
  gates: mem >=45%).

**Tools** — `scripts/devnest/kk_mac_video_compare.py`: old-vs-new MP4
comparator (ffprobe geometry, SSIM/PSNR, blackdetect/freezedetect,
contact strip). Verified: identical files -> SSIM 1.0 / PSNR inf.
`scripts/devnest/kk_mac_video_batch.py` patched with `num_steps` arg to
match the deployed kk-mac version.

## Result / state

- Inventory: done, verified against live hosts + Drive.
- Control: queued + gated launcher armed; render pending owner idle.
- Comparison: tool ready; runs when `out/*-mlx.mp4` lands on Drive.
- MPS lane: untouched, comparison-only per spec.

## How to verify / next steps

1. `ssh kk-mac 'tail ~/kk-video/logs/mlx-control-gated.log'` — gate polls.
2. When green: `gdrive:ada-nest/kk-mac-video-pilot/packs/kk-mac-mlx-colab-scene0-control-20261124/{done,out/}` appears.
3. Compare: `python3 scripts/devnest/kk_mac_video_compare.py old.mp4 new.mp4 -o strip.png` per shot vs `gdrive:ada-nest/renders/ltx_shot{0..3}_colab_20261022-1151.mp4`.
4. Post strips + verdict to the card; request KK quality review before staging scene1/vimax packs.
5. Stop launcher anytime: `ssh kk-mac 'tmux kill-session -t mlx-control'`.

lessons:
- `/home/tony/ada-nest-videos` in card text is stale — real archive is `tony-dell:~/CascadeProjects/tony-chaba-dell/archive/ada-nest-videos/`; ViMax runs also live on `kk-mac:adanest:~/ViMax/.working_dir/`.
- ViMax "video.mp4" shots were **t2v** (vimax_gen_video.py had no image arg) — first_frame.png was storyboard-only; don't assume i2v when replaying ViMax projects.
- ViMax prompt contract = `motion_desc + "\n" + audio_desc` (script2video_pipeline.py:527) — verbatim-recoverable, better control than embed-only projects.
- nest-worker `--once` claims ALL pending packs serially — stage follow-on packs only after the control finishes, never pre-stage on the queue.
- kk-mac HID idle gate is the real bottleneck on owner machines — launcher must poll cheap local gates and only invoke the worker when green (Drive heartbeat for observability).
