# Media store standard — hybrid archive layer (media_store.py)

**Status:** implemented (card `media-hybrid-object-store`, MED-0692)
**Helper:** `scripts/lib/media_store.py` — import or CLI, stdlib only.
**Applies to:** every durable archive write — renders, LINE media
archive, cam captures, WP uploads, backups.

## 1. The model — hybrid, not migration

Local hosts keep **hot/working data** (Ada render scratch, DBs, secrets,
repos — apps need disk speed). The object store is the **durable archive
+ link layer** on top. A producer writes bytes through the helper and
stores the returned canonical URL; which backend actually holds the
bytes is config, not code — `local` today, `r2` when the bucket exists,
`s3` if we ever outgrow R2. Records written today keep resolving after
the flip because they never contain a host path.

## 2. The three rules (from the card spec)

1. **One helper.** All writers go through `media_store.py`. No
   hand-rolled PUTs, no per-producer upload code.
2. **Canonical URLs in records.** Store `rec["url"]`
   (`media://<key>`) — never `/home/...`, never a backend-specific URL.
   `media://` resolves on any host through whatever backend is
   configured there. `rec["public_url"]` (present when
   `MEDIA_STORE_PUBLIC_BASE` is set) is the human/edge link — fine to
   store alongside, never instead of.
3. **Layout `media/<kind>/<yyyy-mm>/<name>`.** `kind` is the media
   family (`render`, `line`, `cam`, `wp`, `backup`, …); month buckets
   keep listings cheap and retention sweeps a prefix-delete.

## 3. Writer usage

```python
import sys; sys.path.insert(0, "<repo>/scripts")
from lib.media_store import MediaStore

store = MediaStore()                       # backend from env — no args
rec = store.put("cam", "/tmp/gate.jpg")    # or bytes / file object
# rec: url (media://...), key, backend, size, sha256, content_type,
#      public_url (when configured), skipped (idempotent hit)
manifest.write(rec["url"])                 # this goes in the record

store.get(rec["url"])                      # bytes, any host, any backend
store.stat(rec["url"]); store.delete(rec["url"])
store.list(kind="cam", month="2026-10")
```

CLI (same env resolution):

```bash
scripts/lib/media_store.py put frame.jpg --kind cam
scripts/lib/media_store.py ls --kind cam --month 2026-10
scripts/lib/media_store.py get media://media/cam/2026-10/gate.jpg -o g.jpg
scripts/lib/media_store.py doctor     # config + reachability, no secrets
```

Dedup/overwrite semantics: same content → idempotent skip
(`rec["skipped"]`); same name + different content → `-<sha8>` suffix so
the archive never silently clobbers; `unique=False` / `--overwrite` for
"latest"-style keys.

## 4. Config — `~/.config/secrets/media-store.env`

Parsed, never sourced; env vars win over file; `MEDIA_STORE_ENV`
overrides the path. Ship the file per host via the secrets convention —
**not** the repo.

```ini
MEDIA_STORE_BACKEND=local            # local | r2 | s3
MEDIA_STORE_LOCAL_ROOT=~/.local/share/media-store   # local only

MEDIA_STORE_BUCKET=media             # r2/s3 only — required
MEDIA_STORE_ENDPOINT=https://<acct>.r2.cloudflarestorage.com
                                     # r2: auto-derived from account id
MEDIA_STORE_ACCOUNT_ID=...           # or R2_ACCOUNT_ID / CF_API_ACCOUNT_ID
MEDIA_STORE_ACCESS_KEY_ID=...
MEDIA_STORE_SECRET_ACCESS_KEY=...
MEDIA_STORE_REGION=auto              # r2 default; us-east-1 for s3
MEDIA_STORE_PREFIX=media             # key prefix (rarely changed)
MEDIA_STORE_PUBLIC_BASE=https://media.<domain>   # optional edge base
```

`backend=local` is the default — every host works with zero cloud creds,
and `media://` records written under `local` stay valid; when a host
flips to `r2`, its *new* writes go to the bucket while old local
`media://` keys keep resolving from the local root. (Cross-backend
pinning — fetching a `media://` key on a host that lacks the object —
is a sync/seeding concern, not a record-format concern.)

## 5. R2 cutover checklist (when Tony creates the bucket)

- [ ] Create R2 bucket `media`; API token (Object Read & Write) →
      `media-store.env` on each writing host (`MEDIA_STORE_BACKEND=r2`,
      keys, account id). `CF_API_ACCOUNT_ID` in `cloudflare.env` is
      already honored for the endpoint derivation.
- [ ] `media_store.py doctor` on each host → bucket reachable.
- [ ] Optional: attach a public/dev domain → set
      `MEDIA_STORE_PUBLIC_BASE` so `public_url` appears in records.
- [ ] Backfill (if wanted): `put()` each existing archive file with the
      original mtime as `when` — keys land in the right month bucket.

## 6. Adoption map — who writes through this

| Producer | Bytes | kind | Status |
|---|---|---|---|
| ada-line-relay | `~/.local/share/ada/line-media/**` | `line` | helper ready — relay call-site card needed |
| cam-snapshot-wp / go2rtc | cam frames | `cam` | today → WP media; archive copy via helper |
| Ada render pipeline | renders (image/video) | `render` | card needed |
| WP uploads bridge | site media | `wp` | card needed |
| backup-manager.sh | config/db archives | `backup` | card needed |

The helper is deliberately delivered ahead of the call-site rewires —
each producer migration is its own card so the flag flip stays small.

## 7. Constraints / non-goals

- PUT bodies are held in memory (v1) — fine for archive-scale objects;
  multipart is the lever if renders go multi-GB.
- Not a CDN, not a cache tier: hot/working data stays on local disk by
  design.
- SigV4 is in-process (no boto3) — pinned to the AWS docs vector in
  `tests/test_media_store.py`.
