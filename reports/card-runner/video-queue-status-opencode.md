# Video queue status audit — 2026-11-26

Read-only reconciliation of both video Nest roots, produced for card
`video-queue-audit-opencode-repair` (retry of ADA-1046 / AUD-1048).

- **Tool:** `scripts/devnest/video_queue_status.py` (OPS-1042, strictly
  read-only — no claims released, no renders started, no Drive mutation)
- **Host:** idc02, run 2026-11-26 ~15:16–15:23 +0700
- **Stale-claim TTL:** 2.0 h (script default, per
  `docs/kb/video-queue-claim-lifecycle-procedure.md`)
- **Raw evidence:** `reports/card-runner/video-queue-status-opencode-20261126.json`
  (full per-pack inventory; this file is the human summary)

## Roots audited

| Root | Packages | render | support |
|---|---|---|---|
| `gdrive:ada-nest/kk-mac-video-pilot` | 14 | 12 | 2 |
| `gdrive:ada-nest` | 79 | 30 | 49 |
| **Total** | **93** | **42** | **51** |

Note: the lifecycle doc still names the pilot root
`gdrive:ada-nest-kk-mac-video-pilot`; that path does not exist — the
script docstring records the correction to
`gdrive:ada-nest/kk-mac-video-pilot` (verified 2026-11-24). The doc
should be updated to match.

## State counts

| State | kk-mac-video-pilot | ada-nest | Total |
|---|---|---|---|
| done | 11 | 60 | 71 |
| queued | 1 | 19 | 20 |
| failed | 2 | 0 | 2 |
| running | 0 | 0 | 0 |
| stale | 0 | 0 | 0 |
| retired (standalone) | 0 | 0 | 0 |

7 packs carry a `retired` marker *alongside* `done` (state precedence
reports `done`; the retired marker stays visible in pack detail) — all
in the Sacred Father family on `gdrive:ada-nest`.

**Delta vs the 2026-11-24 audit
(`reports/video-queue-status-2026-11-24.json`): zero.** Identical pack
set, identical states on both roots — the queue has been completely
idle for 2 days: no claims taken, no packs finished, nothing newly
staged.

## Claims

- **Active claims: 0. Stale claims: 0.** Nothing is running and nothing
  needs claim reconciliation — the 2026-11 stale-claim cleanup held.
- **Residual claims: 39** — claim files left behind on packs that are
  already `done`. They are residue, not work; the classifier correctly
  keeps those packs in `done`.
  - Age range: **492.4 h – 811.6 h** (≈ 20.5 – 33.8 days); median ≈ 780 h.
  - Oldest: `thonburian-bench` (colab-b6bdfc08-88678, 811.6 h).
  - Newest: `bge-hybrid-shadow-idc03-v2` (idc03-3210496, 492.4 h).
  - Workers involved: colab-*, idc03-*, tony-dell-*, tony-omen-*,
    KKs-Mac-Studio.local-* — all historical.

## Sacred Father (project `kk-video-c9f99fee6146`)

12 packs, all on `gdrive:ada-nest` (the pilot root holds only the
final/ artifact tree, not packs):

| Pack | State | Markers | Notes |
|---|---|---|---|
| -embeds | done | done, retired | superseded |
| -image-conditioning-probe | done | done | out/ artifacts |
| -pdf-image-audit | done | done | out/ artifacts |
| -pdf-text-diff | done | done | out/ artifacts |
| -preflight | done | done, retired | superseded |
| -preview | done | done | shots/ artifacts (11 shot dirs) |
| **-preview-v2** | **queued** | — | **deliberately held — see below** |
| -r2-preflight | done | done, retired | superseded |
| -r3-preflight | done | done, retired | superseded |
| -r4-preflight | done | done, retired | superseded |
| -source-image-use-approved | done | done, retired | superseded |
| -voice-clone-probe | done | done | out/ artifacts |

**Canonical final preview — verified live on Drive 2026-11-26:**

- Manifest: `scripts/devnest/video-manifests/sacred-father-final-preview.yml`
  + `reports/sacred-father-canonical-manifest-20261103.yml`
- `gdrive:ada-nest/kk-mac-video-pilot/final/pdf-final-preview-v4-clean.mp4`
  — 2,497,219 bytes (byte count matches the 2026-11-24 sha256-verified
  record exactly), plus `.th.srt` (772 B) and `.en.srt` (369 B).
