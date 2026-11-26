# Documentary control plane (asset identity + continuity)

Card `ai-video-quality-control-plane` (OPS-0882). Extends the Ada Nest
doc-pilot pack chain — `script.yml` → VYNCX VO (`doc-vo-*`) → LTX shots
(`doc-render-*`) → `doc-assemble-*` — with deterministic identity and
continuity control. Tool: `scripts/nest/doc_control.py` (stdlib + pyyaml).
Everything is additive: existing packs, the LTX/VYNCX lanes, and durable
pack artifacts are untouched.

## Project layout

A documentary project dir (mirrors `gdrive:ada-nest/projects/<id>/`):

```text
<project>/
  assets/bibles.yml            # P1: characters/objects/locations
  shots/shot-manifest-v2.json  # P0: immutable per-shot manifest
  qc/continuity-ledger.jsonl   # P1: every render/qc/approve event
  qc/approved-takes.json       # per-stage approved-take manifest
  qc/control-verify.json       # verifier verdict
  qc/<asset_id>.qc.json        # optional per-shot video-qc results
  evals/<doc>-fixture-v1.json  # P3 benchmark fixture
```

## Stages

| Stage | What lands | Verifier |
|-------|-----------|----------|
| P0 | `shot-manifest-v2.json`: asset_id per shot (`<doc>-sNN`), continuity links (`i2v-from-shot-N` → `prev_shot`), scratch-VO timing (`est_s` + measured wav duration, overrun/underrun flags vs render slot), control slots, QC binding to `scripts/ops/video-qc.py` | `doc_control.py verify` → `manifest` check |
| P1 | `assets/bibles.yml` (`nest-doc-bibles-v1`: characters/objects/locations with facts), `qc/continuity-ledger.jsonl` (`nest-doc-continuity-v1`: rendered/qc/approved/rejected events), `controls.pose`/`controls.depth` slots (DWPose skeleton + depth map refs) | `bibles`, `ledger`, `approved-takes` checks; stage coverage reported |
| P2 | `controls.scene` (blender/stock/space/gaussian plate ref) + `controls.camera` (SCoPE trajectory / plate camera id) slots in the manifest | same verifier; coverage counters |
| P3 | `evals/<doc>-fixture-v1.json` (`nest-doc-eval-fixture-v1`): per-shot cases with verbatim prompt, negative, seed, est duration, and a scene graph (objects/characters/location/relations/facts from bibles) tagged for vbench / t2v-compbench / videoscore2 | `fixture` command; scenes grounded in manifest+bibles |

## Workflow

```bash
# P0 — after script.yml + storyboard.yml are approved
python3 scripts/nest/doc_control.py build \
  --script <project>/script.yml --storyboard <project>/storyboard.yml \
  --vo-dir <dir-of-v3-vo-*.wav> \
  --out <project>/shots/shot-manifest-v2.json

# P1 — declare asset identity once per doc
python3 scripts/nest/doc_control.py bibles <project>/assets/bibles.yml \
  --doc-id <doc>

# per take, as renders land (idempotent append-only ledger)
python3 scripts/nest/doc_control.py ledger append <project> \
  --shot 3 --asset-id <doc>-s03 --take 2 --event rendered \
  --artifact qc/shots/s03-t2.mp4
python3 scripts/nest/doc_control.py ledger append <project> \
  --shot 3 --asset-id <doc>-s03 --take 2 --event qc --qc-ok
python3 scripts/nest/doc_control.py ledger append <project> \
  --shot 3 --asset-id <doc>-s03 --take 2 --event approved

# approved-take manifest + stage gate
python3 scripts/nest/doc_control.py takes <project>
python3 scripts/nest/doc_control.py verify <project> [--require-artifacts]

# P3 — benchmark fixture once the manifest is stable
python3 scripts/nest/doc_control.py fixture <project>
```

## Verifier semantics

`verify` writes `qc/control-verify.json` and exits 1 on any `fail`:

- **manifest** — schema, contiguous shot numbers, unique asset_ids,
  non-empty prompts, VO overrun (>15% over effective slot) or underrun
  (<0.5s) flags, `prev_shot` must reference an existing earlier shot
  (i2v links can never point forward — the continuity DAG stays acyclic).
- **bibles** — `assets/bibles.yml` valid; every shot's
  object/characters/location resolves to a bible id. Absent file = warn
  (P1 not yet declared), not fail.
- **ledger** — `qc/continuity-ledger.jsonl` parses; empty/absent fails
  the approved-takes chain.
- **approved-takes** — `qc/approved-takes.json` exists; every row marked
  `approved` must have a matching `approved` ledger event for that
  (shot, take).
- **artifact-qc** (only with `--require-artifacts`) — per-shot
  `qc/<asset_id>.qc.json` produced by `scripts/ops/video-qc.py` must
  report `ok: true`.

`stage_coverage` in the verdict reports P1–P3 field fill
(`pose/depth/scene/camera/scene_graph` as `filled/total`) — informational,
never fails the gate. That is how a reviewer sees how far a doc has
progressed through the stages without a separate status file.

## Scratch-VO timing

`build --vo-dir` measures each `*vo-NN.wav` (stdlib `wave`, PCM only)
and compares it to the shot slot (`num_frames/fps`, falling back to
`est_s * 1.25` when no render spec exists). `overrun`/`underrun` are
hard manifest errors at verify time — a VO that cannot fit its shot slot
must be re-cut or the shot extended before render, not discovered at
assemble time.

## P3 fixture

`fixture` emits one case per manifest shot: verbatim prompt + negative +
seed + estimated duration + scene graph (objects, characters, location,
`continues_from`/`depicts` relations, and bible `facts` for fact-check
benchmarks). Benchmarks listed: vbench, t2v-compbench, videoscore2.
