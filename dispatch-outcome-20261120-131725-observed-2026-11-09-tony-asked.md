# Dispatch outcome — ada-status-live-state-preference (attempt 2)

**Card:** `ada-status-live-state-preference` — OPS-1045 miss: "what is
kk-mac processing" was answered from board card comms hours stale
("offline 22h, 15GiB free") while the live host was online with ~92-115GiB
free (kk_mac lane probe eligible, heartbeat 4min).

**Branch:** `dispatch/20261120-131725-observed-2026-11-09-tony-asked`,
commit `653700bb6a` (11 files, +1199). Prior attempts all died on the
EOL'd Jules lane (FAILED_PRECONDITION — provider-side, not a code bug);
this attempt ran devin lane.

## What changed

- **`scripts/board/host_status.py`** (new, ~600 lines) — live-first host
  status aggregator + CLI implementing the card's three rules:
  1. **Live surfaces queried before board records** —
     `kk_mac_admission.snapshot()` lane probe for kk-mac
     (ada-nest-heartbeats, MDDB :11026), the same heartbeat collection
     for other hosts, the nest-mgr `ada-cms-pages/nest-<host>` page
     (:11027), and runner claims (`action.status=running` + runner).
  2. **Freshness tags** — every board-derived statement (comms +
     request asks mentioning the host) carries `as of Xh ago`; a
     `latest_claim` deep-scan (40 records) finds the newest host-*state*
     claim even when it isn't among the latest raw mentions.
  3. **Contradiction flags** — `offline_vs_live`,
     `blocked_vs_eligible`, `disk_disagree` (>10GiB divergence). Both
     sides are always reported; the answer leads with live telemetry.
     Host aliases normalize (`kk mac`/`kk_mac`/`KKs-Mac-Studio`/
     `kk-imac` → `kk-mac`; `kk-macbook` stays distinct via alnum-boundary
     matching). Probes fail soft (`fetched:false`, `confidence:
     board_only`) — never fatal.
- **`scripts/board/board-api.py`** — `GET /host-status?host=<name>` read
  door (open-read like `/cards`, no lock, 400+hint without host, cards
  from `load_cards()` with dir-scan fallback).
- **ada-voice drop 19** (staged, `integrations/ada-voice/`) —
  `backend/tools.d/host_status.py` thin HTTP adapter over the endpoint
  (`ADA_HOST_STATUS_API`, default idc03 :10000) +
  `manifest.host_status.yml` (read/secondary/45s) +
  `tool_guide.host_status.yml` (the behavioral fix: host-state asks go
  through this tool, conflicts named both-sides, card comms never
  parroted as current). README updated with install steps.
- **`docs/ssot/infrastructure/ssot.tools.yml`** — `host.status` registry
  row (agents: ada-voice, ada-dev, ada-ocb, devin).
- **`docs/kb/board-api-read-door.md`** — endpoint row + response
  contract + checklist item.
- **`docs/ssot/jobs/board/2026-11-20-host-status-live-first.yml`** —
  trail doc with remaining deploy gates.

## Result / verification

- `python3 -m unittest tests.board.test_host_status` — **24 tests pass**,
  including the OPS-1045 contradiction shape (record "offline 22h +
  15GiB" vs live eligible + 92GiB → `offline_vs_live` +
  `blocked_vs_eligible` + `disk_disagree` all flagged, answer leads with
  live telemetry) and a deep-claim test (stale claim outside the top-5
  mentions still tagged + flagged). `tests.board.test_board_api_reads` —
  30 tests pass incl. `/host-status` routing (400 without host; delegates
  to `hs.host_status`).
- `board-api.py --selftest` → `selftest ok`.
- **Live end-to-end on idc02:** `python3 scripts/board/host_status.py
  kk-mac --text` → "kk-mac is ONLINE (live kk_mac_lane_probe): heartbeat
  3m ago, lane probe eligible, 55GiB free, ollama ok, node idle. latest
  board records — card … (as of 23m ago): …" — exactly the DONE-CONDITION
  behavior: live probe data first, board records freshness-tagged.
- `--board-only` degrades to a fully age-tagged board answer with a
  stale-prone caveat.

## Remaining gates (deploy, outside this worktree's scope)

- board-api redeploy on idc03 (runs from the chaba-tony-dell served
  checkout) — until then `/host-status` 404s and the ada tool errors
  cleanly.
- ada-voice drop install per README Drop 19 (file copy + manifest merge +
  tool_guide append + backend restart).
- Optional follow-up: have ada-ocb's `ada_status` (ada-voice repo,
  `opencode/ada_mcp.py`) call `/host-status` internally for host-shaped
  references — no patch base available in this worktree, noted in the
  job trail.

lessons:
- scripts/board/board-api.py runs as a plain script — sibling imports
  resolve via its sys.path insert of scripts/board/, so new helper
  modules for it belong in scripts/board/ (cross-dir deps like
  kk_mac_admission need their own sys.path insert inside the helper).
- Card comms timestamps are local-naive "YYYY-MM-DD HH:MM" — parse with
  datetime.fromisoformat().astimezone() so ages are consistent on any
  host.
- Real cards have string (non-dict) comms entries — guard isinstance
  before .get when scanning comms.
- Regex over normalized text needs alnum boundaries, NOT `-` boundaries:
  normalization turns spaces into `-`, so `(?<![a-z0-9-])` blocks every
  real match; and add `(?<![\d.])` before digit captures or greedy
  backtracking matches "2GiB" inside "92GiB".
- Jules lane is retired (provider EOL) — cards declaring executor=jules
  need the devin lane; earlier "failures" were FAILED_PRECONDITION, not
  code bugs.
