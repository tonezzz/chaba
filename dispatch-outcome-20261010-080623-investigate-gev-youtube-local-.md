# dispatch outcome — investigate-gev-youtube-local-media-fail-d043e5

## What was investigated
Ada's 2026-10-09 02:24 report: "System showing multiple failures: Map 404, YT
Forbidden, local media Timed Out. Sending error brief via Telegram." Traced to
ada-ha-tony session `6744c10aab` (casting-suite scenario session, journal on
idc03). All three failures mapped to exact tool results.

## Findings

1. **Map 404 — RESOLVED (pre-existing fix).**
   `gev_command` → `gev command relay: HTTP Error 404`. Root cause was already
   found on card `ada-scenario-casting-hang`: generated Caddyfile dropped
   `uri strip_prefix /apps/gev-cmd` (chaba 7cb549b1, Oct 7). Fixed live Oct-9
   ~19:55 and made durable in `docs/ssot/infrastructure/ssot.routes.yml`
   (`strip: /apps/gev-cmd`). Re-verified this session: `GET /apps/gev/` → 200,
   `POST /apps/gev-cmd/command` → `ok:true`.

2. **YT Forbidden — transient 403 + a real wedge (fixed live, repo patched).**
   `yt action=status` showed `yt-dlp failed: HTTP Error 403: Forbidden` —
   intermittent YouTube bot-check flake (other downloads succeeded minutes
   apart). The bigger live problem: the last cast job
   (`watch?v=ydYDqZQpim8`, started ~04:03) had been in
   `downloading (subs: live_chat)` for **4+ hours** — the subtitle picker falls
   back to `subs[0]`, which was `live_chat`, and yt-dlp was grinding through the
   entire chat-replay stream (`src.live_chat.json.part-Frag1481`, still growing
   when found). Killed the stuck process at ~08:12 ICT; the serial cast lane is
   free.
   **Repo patch** (`scripts/ops/yt-live.sh`, committed on this dispatch branch):
   `live_chat` excluded from the sub pick list + download wrapped in
   `timeout ${YT_LIVE_DL_TIMEOUT:-1800}`.
   **Caveat:** the live `~/.local/bin/yt-live.sh` on tony-dell is an OLD
   revision (455 lines, no dub support, still has the flaw). Syncing it is a
   deploy — left for a Tony-approved session.

3. **local media Timed Out — vantage-blind URL pre-check (follow-ups filed).**
   `cast_to_screen play http://192.168.2.67/apps/yt-live/LLALMFmabV4-dub.mp4`
   → "URL is unreachable (TimeoutError)". The file serves **206** both on the
   LAN (verified from tony-dell) and on tailnet — but `192.168.2.67` is
   unreachable **from idc03**, where Ada's URL pre-flight check runs. Any
   LAN-only URL is refused regardless of what the display could fetch. The
   `voice-dub-demos` CMS recipe also hands Ada the LAN URL.
   Follow-up cards filed:
   - `cast-precheck-vantage` (ada-pi) — make the check advisory/relay-side or
     allowlist known-good media bases.
   - `voice-dub-recipe-lan-url` (chaba) — recipe should teach per-display URL
     choice (`https://tony-dell.taila0626a.ts.net/apps/yt-live/<file>.mp4` for
     tailnet displays, LAN URL for LAN-local ones).

## Changes
- `scripts/ops/yt-live.sh`: live_chat excluded + `YT_LIVE_DL_TIMEOUT` cap
  (commit `d5ceebbd`, dispatch branch only — not pushed).
- `docs/ssot/jobs/vcast/2026-10-10-gev-yt-local-media-failures.yml`: job record.
- Board: detailed findings comm posted on the card; two follow-up cards filed.

## How to verify
- `curl -X POST https://tony-dell.taila0626a.ts.net/apps/gev-cmd/command -d '{"name":"get_view_state","args":{}}'` → `ok:true` (Map lane).
- `ssh tony-dell 'curl -s http://127.0.0.1:8791/status'` → no job stuck in
  `downloading` for hours; `ps aux | grep yt-dlp` → no runaway.
- `ssh idc03 'curl -o /dev/null -w "%{http_code}" http://192.168.2.67/apps/yt-live/'`
  → timeout (expected — reproduces the pre-check failure mode).
- `bash -n scripts/ops/yt-live.sh` → clean; grep shows `live_chat` filter at
  ~line 515 and the `timeout` wrapper at ~line 544.

## Left for Tony / follow-ups
- Approve deploy: sync `~/.local/bin/yt-live.sh` on tony-dell with the repo
  copy (it is ~215 lines behind and lacks dub support).
- `yt action=transcript` returned `empty transcript` for one URL — minor,
  noted, not carded.
