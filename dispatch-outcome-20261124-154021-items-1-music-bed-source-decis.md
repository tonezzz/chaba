# Dispatch outcome — doc-pilot-v2-polish-music-bed-subs-shot-943456

## What was done

Built the card's five polish items as **six nest job-packs** under
`scripts/colab/packs/`, locally tested the CPU ones against the real
fetched inputs, validated all with `nest-pack-submit.py`, and staged
them to `gdrive:ada-nest/packs/` — workers claim them when free.

| pack | item | gate | local test |
|---|---|---|---|
| doc-v2-vo-earcheck | 4 VO stutter check | none (CPU) | PASS — 18 beats, 0 flags |
| doc-v2-shot-qc | 3a shot metrics + weak list | none (CPU) | PASS — weak=[15,17,18] |
| doc-v2-rerender-shots | 3b GPU re-render weak shots | requires shot-qc; gpu_gb:14 | syntax-checked (no local GPU) |
| doc-v2-music-bed | 1 bed source + duck | none (CPU) | PASS — generated pad + sidechain duck |
| doc-v2-subs | 2 TH+EN SRT + overlays | none (CPU) | PASS — 16 cues, 3 SRTs, 5 previews |
| doc-v2-delivery | 5 v7 master + 720p + poster + CMS | requires music-bed + subs | PASS — 69.2s, 3 variants, 720p, posters |

## Key decisions

- **Store root = `gdrive:ada-nest`** (V1 doc-pilot store), not the
  doc-pilot-v2 subqueue: the card brief points at
  `ada-nest/doc-pilot/final/`, V1 has identical inputs in the flat
  `final/` layout the packs use, and only the default root is scanned
  by GPU-capable workers — doc-pilot-v2 is Omen-only (4GB GTX 1650,
  can't run gpu_gb:14).
- **Music bed = generated** ambient pad (documented licensed
  swap-in contract); ducking via ffmpeg sidechaincompress on the VO
  stem.
- **Subs** reuse the approved v6 TH timings (cue index == shot#);
  EN lines come from script.yml; bilingual variant included; soft
  mov_text + libass burn-in previews.
- **Delivery** replicates the proven 08-doc-hybrid-v6 assembly
  (NASA composites, per-scene clone-holds, same VO map) so v7
  automatically picks up re-rendered shots if rerender lands first;
  rerender deliberately NOT in `requires` so v7 never blocks on GPU.

## Where things are

- Pack sources: `scripts/colab/packs/doc-v2-*/pack.yml`
- Staged: `gdrive:ada-nest/packs/doc-v2-*/`
- Job trail: `docs/ssot/jobs/nest/2026-11-24-docpilot-v2-polish-packs.yml`
- Expected outputs (post-run): `doc-pilot/audio/`, `doc-pilot/subs/`,
  `doc-pilot/qc/{shot-qc,vo-earcheck}/`, `doc-pilot/final-v7/` masters
  + 720p + posters + `cms-destination.json`

## How to verify

- `python3 scripts/ada/nest-pack-submit.py --list` shows the six packs.
- CPU packs should show `done` markers after the next worker pass;
  `doc-v2-rerender-shots` stays queued until a ≥14GB worker claims it.
- After all done: `gdrive:ada-nest/doc-pilot/final-v7/` holds
  `ss1-master-v7-{th,en,bi}.mp4`, `ss1-master-v7-720p.mp4`,
  `poster-v7-{saturn,earth}.jpg`, `align-report-v7.md`,
  `cms-destination.json`.

lessons:
- doc-pilot has TWO Drive stores (ada-nest/doc-pilot flat `final/` vs
  ada-nest/doc-pilot-v2/doc-pilot `final-vN/` dirs) — check which root
  a pack lane uses before writing fetch paths; card briefs point at
  the V1 flat layout.
- nest-worker injects NEST_ROOT=PACK_DIR on fleet but NEST_ROOT=store
  mount on Colab — store-side writes under `{NEST_ROOT}/doc-pilot/...`
  only reach the real store on Colab; fleet needs `publish:` mapping
  (src is pack-relative, e.g. `out/audio: doc-pilot/audio`).
- `publish:` src paths are relative to the pack dir, not to out/ —
  keep run-code outputs and publish keys consistent.
- ffmpeg `-c:v copy` mov_text muxing hit one transient "Invalid
  argument" on a soft-sub variant — retry once and delete partial
  output on failure.
- Re-render packs can't reuse doc-render-ss1's >50KB cache skip —
  efficient encodes of static scenes all land under it; drive the
  shot list from a QC artifact instead.