- Unmanifested alternate `pdf-final-preview-canonical-v1.mp4`
  (3,451,458 B) still present on the same root — recorded for owner
  review, NOT canonical.
- `-preview-v2` is queued but **held by design**: its `pack.yml`
  `requires:` lists `kk-video-c9f99fee6146-preview-v2-resume-authorized`
  with the comment *"Deliberate hold per Tony; remove only when resuming
  the Colab V2 run."* That gate pack does not exist in either root, so
  the dependency can never be satisfied — do not dispatch it.

## Queued work (20 packs) — by family

- **doc-v2-\* pipeline** (6, `gdrive:ada-nest`, card
  doc-pilot-v2-polish-music-bed-subs-shot-943456): `shot-qc` →
  `rerender-shots` (GPU, requires shot-qc) → `music-bed`, `subs` →
  `delivery` (requires music-bed + subs). Legitimate ordered queue.
- **Sacred Father**: `-preview-v2` (held, above).
- **Pilot root**: `kk-mac-mlx-colab-scene0-control-20261124`,
  `kk-mac-video-probes` — Drive-only packs (no `pack.yml` in repo);
  queued ~2 days, intent unclear.
- **Support/other** (13 on ada-nest): gaussian-splat-×4,
  `kk-mac-gaussian-*`, `kk-mac-hibiscus-7k`, `img-gen-bench-t4`,
  `jev-triage`, `decision-arena`, `devnest-model-slot-30m`,
  `T4-QUEUE-ADDITIONS.md` (a markdown file staged as a pack dir).
  Per the lifecycle doc, `queued/other` is not a valid final status —
  each needs a declared role or retirement.

## Failed packs (2, both pilot root)

- `kk-mac-storyboard-i2v-shot03-oneoff-20261030` — failed
- `kk-mac-storyboard-i2v-shot03-oneoff-v2-20261030` — failed
- Superseded by `kk-mac-storyboard-i2v-shot03-oneoff-v3-20261030`
  (**done**). Candidates for `retired` markers per the lifecycle
  procedure (preserve history, never rerun).

## Safe recommendations (no mutations performed)

1. **Nothing to reconcile.** Zero active/stale claims; the queue is
   idle, not stuck. Do not release anything.
2. **Residual claim cleanup** — 39 stale-aged claim files on `done`
   packs are cosmetic but pollute every future audit's claim scan
   (each costs an `rclone lsl` RTT — this run took ~7 min mostly on
   them). Schedule one explicit cleanup pass per the claim-lifecycle
   procedure: verify `done` marker, remove only `claim/<worker>` files.
   Reversible, low-risk, but a separate approved op — not done here.
3. **Sacred Father**: leave `-preview-v2` held. The canonical
   `v4-clean` preview is verified on Drive; the next real step is the
   owner visual review → `approve_private_preview` → publish decision,
   which is a Tony gate, not a queue action.
4. **doc-v2-\***: if the doc-pilot-v2 polish card is still live, the
   safe dispatch order is `doc-v2-shot-qc` (CPU) first, then
   `music-bed`/`subs` (CPU), `rerender-shots` only on a GPU lane
   (requires shot-qc), `delivery` last. If the card is dead, retire
   the family rather than letting it sit queued forever.
5. **Pilot strays**: `kk-mac-mlx-colab-scene0-control-20261124` and
   `kk-mac-video-probes` have no repo-side pack definition — get an
   owner call (dispatch or retire); they cannot be safely interpreted
   from the queue alone.
6. **Failed shot03 oneoffs**: mark `retired` (successor v3 is done) —
   explicit, auditable, preserves history.
7. **Support-pack triage**: the 13 queued support/other packs violate
   the "no queued/other final status" rule — batch-triage each into
   support-package / canonical / historical / retired.
8. **Doc fix**: update `video-queue-claim-lifecycle-procedure.md` §1 to
   the corrected pilot root path.
9. **Cadence**: re-run this audit periodically (or after any render
   wave) — it is read-only and self-verifying; keep the JSON next to
   this report for diffing.

## Verification

- Re-run: `python3 scripts/devnest/video_queue_status.py` on any host
  with the `gdrive:` rclone remote; expect the same JSON shape.
- Cross-check counts: `python3 -c "import json;d=json.load(open('reports/card-runner/video-queue-status-opencode-20261126.json'));print([(q['remote'],q['states']) for q in d['queues']])"`
- Sacred Father spot-check: `rclone lsl gdrive:ada-nest/kk-mac-video-pilot/final/`
