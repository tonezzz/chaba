# Document archive service — design draft for review (2026-09-23)

Scope: take document photos/scans (like the A-68 sale pack), normalize them
for archiving, and store them durably — with a service living on idc01.
Related jobs: `document-print-pipeline` (P3 archive), `ada-devin-dispatch`.

## 1. What was already done today (A-68)

- Split the two double-page deed photos into 4 single pages
  (070547 / 070548 / backs), auto-trimmed to the page border.
- Archival enhancement on all 7 images: per-channel white-balance
  (paper → white), black-point deepen for text, mild unsharp — color
  kept deliberately (red Garuda stamps, blue signatures carry info).
- Output: `~/Downloads/A-68/archive/A-68-*.jpg` @300dpi, JPEG q92.
- Extraction of key fields: `~/Downloads/A-68/A-68-extracted.md`.

## 2. Proposed pipeline (per document set)

```
inbox (photos/scan/PDF) 
  → normalize: split spreads, trim, white-balance, levels, sharpen
  → emit: page JPEGs q92 + one PDF per set + manifest.json (fields, hashes)
  → store: gdrive:ada-documents/<YYYY>/<set-slug>/
  → index: metadata doc in MDDB `documents` bank (type, parties, numbers,
    dates, gdrive path) — "find my condo deed" via ada_memory_search
```

## 3. Google Drive for archiving — pros & cons

**Pros**
- Already integrated: working `gdrive:` rclone remote (tony-dell),
  `~/GoogleDrive` mount unit exists, and `gdrive:notebooklm/chaba` is
  the established upload convention for NotebookLM sources — an
  `ada-documents/` collection fits the same pattern and can feed NLM
  deep-recall later.
- Offsite durability: survives any single host/disk loss; versioning
  in Drive UI; shareable links when a doc must be sent (e.g. to agent).
- Free tier is enough for documents (JPEG q92 ~0.5–1.5 MB/page; 15 GB
  ≈ 10k+ pages) — no new service cost.

**Cons**
- Privacy: deeds, ID cards, passports on Google cloud. The account is
  personal so risk is bounded, but it's a real policy decision — raw
  scans should be treated like the `personal` bank class (never
  repo-bound, never shared).
- rclone mount quirks: eventual consistency, `--vfs-cache` staleness,
  rate limits on bursts; better to `rclone copy` explicit paths than
  rely on the mount for writes.
- Token maintenance: gdrive OAuth can need re-auth (same class of
  upkeep as notebooklm keepalive — we already solved this pattern).
- Multi-writer risk: two hosts writing the same Drive folder can
  conflict — pick ONE writer (the service) and treat others as read.
- Not a backup by itself for the *metadata* — MDDB bank docs still
  need their own backup (already covered by backup-mddb-banks.py).

Alternatives if privacy wins: local-only archive on idc01 (already the
MDDB host, has backup timers) + optional encrypted rclone remote
(`crypt:` over gdrive) later — same workflow, ciphertext in Drive.

## 4. Service on idc01 — proposed shape

- **Name**: `doc-archive` — small Python service (FastAPI, like
  notebooklm-rest) or a folder watcher; systemd user service/quadlet on
  idc01, tailnet-only.
- **Why idc01**: MDDB lives there → bank metadata writes are local; it
  already runs backup timers; tony-dell stays unburdened.
- **Gap**: idc01 has NO rclone/gdrive today. Two options:
  - (a) install rclone on idc01 + copy `~/.config/rclone/rclone.conf`
    gdrive token from tony-dell — simplest, same credential-copy
    pattern as devin credentials.
  - (b) idc01 calls an upload endpoint on tony-dell (which owns the
    remote) — avoids duplicating Google creds but adds a hop.
  Recommendation: (a), then restrict the folder to `ada-documents/`.
- **API**: `POST /v1/archive` {files[], set_slug, doc_type} → normalize
  → stream to gdrive → MDDB doc → returns archive_id.
  `GET /v1/archive/{id}` status, `GET /v1/archive/{id}/page/{n}` streams
  a page back. Reuse the X-API-Key pattern from notebooklm-rest.
