# Nest media-pack layout

Use one storage contract for image, video, audio, document, and Gaussian
experiments. Google Drive is the durable source/artifact tier; workers hydrate
inputs into local scratch and upload verified outputs.

```text
gdrive:ada-nest/
  datasets/<asset-type>/<project-id>/<dataset-id>-vN/
    manifest.json
    source/
    references/
    derived/
    qc/
  projects/<project-id>/{brief,story,shots,assets,qc}/
  jobs/<job-id>/{job.yml,inputs,out,qc,logs,verdict.json}
  packs/<pack-id>/{pack.yml,inputs,out,qc,report.md,verdict.json}
```

Every candidate has a unique `path_id`; candidates are never overwritten.
`manifest.json` records hashes, tool versions, device, config, seed, outputs,
metrics, verifier, verdict, privacy, and retention. `scripts/nest/pack_manifest.py`
provides the storage-neutral `init`, `hash`, and `verify` operations.

Workers should use:

```text
Drive dataset -> local scratch/<job-id> -> preflight -> processing
  -> QC/verifier -> Drive out/qc -> done marker -> later scratch cleanup
```

Do not train against an rclone mount for normal jobs. Keep private media out
of Git and remove local copies only after a verified Drive round-trip.
