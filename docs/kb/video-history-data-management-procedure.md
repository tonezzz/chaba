# Video history data-management procedure

**Scope:** PDF-to-video projects, KK-Mac MLX, Colab packs, review clips, and
final cuts.

## Data classes

Every project uses one immutable project ID and separates:

```text
source:
  original PDF, source images, rights notes, source hash

plan:
  brief, story beats, shot list, prompt pack, asset manifest

derived:
  crops, embeddings, downloaded model/cache data, intermediate frames

review:
  labeled/overlay clips, contact sheets, QC reports, reviewer notes

deliverable:
  silent preview, narrated preview, subtitle files, final cut

execution:
  pack.yml, manifest, logs, usage, verifier, done/failed markers
```

## Naming and lineage

Use:

```text
<project>-<stage>-<variant>-<date>
```

Every derived artifact records:

```text
project_id
source_sha256
parent_artifact
model/revision
prompt or prompt-pack hash
seed
resolution/frame-rate
renderer commit
created_at
verdict
```

Do not overwrite a prior render. A correction creates a new variant such as
`v2`, `review`, or `final-v1`, with `supersedes` or `parent_artifact`.

## Storage tiers

```text
hot/local:
  active model cache, current render work, current QC

warm/Drive:
  manifests, source, approved review artifacts, final cuts, reports

cold/archive:
  superseded renders, old probes, reproducible intermediates
```

The durable source of truth is the project manifest plus Drive artifact path,
not a chat attachment or a temporary local directory.

## Retention rules

Never delete without explicit owner approval:

```text
original PDFs/source media
approved final cuts
project manifests and hashes
rights/QC/verdict records
```

Safe candidates for later cleanup, after checking references:

```text
failed temporary renders
duplicate downloads
unreferenced extracted frames
superseded model staging caches
```

Keep at least one review artifact and one final artifact for every promoted
variant. Keep failed artifacts until their failure is recorded and the
replacement is verified.

## Review and publication

Review variants may contain shot IDs and overlays. They must never be
published as the public final. Before final publication:

```text
remove review overlays
verify audio/subtitle streams
decode the complete MP4
check duration/frame count/loudness
record final SHA256
publish privately first
```

## KK-Mac and Colab hygiene

KK-Mac cleanup may remove only approved derived/cache data after reference
checks. Do not delete owner Desktop/Downloads/Adobe data, active Ollama
models, or incomplete LTX caches as part of routine queue work.

Colab runtimes are ephemeral. Publish artifacts before the runtime ends.
Queue manifests and Drive artifacts remain the history; local runtime files
are disposable only after the artifact gate passes.

## History review

At project close and weekly thereafter:

1. Reconcile manifest entries against Drive artifacts.
2. Identify missing, duplicate, failed, and superseded outputs.
3. Confirm every final has a QC/verdict and hash.
4. Archive reproducible superseded variants.
5. Produce a compact history index with links to source, review, and final.

Procedure card: `video-history-data-management`.
