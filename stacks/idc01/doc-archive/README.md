# doc-archive (idc01)

Document archiving API per `docs/kb/document-archive-service.md`: page images
in (base64, RAM-only) → sha256 + dhash → dedup against MDDB → resumable
upload to `gdrive:ada-documents/<YYYY>/<slug>/` → one metadata doc in the
MDDB `documents` collection. No page bytes ever hit idc01's disk or MDDB.

Transport is direct Drive REST (resumable PUT + `alt=media` GET) with the
OAuth refresh_token taken from the `[gdrive]` section of `rclone.conf` —
see `drive_client.py` (factored from `scripts/gdrive-archive.py`).

## Layout

| file | purpose |
|---|---|
| `drive_client.py` | Drive REST client: token refresh, find/mkdir, resumable upload, `alt=media` download, retry+backoff on 401/403/429/5xx |
| `doc_archive.py` | FastAPI app + MDDB client (stdlib urllib) + sha256/dhash dedup |
| `doc-archive.service` | systemd **user** unit (venv + uvicorn) |
| `doc-archive.container` | rootless-podman quadlet alternative (host net) |
| `Dockerfile` | image for the quadlet (`localhost/doc-archive`) |
| `deploy.sh` | copies source + unit to idc01, builds venv, enables service |
| `doc-archive.env.example` | env template → `~/.config/secrets/doc-archive.env` |
| `tests/` | pytest suite; Drive + MDDB fully mocked |

## Endpoints

All require `X-API-Key` except `GET /health*`.

- `POST /v1/archive` — `{slug, doc_type, files:[{name, data_b64}]}`
  - exact sha256 hit in MDDB → returns existing `{archive_id, folder_id,
    page_ids, dedup:"exact"}` with no re-upload
  - dhash hamming ≤ 6 (`DHASH_MAX_HAMMING`) → archives anyway, response
    carries `dedup:"near"` + `dedup_candidates[]`
  - otherwise `dedup:"none"`; always returns
    `{archive_id, folder_id, manifest_id, page_ids[], dedup, dedup_candidates[]}`
  - 409 if `ada-documents/<YYYY>/<slug>/` already exists
- `GET /v1/archive/{slug}` → `{archive_id, mddb, manifest}`
- `GET /v1/archive/{slug}/page/{n}` → streams page bytes (`n` is 1-based),
  `X-Page-Sha256` header carries the manifest hash
- `GET /health` → `{ok:true, drive:"reachable"|"unreachable"}` (unauthenticated)

Example:

```bash
curl -s http://100.74.146.0:11025/v1/archive \
  -H "X-API-Key: $KEY" -H 'Content-Type: application/json' \
  -d '{"slug":"a-68-sale","doc_type":"condo-sale","files":[
        {"name":"p1.jpg","data_b64":"'"$(base64 -w0 p1.jpg)"'"}]}'
```

## Env (`~/.config/secrets/doc-archive.env`, 0600)

| var | default | notes |
|---|---|---|
| `DOC_ARCHIVE_API_KEY` | — | required; or `DOC_ARCHIVE_API_KEYS=k1,k2` |
| `DOC_ARCHIVE_BIND` | — | `100.74.146.0` (idc01 tailnet IP) |
| `DOC_ARCHIVE_PORT` | — | `11025` |
| `RCLONE_CONF` | `~/.config/rclone/rclone.conf` | needs `[gdrive]` client_id/secret/token |
| `MDDB_BASE` | `http://100.74.146.0:11023` | |
| `MDDB_COLLECTION` | `documents` | |
| `DRIVE_ROOT` | `ada-documents` | |
| `DHASH_MAX_HAMMING` | `6` | near-dup threshold |
| `DOC_ARCHIVE_MAX_FILES` | `50` | per request |

## Deploy (review first — not yet run)

1. Copy `[gdrive]` rclone.conf creds to idc01 (design doc §4, option a).
2. `install -m600 doc-archive.env.example ~/.config/secrets/doc-archive.env`
   on idc01, edit in a real `DOC_ARCHIVE_API_KEY`.
3. `./deploy.sh` — copies source to `~/.local/share/doc-archive`, builds
   `venv`, installs/enables `doc-archive.service`, curls `/health`.
   Quadlet instead: scp `doc-archive.container` + `Dockerfile`, `podman
   build -t localhost/doc-archive`, `systemctl --user start doc-archive`.

## Tests

```bash
python3 -m venv --system-site-packages /tmp/doc-archive-venv  # or any venv
/tmp/doc-archive-venv/bin/pip install fastapi pillow pytest httpx
cd stacks/idc01/doc-archive
/tmp/doc-archive-venv/bin/python -m pytest tests/ -q
```

Covers: happy path (upload + MDDB doc + GET endpoints), exact-dup
short-circuit, near-dup candidates, auth failures, bad base64, Drive retry
on 500.
