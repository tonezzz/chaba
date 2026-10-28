# Dispatch outcome — media-hybrid-object-store (2026-10-28)

## What changed

Implemented the hybrid media store helper per the card spec (Tony's
answered request: `media_store.py` in the chaba repo for infra-wide use):

- **`scripts/lib/media_store.py`** — one write path for archive media.
  Backend is a config flag (`local|r2|s3`) via
  `~/.config/secrets/media-store.env` (parsed, not sourced; env vars
  win). `r2` is an S3 preset (region=auto, endpoint derived from account
  id — falls back to `CF_API_ACCOUNT_ID` in `cloudflare.env`). SigV4 is
  implemented in stdlib (no boto3, matching repo convention) and is
  pinned to the AWS documentation worked example in tests. Object
  layout `media/<kind>/<yyyy-mm>/<name>`; records carry a
  backend-neutral canonical `media://<key>` URL plus an optional
  `public_url` when `MEDIA_STORE_PUBLIC_BASE` is set. `put()` is
  idempotent on sha256, unique-collides with a `-<sha8>` suffix instead
  of clobbering, and supports `unique=False` overwrite for
  "latest"-style keys. Ops: put/get/stat/list/delete + `doctor`, all
  importable (`from lib.media_store import MediaStore`) and via CLI.
- **`tests/test_media_store.py`** — 25 tests: local roundtrip,
  dedup/unique/overwrite, layout+sanitization, config resolution, SigV4
  AWS doc vectors (signing key + ListUsers signature), mock-S3
  end-to-end, CLI smoke. All green.
- **`docs/kb/media-store.md`** — the standard: model (hybrid, not
  migration), the three spec rules, writer usage, config reference, R2
  cutover checklist, per-producer adoption map.
- **`docs/ssot/jobs/infrastructure/2026-10-28-media-store-hybrid.yml`** —
  trail (deliverables, design decisions, verification, follow-ups).

## Result

Helper delivered and verified. No host changes, no deploy, no secrets
in-repo. R2 creds don't exist yet on any host — `backend=local` is the
zero-dep default; the bucket cutover is a config flip per runbook §5.

## How to verify

```
python3 tests/test_media_store.py            # 25 tests, all OK
python3 scripts/lib/media_store.py doctor    # config + reachability
python3 -m py_compile scripts/lib/media_store.py
```

## Follow-ups (not blocking)

- Tony creates the R2 bucket + token → `media-store.env` on writing
  hosts, `MEDIA_STORE_BACKEND=r2` (checklist in runbook §5).
- Per-producer adoption cards: ada-line-relay (kind=line), cam frames
  (cam), Ada renders (render), WP uploads (wp), backup-manager (backup).
