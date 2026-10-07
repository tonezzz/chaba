# dispatch outcome — yt-dub-liam-e2e: Ada transcript audit + memory-pollution fix

## What was done

Tony ran the card's live voice pass twice and answered the board request:
"Check my transcript, Ada didn't know about it." This session audited both
ada-ha-tony sessions on idc03 (transcripts + journal tool calls) and fixed
the root cause reachable from this repo.

### Audit findings (evidence: idc03 journal + ~/.local/share/ada/transcripts/)

- **Session ece770ccb0 (17:55–17:56)**: Ada called `ada_memory_search` ×3
  and `cms_read action=list limit=10` ×1. All calls returned ok:true but
  none surfaced the dub; she answered "not in memory" and "CMS has only
  traffic + CCTV" — unsupported negative from a 10-item list.
- **Session 6e5d59f738 (18:34)**: `ada_session_recall` ×2 + `drive` search
  'Liam Noel' (0 files — wrong tool). No cms_read at all; she asserted
  "no videos are cached in the system" — flat wrong.

### Root causes

1. **Memory-bank pollution (fixed here)**: `ada_memory_search` top hits
   were all `devin/*` docs — raw Devin CLI thread dumps synced hourly by
   `scripts/ada/sync-devin-summaries.py`. Each dump leads with
   `=== MESSAGE 0 - System ===` (`<available_skills>`/`<system_info>`
   boilerplate), so the embedded vectors hit ~0.73–0.80 on every query
   and crowd out real memory.
2. **CMS listing blind spot (filed)**: `cms_read action=list` filters
   `kind=page`; `cached-videos-report` is `kind=report` (like 15 other
   reports) — invisible to list. `voice-dub-demos` IS a page and DOES
   list `LLALMFmabV4-dub.mp4` (updated 18:23, between the two tests).
3. **Tool-guide knowledge is error-path only (filed)**: the pointer
   "dub demos live in voice-dub-demos CMS page" lives in
   `backend/tool_guide.yml`, which only attaches to FAILED tool calls —
   on a clean turn Ada never sees it.
4. **Unsupported negative claims**: "no cached videos" declared twice
   with zero positive lookup.

## Changes

- `scripts/ada/sync-devin-summaries.py` — new `_strip_preamble()` removes
  the leading `=== MESSAGE 0 - System ===` block before `clip()`+embed.
  Verified: drops boilerplate, keeps MESSAGE-1 resume summary (topical
  content). On merge, the hourly `devin-summaries-sync.timer` (:45)
  resyncs all ~159 changed docs (one-off re-embed).
- `docs/ssot/jobs/yt-dub/2026-10-07-yt-dub-liam-e2e-ada-audit.yml` —
  full trail (evidence, root causes, fixes, residual risk).
- Filed card **ada-video-query-routing** (backlog) — ada-pi-side fixes:
  name voice-dub-demos + cached-videos-report in CMS_INSTRUCTIONS,
  decide kind=report list gap, negative-claim discipline.
- `ssot-validate-all.mjs` — 1628/1628 valid.
- Audit marker updated: `~/.local/share/devin/ada-audit-marker`.

## How to verify

- `python3 scripts/ada/sync-devin-summaries.py --dry-run` → history_*
  docs show `~` (changed) once remote differs.
- After merge + next :45 sync: `ada_memory_search 'youtube video'`
  should not return MESSAGE-0 skills text.
- Live pass (still needs Tony): retry the scenario after card
  ada-video-query-routing lands on idc03 — the dub
  (`LLALMFmabV4-dub.mp4`, still HTTP 200 at `/apps/yt-live/`) is in
  voice-dub-demos + cached-videos-report, so Ada just needs the routing.

## Blockers / pending

- ada-pi changes are outside this worktree — card ada-video-query-routing
  carries the precise patch locations (realtime_provider.py ~line 152,
  ~line 3513).
- Card verify step remains a live voice pass with Tony present.