- **Transport: direct Drive REST (benchmarked 2026-09-23,
  scripts/bench-gdrive.py — rclone vs REST, same files, RAM-only).**
  REST wins every op on both hosts:

  | op | size | tony-dell rclone / REST | idc01 rclone / REST |
  |---|---|---|---|
  | up | 1 MB | 2.84s / 2.43s | 2.85s / 2.54s |
  | up | 32 MB | 5.78s / 4.29s | 5.03s / 3.63s |
  | down | 1 MB | 2.56s / 1.40s | 2.53s / 1.40s |
  | down | 32 MB | 4.44s / 3.05s | 3.87s / 3.31s |
  | list | — | 0.48s / 0.39s | 0.49s / 0.43s |

  REST = resumable-upload PUT + `alt=media` GET via urllib (stdlib —
  no new deps needed); rclone = rcat/cat subprocess. Advantage is
  mostly fixed overhead (~0.3–1.3s/op: spawn + internal checks); raw
  throughput converges ~10–11 MB/s (WAN-bound). For doc workloads
  (~1 MB pages) REST is ~1.7x faster per op and keeps everything
  in-process. rclone stays for bulk/offline ops and manual inspection.
  Retry+backoff is mandatory either way — we hit transient 500s and
  quota 403s inside a ~60-op run.

- **OAuth client: dedicated, now live on both hosts.** The bench
  exposed a real flaw: rclone.conf had empty client_id/secret →
  rclone's *shared* built-in GCP project (202264815644), whose
  per-minute query quota is contended by every default-cred rclone
  user — we got repeated `Quota exceeded` 403s. Fixed by granting
  `drive` scope under the existing `google_credentials.json` desktop
  client (project `gen-lang-client-0694401188`) and writing
  client_id/secret/token into rclone.conf on idc01 + tony-dell.
  Side effects: dedicated ~12k-req/min quota for ALL rclone use
  (notebooklm syncs benefit too), and the service can refresh the
  access token itself (refresh_token in rclone.conf).
- **Storage model: RAM-only, no local staging.** Upload bytes arrive in
  memory; normalize runs on PIL/numpy buffers; outputs stream out via
  Drive REST resumable-upload (or `rclone rcat` as fallback) — nothing
  touches idc01's disk. set.pdf + manifest.json are built in a BytesIO.
  Reads stream back via `alt=media` → HTTP response, or `lp` stdin for
  printing.
  - Dedup needs no disk either: sha256 over the bytes, pHash over the
    decoded image — both computed in RAM.
  - NLM feed needs no disk: files are already on Drive; add source by
    Drive file-ID (same path nlm-add uses).
  - Do NOT use the rclone *mount* for writes (VFS cache = disk anyway,
    plus staleness); REST/rcat bypass it entirely.
  - Only real tradeoff: a crash mid-set drops in-flight work — pages are
    ~1 MB so reprocessing is seconds; if it ever matters, a tmpfs
    scratch dir gives recovery without real disk usage.
- **Ada hookup** (later): `ada_document_archive` tool calls this API —
  same confirmed=true gate as print.
- **Layout**: `gdrive:ada-documents/<YYYY>/<set-slug>/{pages/*.jpg,
  set.pdf, manifest.json}`.

## 5. Decisions (2026-09-23)

1. Raw ID/passport scans on Google Drive: **OK** — personal account,
   `ada-documents/` folder, private sharing only.
2. Auto-feed NotebookLM: **YES** — archived sets become NLM sources via
   the existing nlm pipeline (same gdrive collection pattern).
3. Originals: **KEEP** — `~/Downloads` source files are never deleted by
   the service; `archive/` outputs are additional copies.

## 6. Duplicates & near-duplicates

Three different situations — handled differently:

**Exact duplicate (same bytes).** SHA-256 of each normalized page in
manifest.json. On ingest, query the `documents` bank for the hash;
a hit returns the existing archive_id — no re-upload, no new doc.

**Re-capture (same document, new photo/scan — different bytes, same
content).** Perceptual hash (pHash/dHash on the grayscale page) —
robust to brightness, resolution, compression. Hamming distance ≤ ~6
→ candidate; confirm by matching extracted doc numbers (deed no.,
ID no., passport no.) from the normalize step. Then compare quality
(resolution × blur score / Laplacian variance):
- new copy is better → archive it, mark the old doc
  `status: superseded` + `superseded_by` link (schema already supports
  this) — old file stays on Drive, just demoted in recall
- new copy is same/worse → skip upload, record a "seen again" note on
  the existing doc (bumps last_verified)

**New version of same document (renewed ID, re-issued deed).** Same
doc number but different issue date/serial → NOT a duplicate — archive
as new, link via `subject` (doc number) + supersedes chain. Recall
surfaces only `status: active`, so "my ID card" resolves to the
current version automatically.

**Set-level dedup.** A set's signature = sorted page phashes. Same
signature → the whole set is a re-capture; page-level matches inside a
partially-new set are handled per-page.

**Rule:** never auto-delete. Worst case is `status: superseded` — the
bytes stay on Drive; Tony decides deletion.
