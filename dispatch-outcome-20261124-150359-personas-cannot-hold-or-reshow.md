# Dispatch outcome — persona-photo-store (2026-11-24)

## Task

Personas cannot hold or reshow photos: bank docs are text-only and no
tool returns a stored image URL to the relay `_image_msgs` path. Driver:
kaewta re-showing kk's car photo on request. Needed: (1) a served asset
store referenced by `meta.image_url` in bank docs, (2) a memory-search
path that surfaces the URL into tool_result images, (3) ingestion of an
in-group LINE image as a persona asset.

## What changed

All ada-voice work is staged as **drop 22** under
`integrations/ada-voice/` (drop pattern: patches + new files + README
section); chaba-side SSOT/test changes land directly. Nothing was
deployed — ada-voice merge + `deploy-ada.sh` remains the Tony gate.

**Store side — new `asset_save` tool** (`integrations/ada-voice/backend/tools.d/asset_save.py`,
manifest snippet `manifest.asset_save.yml`):
- Resolves the image: explicit `media_url=` (the `/relay-img/arch/` URL
  from a "photo received" turn, an archive-relative path, or any
  fetchable image URL), else this chat's latest `kind=image` entry in
  `manifest.jsonl` via `session_chat_id(runner, "line")`.
- Magic-byte sniff (jpeg/png/gif/webp), `ADA_ASSET_MAX_BYTES` cap
  (15 MiB), stores under `<LINE_MEDIA_ARCHIVE_DIR>/persona-assets/`
  with sha256 dedupe + hash-suffixed collision names, served publicly
  at `<ADA_RELAY_PUBLIC_BASE|LINE_PUBLIC_IMG_BASE>/arch/persona-assets/`
  by the relay's existing arch route — no new hosting.
- Upserts `assets/<slug>` via new `memory_ops.asset_remember` riding
  the `ada_remember` ACL; mirrors ada_remember's write gates
  (`_scan_memory_write` → `_memory_staging_required` →
  `_stage_memory_write(route="asset")` for non-admins, direct write for
  `{full:true}`). Confirmed-policy banks refuse honestly (tools.d
  confirmed args never reach `run()`).
- `memory_pending.py` gained route `asset` (replays through
  `asset_remember` on approval); `scripts/ada/memory-pending.py`
  `_runtime` includes `asset`.

**Recall side — image-bearing memory hits:**
- `memory_ops._doc_to_hit` surfaces `meta.image_url` on hits;
  `asset_remember` writes it.
- `tool_runner/memory.py` `ada_memory_search` promotes the first usable
  hit carrying `image_url` (http/https/`/v1/`, not draft/archival) to
  top-level `image_url` + `image_note` — `_safe_args` keeps scalars so
  the relay's `_images_from` attaches it to the reply automatically.
  Per-hit `image_url` also survives for deliberate `chat_send` resends.

**Chaba SSOT:** `ssot.apps.ada-memory-schema.yml` gained
`meta_schema.fields.image_url`; `ssot.tools.yml` gained
`memory.asset_save`; `ssot.tool-surface` coverage_debt lists the tool
until a live scenario lands; `tool_guide.yml` has the usage entry.

**Trail:** `docs/ssot/jobs/ada/2026-11-24-persona-photo-store.yml`.

## Result

- `tests/ada/test_persona_photo_store.py`: **18/18 pass** — includes a
  patch-application gate against live ada-voice HEAD.
- ada-voice scratch tree (`/tmp/pps-ada`, baseline `8da3e42`):
  `tool-lint` clean, `pytest tests/ -x -q` 1646 passed (3 pre-existing
  fastapi-stub env failures, unrelated); `tools_loader.load()` resolves
  `asset_save` as DynamicTool (policy=read, secondary_allowed=false,
  timeout 60s).
- All edited YAML parses clean.

## How to verify

1. `python3 -m pytest tests/ada/test_persona_photo_store.py -x -q` in
   this worktree.
2. Review `integrations/ada-voice/README.md` "Drop 22" for install steps
   (apply 6 patches + copy 2 new files + merge manifest snippet).
3. After ada-voice merge+deploy: in a LINE group, send a photo and ask
   the persona to keep it, then ask for it back — the reply should
   carry the re-hosted image.

## Remaining gates

- ada-voice `dispatch/*` branch → merge-sweep → `deploy-ada.sh` on
  idc03 (Tony gate).
- `render-memory-banks.py` on a secrets-equipped host to register
  `image_url` in the bank-registry JSON (warn-only drift until then).
- TG lanes: no LINE media archive, so `asset_save` there needs an
  explicit fetchable `media_url=`.

lessons:
- tools.d dynamic tools do NOT ride MEMORY_WRITE_TOOLS — a tool that
  writes banks must replicate the dispatch-layer gates itself
  (_check_memory_write_allowed + _scan/_stage/_memory_staging_required)
  or it silently bypasses person_policies, allowed_tools and the
  pending-approval lane.
- The relay's tool_result image path keys off top-level scalar
  image_url/image_note in the tool result (_safe_args keeps scalars,
  _cap_tool_result preserves them) — nested per-hit fields never reach
  _images_from; promote to top level for auto-attach.
- /relay-img/arch/{rest:path} already serves nested archive paths —
  persona-assets/ needed zero new hosting; reuse the media archive
  before reaching for an object store.
- memory_banks._slug falls back to 'note' for non-latin descriptions —
  generic slugs need a content-hash suffix or unrelated saves collide
  on the same doc key.
- Declared-tool lint counts DECLARATION description lines (cap 4) —
  keep the one-liner tight and move prose to tool_guide.yml.
