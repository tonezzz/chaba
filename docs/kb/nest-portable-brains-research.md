# Chaba Nest — Portable Brains (research program)

Status: draft, 2026-10-07. Anchor card: `docs/ssot/kanban/cards/nest-portable-brains.yml`.

## Idea

Give every Nest entity a **portable brain**: a versioned bundle of everything it
needs to resume on any node — weights, memory slice, config, checkpoint pointer.
Store brains on Google Drive (REST-visible, durable, 1.8 TB free) so any host can
fetch → hydrate → continue where the last checkpoint left off, with bounded data
loss (RPO = time since last checkpoint).

## What a "brain" is

```
brain/
  manifest.yml     # entity-id, brain-version, sha256 per blob, parent-version,
                   # created-on-host, bench-score-at-checkpoint, RPO marker
  weights/         # GGUF/ONNX/npz — the model itself
  memory/          # MDDB export slice, sqlite, or corpus delta (NOT whole banks)
  config/          # unit/flags/prompt/tool surface needed to respawn
  state/           # counters, last-processed-offset, rng seed — resume anchors
```

Brains are **append-only artifacts** — dated, immutable, CAS-addressed by sha.
`gdrive:nest/brains/<entity>/<version>/` + a `latest` pointer file (small mutable
file, or Drive `appProperties` query: `"latest brain for entity X"`).

## Why gdrive fits (and where it doesn't)

Fits: cold/warm brain tiers. Drive REST gives real metadata + md5Checksum,
queries via `appProperties`, Changes API for "newer brain exists elsewhere"
signals, ~30 MiB/s observed — fine for respawn-in-minutes SLAs.

Doesn't fit: live state. No partial-file incrementals (a changed 4 GB sqlite
re-uploads whole), FUSE mount is write-through. So: hot state stays local,
brains checkpoint on cadence — Drive is the durable cold tier, tailnet hosts
are the warm tier (fast fetch).

Same tier model as the backup offload already deployed:

```
hot:  running entity (local state)
warm: latest brain mirrored on 1-2 tailnet hosts
cold: gdrive:nest/brains/ — versioned, verified, resumable
```

## Research questions

1. **Brain boundary** — what is *just enough* to resume? (weights + memory
   slice + state anchors, not the whole disk). Measure resume-fidelity by
   bench-diff, not vibes.
2. **Checkpoint cadence** — periodic timer vs event-driven (pre-stop, on
   bench-improvement). What's the cost per GB-minute of RPO?
3. **Fencing** — two nodes respawning the same brain = split-brain.
   Manifest needs a lease/epoch; last-writer-wins is acceptable for
   single-owner entities, not for shared ones.
4. **Provenance & drift** — `appProperties: entity, version, parent, sha`.
   Drive query → "is there a newer brain than mine?" becomes a cheap
   drift/respawn signal via Changes API.
5. **Confidentiality** — brains contain memory. `rclone crypt` layer for
   sensitive entities; classify brain sensitivity at pack time.
6. **Restore SLA** — RTO = download + hydrate + healthcheck. Target:
   micro-entities (<50 MB brain) respawn in <60 s; jev-class (<1 GB)
   in <5 min.

## Phases

- **P0 — inventory + manifest schema** (this card): list candidate entities,
  define `manifest.yml`, pick first subject.
  Candidates: `nest-01-ops-classifier` (10 KB model — ideal MVP), jev-student
  checkpoints (proven recipe), orch-bench corpus, edge-vision models.
- **P1 — pack/restore tooling**: `scripts/nest-brain-{pack,restore}.sh` —
  tar+sha manifest, `rclone copyto`, verify round-trip on same host.
- **P2 — cross-host respawn proof**: ops-classifier checkpoint on tony-dell →
  restore on mn01 → run bench → scores within noise = continuity proven.
- **P3 — cadence + drift signal**: checkpoint timer per entity; poller reads
  Drive Changes/`latest` pointers → "newer brain available" events on the bus.
- **P4 — federation tie-in**: brains become the transport for FedAvg rounds
  (chaba-nest-models card) — a brain IS a model artifact + provenance.

## How it keeps moving (momentum mechanics)

- Each phase = its own kanban card, dispatchable.
- Results land in MDDB bench collection → `nest-bench`-style CMS trend page.
- Weekly `report-ai-edge.py` pattern for a `nest-brains-report` page:
  entity × last-checkpoint × RPO × last-verified-restore.
- Failure mode visibility: pack/restore failures surface in host audits like
  the mddb-standby-pull pattern (fail the unit, show in audit).

## Links

- Cards: `nest-collective-bench`, `chaba-nest-models`, `nest-edge-vision`,
  `verify-gdrive-offload-tier`
- Deployed precedent: `mddb-standby-pull.service` gdrive tier (newest-1 local,
  verified upload, fail-visible)
- Research basis: `docs/kb/tiny-models-research.md` (50 MB micro-model budget)
