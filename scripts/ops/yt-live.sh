#!/usr/bin/env bash
# yt-live.sh — cast a YouTube video to the TV with transcribed + translated
# subtitles burned into the picture, served as HLS from Caddy /apps/yt-live/.
#
# Usage:
#   yt-live.sh <youtube-url> [target_lang] [voice]  # voice: off|th|en (dub)
#   yt-live.sh stop
#   yt-live.sh cache                                # list media-cache entries
#
# Env overrides: YT_LIVE_BASE, HA_BASE, YT_PLAYER, YT_MIN_SEGS, NO_SUBS=1,
# YT_LIVE_NOCACHE=1, YT_LIVE_CACHE_MAX (8 GiB LRU cap), GEMINI_MODEL,
# YT_LIVE_VOICE (= arg3 default), YT_LIVE_APP / YT_LIVE_MCACHE (test dirs).
# voice != off renders a dub (yt-vtt-dub.py) in the background and upgrades
# the playing stream to dub.m3u8 mid-play; failure -> subs-only cast.
# Ada announce needs ~/.config/secrets/ada-api-key.env (optional).
set -euo pipefail
export PATH="$HOME/.local/bin:$PATH"  # yt-dlp, deno live here

# Repo home: chaba scripts/ops/. Installed copies in ~/.local/bin resolve
# siblings from their own dir (real file or symlink — readlink -f covers both),
# falling back to ~/.local/bin for pre-repo-home installs.
SCRIPT_DIR="$(cd "$(dirname "$(readlink -f "$0")")" && pwd)"
YT_VTT_TRANSLATE="${YT_VTT_TRANSLATE:-$SCRIPT_DIR/yt-vtt-translate.py}"
[ -x "$YT_VTT_TRANSLATE" ] || YT_VTT_TRANSLATE="$HOME/.local/bin/yt-vtt-translate.py"
YT_VTT_DUB="${YT_VTT_DUB:-$SCRIPT_DIR/yt-vtt-dub.py}"
[ -x "$YT_VTT_DUB" ] || YT_VTT_DUB="$HOME/.local/bin/yt-vtt-dub.py"

# Served by the containerized web Caddy (:80 -> 127.0.0.1:8080), docroot =
# live checkout stacks/web/public. (The old :8085 edge serving
# ~/.config/caddy/public was retired 2026-09-25.)
APP_DIR="${YT_LIVE_APP:-/home/tony/CascadeProjects/chaba-tony-dell/stacks/web/public/apps/yt-live}"
BASE_URL="${YT_LIVE_BASE:-http://192.168.2.67/apps/yt-live}"
HA_BASE="${HA_BASE:-http://127.0.0.1:8123}"
PLAYER="${YT_PLAYER:-media_player.tony_tv_cast}"
TARGET_LANG="${2:-th}"
PIDFILE="$APP_DIR/ffmpeg.pid"
RUNFILE="$APP_DIR/run.pid"
LOCKFILE="$APP_DIR/.lock"
LOG="$APP_DIR/ffmpeg.log"
SUBS_VTT="$APP_DIR/subs.vtt"

# <=720p h264 + aac: TrueID/Chromecast-safe and fast to burn-in.
FMT='bv*[vcodec^=avc1][height<=720]+ba[acodec^=mp4a]/bv*[vcodec^=avc1][height<=720]+ba/b[ext=mp4][vcodec^=avc1][height<=720]/b[ext=mp4]/b'
# (subtitle track is now picked from info.json's audio language)

# shellcheck disable=SC1091
source "$HOME/.config/secrets/nodered-ha.env"
TOKEN="${HASS_TOKEN:?HASS_TOKEN not set}"

ha_state() {
  curl -sf -m 5 -H "Authorization: Bearer ${TOKEN}" \
    "${HA_BASE}/api/states/$1" \
    | python3 -c 'import json,sys; print(json.load(sys.stdin)["state"])' 2>/dev/null
}

ha_call() { # domain/service, json payload
  curl -s -m 10 -o /dev/null -w "%{http_code}" -X POST \
    -H "Authorization: Bearer ${TOKEN}" -H "Content-Type: application/json" \
    -d "$2" "${HA_BASE}/api/services/$1"
}

stop_ffmpeg() {
  [ -f "$PIDFILE" ] && kill "$(cat "$PIDFILE")" 2>/dev/null || true
  rm -f "$PIDFILE"
}

kill_pipeline() {  # previous orchestrator + its children (yt-dlp, translate)
  local old
  old="$(cat "$RUNFILE" 2>/dev/null || true)"
  [ -n "$old" ] || return 0
  pkill -P "$old" 2>/dev/null || true
  # run-spawned processes share the run's process group (api spawn uses
  # start_new_session -> pgid=pid) — group-kill reaches grandchildren that
  # -P would orphan. Detached __dub/__finalize workers sit in their own
  # session; they self-abort when clean_dir removes their .gen token.
  pkill -g "$old" 2>/dev/null || true
  kill "$old" 2>/dev/null || true
}

ada_notify() {  # best-effort: Ada announces playback; never fails the cast
  local envf="$HOME/.config/secrets/ada-api-key.env" msg
  [ -f "$envf" ] || return 0
  msg="yt_cast finished — the video \"$TITLE\" just started playing on the TV. Announce it to the user briefly."
  ( set -a; source "$envf"; set +a
    [ -n "${ADA_NOTIFY_URL:-}" ] && [ -n "${ADA_API_KEY:-}" ] || exit 0
    curl -s -m 10 -o /dev/null -X POST "$ADA_NOTIFY_URL" \
      -H "X-Api-Key: $ADA_API_KEY" -H "Content-Type: application/json" \
      -d "$(python3 -c 'import json,sys; print(json.dumps({"text": sys.argv[1]}))' "$msg")"
  ) || true
}

clean_dir() {
  mkdir -p "$APP_DIR"
  rm -f "$APP_DIR"/seg_*.ts "$APP_DIR"/*.m3u8 "$APP_DIR"/*.vtt \
        "$APP_DIR"/src.* "$APP_DIR"/*.log "$APP_DIR"/meta.json \
        "$APP_DIR"/dseg_*.ts "$APP_DIR"/dub.mp4 "$APP_DIR"/dub.state \
        "$APP_DIR"/dub.qc.json \
        "$APP_DIR"/.gen-* "$APP_DIR"/.cast-sent "$PIDFILE"
}

# --- media cache -----------------------------------------------------------
# Full HLS output per video+lang in ~/.cache/yt-live-media/<key>/ so replays
# skip download + translate + transcode entirely. A dir holds the copied
# APP_DIR artifacts plus meta.json and a `complete` marker written LAST —
# no marker means the populate was interrupted and the entry is ignored.
# LRU: `last_used` file mtime drives eviction once total > YT_LIVE_CACHE_MAX.
MEDIA_CACHE="${YT_LIVE_MCACHE:-$HOME/.cache/yt-live-media}"
CACHE_MAX="${YT_LIVE_CACHE_MAX:-8589934592}"   # 8 GiB

extract_vid() {  # best-effort 11-char id without network; "" for searches
  python3 - "$1" <<'PY'
import re, sys
m = re.search(r'(?:v=|youtu\.be/|/shorts/|/live/|/embed/)'
              r'([A-Za-z0-9_-]{11})', sys.argv[1])
print(m.group(1) if m else "")
PY
}

meta_get() {
  python3 -c 'import json,sys
try: print(json.load(open(sys.argv[1]+"/meta.json")).get(sys.argv[2]) or "")
except Exception: print("")' "$1" "$2"
}

cache_lookup() {  # $1 vid, $2 target_lang, $3 voice (off|th|en) -> dir on stdout
  [ "${NO_SUBS:-0}" = "1" ] || [ "${YT_LIVE_NOCACHE:-0}" = "1" ] && return 1
  local d
  for d in "$MEDIA_CACHE/$1".*/; do
    [ -f "${d}complete" ] && [ -f "${d}media.m3u8" ] || continue
    # Match on the langs the request would actually burn, recomputed from the
    # entry's srclang — mirrors the subtitle-selection block below — plus the
    # voice variant (dubbed entries carry meta voice=<lang> + dub.m3u8).
    python3 - "${d%/}" "$2" "${3:-off}" <<'PY' && { echo "${d%/}"; return 0; }
import json, os, sys
d, tgt, wvoice = sys.argv[1], sys.argv[2], sys.argv[3]
try:
    m = json.load(open(d + "/meta.json"))
except Exception:
    sys.exit(1)
if m.get("subs") == "no":       # no captions -> undubbable, same for all voices
    sys.exit(0)
src = m.get("srclang") or ""
if src.split("-")[0] == "en":
    want = tgt
elif src == tgt:
    want = "en"
else:
    want = "en," + tgt
if want.split(",")[0] == src.split("-")[0]:
    want = ""
ok = want == (m.get("langs") or "") and (m.get("voice") or "off") == wvoice
if ok and wvoice != "off":      # a voice entry is only real with dub.m3u8
    ok = os.path.exists(d + "/dub.m3u8")
sys.exit(0 if ok else 1)
PY
  done
  return 1
}

cache_prune() {  # LRU evict oldest last_used until under CACHE_MAX
  [ -d "$MEDIA_CACHE" ] || return 0
  local total victim
  total="$(du -sb "$MEDIA_CACHE" 2>/dev/null | cut -f1)"
  while [ "${total:-0}" -gt "$CACHE_MAX" ]; do
    victim="$(for d in "$MEDIA_CACHE"/*/; do
      stat -c "%Y %n" "$d/last_used" 2>/dev/null || echo "0 ${d%/}"
    done | sort -n | head -1 | cut -d' ' -f2-)"
    [ -n "$victim" ] && [ -d "$victim" ] || break
    echo "   cache prune: evicting $(basename "$victim")"
    rm -rf "$victim"
    total="$(du -sb "$MEDIA_CACHE" 2>/dev/null | cut -f1)"
  done
}

# Detached repopulation: waits for the playlist to finish, then hardlinks the
# APP_DIR artifacts into the cache dir. Aborts if a newer run cleaned APP_DIR
# (gen token gone) or ffmpeg died before ENDLIST. Re-invoked via `__finalize`.
# Voice casts: $1 is the base (off) key; the entry lands at "<base>.<voice>"
# when the dub succeeded — a failed/skipped dub stores the subs-only variant
# under the base key instead (voice=off in meta), so the cache never carries
# an entry that claims a dub it doesn't have.
cache_finalize() {  # $1 base dest dir, $2 gen token path, $3 voice mode
  local d="$1" gen="$2" voice="${3:-off}" i
  for i in $(seq 1 720); do   # up to ~2h of transcode
    [ -f "$gen" ] || exit 0
    grep -q ENDLIST "$APP_DIR/media.m3u8" 2>/dev/null && break
    kill -0 "$(cat "$PIDFILE" 2>/dev/null)" 2>/dev/null || exit 0
    sleep 10
  done
  [ -f "$gen" ] || exit 0
  grep -q ENDLIST "$APP_DIR/media.m3u8" 2>/dev/null || exit 0
  local final_voice="off" dst="$APP_DIR/dub.state"
  if [ "$voice" != "off" ]; then
    # the dub render can outlive the transcode — wait for a terminal state
    for i in $(seq 1 720); do
      [ -f "$gen" ] || exit 0
      grep -qsE ':(done|failed|skipped)$' "$dst" && break
      sleep 10
    done
    [ -f "$gen" ] || exit 0
    if grep -qs ':done' "$dst" \
       || grep -qs ENDLIST "$APP_DIR/dub.m3u8" 2>/dev/null; then
      final_voice="$voice"; d="$d.$voice"
    elif [ -f "$d/complete" ]; then
      exit 0   # dub failed on a replayed off variant — entry already exists
    fi
  fi
  mkdir -p "$d"
  cp -al "$APP_DIR"/. "$d"/ 2>/dev/null || cp -a "$APP_DIR"/. "$d"/
  rm -f "$d"/.gen-* "$d"/run.pid "$d"/ffmpeg.pid "$d"/.lock "$d"/*.log \
        "$d"/.cast-sent "$d"/dub.state "$d"/dub.mp4
  # off-variant entries must not carry a partial dub — a truncated dub.m3u8
  # would fail validation and the subs variant is the honest artifact
  [ "$final_voice" = "off" ] && rm -f "$d"/dub.m3u8 "$d"/dseg_*.ts
  if [ "$voice" != "off" ]; then
    # stamp the real variant in the cached meta (rewrite breaks the hardlink)
    rm -f "$d/meta.json"
    SRC_META="$APP_DIR/meta.json" FINAL_VOICE="$final_voice" \
    python3 - "$d/meta.json" <<'PY'
import json, os, sys
try:
    m = json.load(open(os.environ["SRC_META"]))
except Exception:
    m = {}
m["voice"] = os.environ["FINAL_VOICE"]
json.dump(m, open(sys.argv[1], "w"), ensure_ascii=False)
PY
  fi
  # validate: every playlist has ENDLIST and all its segments actually copied
  if python3 - "$d" <<'PY'
import os, sys
d = sys.argv[1]
ok = True
for pl in ("media.m3u8", "dub.m3u8"):
    p = os.path.join(d, pl)
    if not os.path.exists(p):
        ok = ok and pl != "media.m3u8"
        continue
    ls = [l.strip() for l in open(p, errors="replace")]
    segs = [l for l in ls if l and not l.startswith("#")]
    ok = ok and bool(segs) and any(l == "#EXT-X-ENDLIST" for l in ls) \
        and all(os.path.exists(os.path.join(d, s)) for s in segs)
sys.exit(0 if ok else 1)
PY
  then
    if [ "$final_voice" = "off" ] || [ -f "$d/dub.m3u8" ]; then
      touch "$d/last_used" "$d/complete"
    else
      rm -rf "$d"
    fi
  else rm -rf "$d"
  fi
}

cache_replay() {  # $1 cache dir -> populate APP_DIR, then cast_now
  local d="$1"
  cp -al "$d"/. "$APP_DIR"/ 2>/dev/null || cp -a "$d"/. "$APP_DIR"/
  # drop copied run markers, but keep this run's own gen token — it's the
  # liveness check for any detached __dub/__finalize workers we spawn
  local g
  for g in "$APP_DIR"/.gen-*; do
    [ -e "$g" ] || continue
    [ "$g" = "${GEN_TOKEN:-__keep__}" ] || rm -f "$g"
  done
  rm -f "$APP_DIR"/complete "$APP_DIR"/last_used \
        "$APP_DIR"/run.pid "$APP_DIR"/ffmpeg.pid
  [ -s "$APP_DIR/media.m3u8" ] \
    || { echo "cache replay: copy failed, falling back to full pipeline"; return 1; }
  VID="$(meta_get "$d" vid)"; TITLE="$(meta_get "$d" title)"
  touch "$d/last_used"
  # voice variants replay their dubbed playlist straight away — the dub is
  # already baked, no subs-first upgrade needed
  local pls="media.m3u8" mv
  mv="$(meta_get "$d" voice)"
  [ -n "$mv" ] && [ "$mv" != "off" ] && [ -s "$APP_DIR/dub.m3u8" ] \
    && pls="dub.m3u8"
  echo "== replay from media cache ($(du -sh "$d" | cut -f1) cached, \
$(ls "$APP_DIR"/seg_*.ts 2>/dev/null | wc -l) segs)"
  [ "$pls" != "media.m3u8" ] && { echo "   voice=$mv -> dubbed playlist"
    echo "$mv:done" >"$APP_DIR/dub.state"; }
  [ -n "$TITLE" ] && echo "   title: $TITLE"
  cast_now "$pls"
}

cast_now() {  # $1 playlist (default media.m3u8), $2 "no" = skip Ada announce
  local pls="${1:-media.m3u8}" code
  touch "$APP_DIR/.cast-sent"   # lets a waiting dub job upgrade mid-play
  echo "== casting $BASE_URL/$pls"
  code="$(ha_call media_player/play_media \
    "{\"entity_id\":\"$PLAYER\",\"media_content_id\":\"$BASE_URL/$pls\",\"media_content_type\":\"application/vnd.apple.mpegurl\"}" \
    || echo 000)"
  if [ "$code" != "200" ]; then
    code="$(ha_call media_player/play_media \
      "{\"entity_id\":\"$PLAYER\",\"media_content_id\":\"$BASE_URL/$pls\",\"media_content_type\":\"video\"}" \
      || echo 000)"
  fi
  echo "   play_media: HTTP $code   player state: $(ha_state "$PLAYER")"
  echo "   ffmpeg log: $LOG   (transcode continues in background)"
  [ "$code" = "200" ] && [ "${2:-yes}" = "yes" ] && ada_notify
  return 0
}

# Voice dub (voice != off). Latency strategy — mid-play upgrade, chosen over
# gating the cast on the dub: edge-tts synthesis is far slower than the
# transcode, so holding the cast would mean minutes of dead air. Instead the
# subs-only HLS casts at MIN_SEGS as usual while the dub renders off src.mp4
# + subs.vtt in the background; when dub.mp4 lands it remuxes (codec copy,
# seconds) to dseg_*.ts + dub.m3u8 and the TV is re-pointed at the dubbed
# playlist — playback restarts at 0 dubbed. Any failure leaves the subs cast
# running untouched.
#
# Runs detached via `__dub` (own session, same pattern as __finalize) so the
# upgrade doesn't depend on the orchestrator staying alive; the gen token is
# the "still the current run" check — a newer cast or `stop` removes it via
# clean_dir and the worker exits before touching the new run's artifacts.
dub_job() {  # $1 media input (src.mp4|m3u8), $2 karaoke vtt ("" ok),
             # $3 voice, $4 duration-ish ("" -> ffprobe), $5 gen token path,
             # $6 video id (per-video fix-map lookup)
  local din="$1" kar="$2" voice="$3" dur="$4" gen="$5" vid="${6:-}"
  local st="$APP_DIR/dub.state" secs
  # compress_lines wants GEMINI_API_KEY — the replay path never passed
  # through the subs block that sources it
  [ -f "$HOME/.config/secrets/gemini-api-key.env" ] && \
    { set -a; . "$HOME/.config/secrets/gemini-api-key.env"; set +a; }
  [ -n "$kar" ] && [ -s "$kar" ] || kar=""
  secs="${dur%%.*}"
  case "$secs" in ''|*[!0-9]*)
    secs="$(ffprobe -v error -show_entries format=duration -of csv=p=0 \
             "$din" 2>/dev/null | cut -d. -f1)" ;;
  esac
  case "$secs" in ''|*[!0-9]*) secs=7200 ;; *) secs=$((secs + 5)) ;; esac
  [ "$secs" -lt 10 ] && secs=7200   # unknown/live duration -> don't truncate
  echo "$voice:rendering" >"$st"
  echo "   dub: edge-tts render detached (voice=$voice, secs=$secs)"
  local args=("$din" "$SUBS_VTT" "$APP_DIR/dub.mp4"
              --lang "$voice" --secs "$secs")
  # compress_lines' prompt is TH-specific — skip it for non-TH voices
  [ "$voice" = "en" ] && args+=(--no-compress)
  # caption QC gate: flagged cues skip TTS but stay in the burn; the report
  # (dub.qc.json) rides into the media cache next to dub.mp4
  args+=(--qc)
  # fix-map watch-list: shared seed in the repo + optional per-video dict
  # (~/.cache/yt-live-subs/fixmap/<vid>.json); files merge in order
  local fm=()
  [ "$voice" = "th" ] && [ -f "$SCRIPT_DIR/yt-dub-fixmap.th.json" ] \
      && fm+=("$SCRIPT_DIR/yt-dub-fixmap.th.json")
  [ -n "$vid" ] && [ -f "$HOME/.cache/yt-live-subs/fixmap/$vid.json" ] \
      && fm+=("$HOME/.cache/yt-live-subs/fixmap/$vid.json")
  [ "${#fm[@]}" -gt 0 ] && args+=(--fix-map "$(IFS=,; echo "${fm[*]}")")
  if [ -n "$kar" ] && grep -qm1 -E '<[0-9:.]{10,}><c>' "$kar" 2>/dev/null; then
    args+=(--sentences --en-vtt "$kar")
    echo "   dub: sentence mode (karaoke: $(basename "$kar"))"
  fi
  if timeout 5400 "$YT_VTT_DUB" "${args[@]}" >"$APP_DIR/dub.log" 2>&1 \
     && [ -s "$APP_DIR/dub.mp4" ] && [ -f "$gen" ]; then
    echo "$voice:muxing" >"$st"
    if ffmpeg -hide_banner -loglevel error -y -i "$APP_DIR/dub.mp4" -c copy \
        -f hls -hls_time 4 -hls_list_size 0 -hls_playlist_type vod \
        -hls_segment_filename "$APP_DIR/dseg_%05d.ts" \
        "$APP_DIR/dub.m3u8" >>"$APP_DIR/dub.log" 2>&1; then
      # upgrade only after the subs cast has actually gone out
      for _ in $(seq 1 600); do
        [ -f "$gen" ] || return 0
        [ -f "$APP_DIR/.cast-sent" ] && break
        sleep 1
      done
      if [ -f "$APP_DIR/.cast-sent" ] && [ -f "$gen" ]; then
        echo "$voice:done" >"$st"
        echo "   dub: ready — upgrading stream to dub.m3u8 (restarts dubbed)"
        cast_now dub.m3u8 no
        return 0
      fi
    fi
  fi
  [ -f "$gen" ] || return 0
  echo "$voice:failed" >"$st"
  echo "   dub: render/mux failed — subs-only cast continues (see dub.log)"
  return 0
}

# Spawn the detached dub worker (re-invokes this script as `__dub`, same
# pattern as __finalize). Caller must have created GEN_TOKEN already. The
# orchestrator may exit before the dub lands — output goes to dub.log
# (append) so a closed parent stdout can't SIGPIPE the worker.
dub_spawn() {  # $1 media input, $2 karaoke vtt, $3 duration-ish
  setsid "$0" __dub "$1" "$2" "$VOICE" "$3" "$GEN_TOKEN" "${VID:-}" \
    >>"$APP_DIR/dub.log" 2>&1 &
}

# Voice request, only the subs (off) variant cached: replay it instantly,
# render the dub off the cached media (src.mp4 rides along in the entry, else
# the cached playlist itself), upgrade mid-play, and let __finalize store the
# dubbed artifacts under "<base>.<voice>".
cache_replay_dub() {  # $1 off-variant cache dir
  local d="$1" din kar dur srclang
  cache_replay "$d" || return 1
  [ -f "$SUBS_VTT" ] || return 0  # no captions in entry — subs cast stands
  dur="$(meta_get "$d" duration)"
  srclang="$(meta_get "$d" srclang)"
  din="$APP_DIR/src.mp4"; [ -s "$din" ] || din="$APP_DIR/media.m3u8"
  kar="$APP_DIR/src.${srclang}.vtt"; [ -s "$kar" ] || kar=""
  dub_spawn "$din" "$kar" "$dur"
  setsid "$0" __finalize "$d" "$GEN_TOKEN" "$VOICE" >/dev/null 2>&1 &
  return 0
}

try_replay() {  # $1 vid -> 0 if a cache entry took over the cast
  local hit
  if hit="$(cache_lookup "$1" "$TARGET_LANG" "$VOICE")" && [ -n "$hit" ]; then
    cache_replay "$hit" && return 0
  fi
  if [ "$VOICE" != "off" ]; then
    if hit="$(cache_lookup "$1" "$TARGET_LANG" off)" && [ -n "$hit" ]; then
      cache_replay_dub "$hit" && return 0
    fi
  fi
  return 1
}

case "${1:-}" in
  ""|-h|--help)
    sed -n '2,14p' "$0"; exit 0 ;;
  stop)
    kill_pipeline
    stop_ffmpeg
    echo "media_stop: $(ha_call media_player/media_stop "{\"entity_id\":\"$PLAYER\"}")"
    clean_dir
    rm -f "$RUNFILE"
    exit 0 ;;
  __finalize)  # internal: detached cache populate, spawned by a cast run
    cache_finalize "$2" "$3" "${4:-off}"; exit 0 ;;
  __dub)       # internal: detached voice-dub worker, spawned by dub_spawn
    dub_job "$2" "$3" "$4" "$5" "$6" "$7"; exit 0 ;;
  cache)
    [ -d "$MEDIA_CACHE" ] || { echo "media cache empty"; exit 0; }
    python3 - "$MEDIA_CACHE" "$CACHE_MAX" <<'PY'
import json, os, sys, time
root, cap = sys.argv[1], int(sys.argv[2])
rows, total = [], 0
for name in sorted(os.listdir(root)):
    d = os.path.join(root, name)
    if not os.path.isdir(d):
        continue
    size = sum(os.path.getsize(os.path.join(d, f))
               for f in os.listdir(d) if os.path.isfile(os.path.join(d, f)))
    total += size
    try:
        meta = json.load(open(os.path.join(d, "meta.json")))
    except Exception:
        meta = {}
    try:
        used = os.path.getmtime(os.path.join(d, "last_used"))
    except OSError:
        used = 0
    ok = os.path.exists(os.path.join(d, "complete"))
    rows.append((used, name, size, ok, meta.get("title") or "?",
                 meta.get("target") or "-"))
for used, name, size, ok, title, tgt in rows:
    print(f"{time.strftime('%Y-%m-%d %H:%M', time.localtime(used))}  "
          f"{size/1e6:7.0f}M  {'ok ' if ok else 'BAD'}  {name:<28} "
          f"tgt={tgt:<3} {title[:50]}")
print(f"-- {len(rows)} entries, {total/1e9:.2f}G / {cap/1e9:.0f}G cap")
PY
    exit 0 ;;
esac

URL="$1"
# Voice dub mode: off (default = subs only, unchanged) | th | en.
# Positional arg 3 wins over YT_LIVE_VOICE. Parsed here (after the
# subcommand dispatch) so __finalize's positional args stay free.
VOICE="${3:-${YT_LIVE_VOICE:-off}}"
case "$VOICE" in off|th|en) ;; *) echo "voice must be off|th|en" >&2; exit 2 ;; esac

# Non-URL arg = YouTube search (voice-friendly: "yt-live.sh the egg kurzgesagt")
case "$URL" in http*|www.*|ytsearch*) ;; *) URL="ytsearch1:$URL" ;; esac

# Respect the managed kill switch (packages/cast-safety.yaml).
if [ "$(ha_state input_boolean.cast_enabled)" = "off" ]; then
  echo "cast_enabled is off — managed casting disabled"; exit 1
fi

# Single-flight: a new cast supersedes any pipeline already running.
mkdir -p "$APP_DIR"
exec 9>"$LOCKFILE"
if ! flock -n 9; then
  kill_pipeline
  stop_ffmpeg
  flock 9
fi
echo $$ > "$RUNFILE"
trap '[ "$(cat "$RUNFILE" 2>/dev/null)" = "$$" ] && rm -f "$RUNFILE"' EXIT

stop_ffmpeg
clean_dir
# Run-scoped generation token: a newer cast's clean_dir removes it, which is
# how detached workers (__dub, __finalize) notice they've been superseded.
GEN_TOKEN="$APP_DIR/.gen-$$"; touch "$GEN_TOKEN"

# Fast path: a URL whose id is already in the media cache replays instantly —
# no yt-dlp, no transcode. (Search queries still resolve first, then recheck.)
VID_GUESS="$(extract_vid "$URL" || true)"
if [ -n "$VID_GUESS" ] && try_replay "$VID_GUESS"; then exit 0; fi

echo "== resolving $URL"
yt-dlp --no-playlist --skip-download -j "$URL" > "$APP_DIR/info.json" \
  2>"$APP_DIR/ytdlp.log" \
  || { echo "yt-dlp resolve failed:"; tail -5 "$APP_DIR/ytdlp.log"; exit 1; }
mapfile -t META < <(python3 - "$APP_DIR/info.json" <<'PY'
import base64, json, sys
d = json.load(open(sys.argv[1]))
print(d.get("id") or "")
print(d.get("duration") or 0)
print(base64.b64encode((d.get("title") or "?").encode()).decode())
audio = (d.get("language") or "").lower()
# live_chat is the chat-replay stream, not a caption track — yt-dlp pulls it
# as endless fragments (2026-10-10: ydYDqZQpim8 ran 4h+, Frag1481+, lane held).
subs = [s for s in list(d.get("subtitles", {})) + list(d.get("automatic_captions", {}))
        if s != "live_chat"]
pick = ""
for want in (audio, audio + "-orig", "en", "en-orig"):
    if want and want in subs:
        pick = want
        break
print(pick or (subs[0] if subs else ""))
PY
)
VID="${META[0]}"
DURATION="${META[1]}"
TITLE="$(base64 -d <<<"${META[2]}")"
SUBLANG="${META[3]:-}"

# Resolved a search/unknown URL — the video may still be cached.
if [ -n "$VID" ] && try_replay "$VID"; then exit 0; fi

cache_prune   # free LRU space before the incoming download

echo "== downloading${SUBLANG:+ (subs: $SUBLANG)}"
SUBS_ARGS=()
[ -n "$SUBLANG" ] && SUBS_ARGS=(--write-subs --write-auto-subs
  --sub-langs "$SUBLANG" --sub-format 'vtt/best')
# -i: a subtitle 429 must not kill the video download
# YT_LIVE_DL_TIMEOUT caps the download so a runaway (huge VOD, trickle
# fragments) can't hold the serial cast lane forever.
yt-dlp() { timeout "${YT_LIVE_DL_TIMEOUT:-1800}" command yt-dlp "$@"; }
yt-dlp --no-playlist --no-warnings --quiet -i -f "$FMT" \
  --merge-output-format mp4 "${SUBS_ARGS[@]}" \
  -o "$APP_DIR/src.%(ext)s" "$URL" 2>"$APP_DIR/ytdlp.log" \
  || { echo "yt-dlp failed:"; tail -5 "$APP_DIR/ytdlp.log"; exit 1; }
SRC="$(ls "$APP_DIR"/src.mp4 2>/dev/null | head -1)"
[ -n "$SRC" ] || { echo "no src.mp4 produced"; exit 1; }
echo "   title: $TITLE  (${DURATION}s)"

SUBSRC="" SRCLANG="" LANGS_ARG=""
if [ "${NO_SUBS:-0}" != "1" ]; then
  [ -n "$SUBLANG" ] && [ -f "$APP_DIR/src.$SUBLANG.vtt" ] \
    && SUBSRC="$APP_DIR/src.$SUBLANG.vtt"
  [ -z "$SUBSRC" ] && SUBSRC="$(ls "$APP_DIR"/src.*.vtt 2>/dev/null | head -1 || true)"
fi

if [ -n "$SUBSRC" ]; then
  SRCLANG="$(basename "$SUBSRC" .vtt | sed 's/^src\.//')"
  # The original-language line always stays on top; translations are appended below.
  # src=EN -> target below; src==target (e.g. Thai->Thai) -> English below;
  # other src -> English + target below.
  if [ "${SRCLANG%%-*}" = "en" ]; then
    LANGS_ARG="$TARGET_LANG"
  elif [ "$SRCLANG" = "$TARGET_LANG" ]; then
    LANGS_ARG="en"
  else
    LANGS_ARG="en,$TARGET_LANG"
  fi
  # English source with English target -> nothing to translate.
  [ "${LANGS_ARG%%,*}" = "${SRCLANG%%-*}" ] && LANGS_ARG=""
  echo "== translating subs ($(basename "$SUBSRC") -> ${LANGS_ARG:-original only})"
  # shellcheck disable=SC1091
  set -a; source "$HOME/.config/secrets/gemini-api-key.env"; set +a
  # Translation cache: keyed by video id + source/track langs — replays skip
  # the whole Gemini pass and start transcoding immediately.
  CACHE_DIR="$HOME/.cache/yt-live-subs"; mkdir -p "$CACHE_DIR"
  CACHE_FILE=""
  [ -n "$VID" ] && [ -n "$LANGS_ARG" ] \
    && CACHE_FILE="$CACHE_DIR/${VID}.${SRCLANG}.${LANGS_ARG//,/+}.vtt"
  if [ -n "$CACHE_FILE" ] && [ -f "$CACHE_FILE" ]; then
    echo "   cached translation -> subs.vtt"
    cp "$CACHE_FILE" "$SUBS_VTT"
  elif [ -z "$LANGS_ARG" ]; then
    echo "   source already in target lang — original subs only"
    sed 's/<[^>]*>//g' "$SUBSRC" > "$SUBS_VTT"
  elif [ -n "${GEMINI_API_KEY:-}" ] && \
     "$YT_VTT_TRANSLATE" "$SUBSRC" "$SUBS_VTT" --langs "$LANGS_ARG" --jobs 4; then
    echo "   merged subs -> subs.vtt (original on top, then: $LANGS_ARG)"
    [ -n "$CACHE_FILE" ] && cp "$SUBS_VTT" "$CACHE_FILE"
  else
    echo "   translation unavailable — using original subs only"
    sed 's/<[^>]*>//g' "$SUBSRC" > "$SUBS_VTT"
  fi
else
  echo "== no captions found — casting without subs"
fi

# Voice dub: with captions + voice!=off the render runs in parallel with the
# subs transcode; the subs cast still plays at MIN_SEGS and the detached
# worker re-points the TV at dub.m3u8 when ready (see dub_job for the
# latency rationale — the gen token gates the upgrade, not our lifetime).
if [ "$VOICE" != "off" ]; then
  if [ -f "$SUBS_VTT" ] && [ -x "$YT_VTT_DUB" ]; then
    dub_spawn "$SRC" "$SUBSRC" "$DURATION"
  else
    echo "$VOICE:skipped" >"$APP_DIR/dub.state"
    echo "   dub: voice=$VOICE requested but no usable captions/dubber — subs-only"
  fi
fi

VF="scale='min(1280,iw)':-2"
[ -f "$SUBS_VTT" ] && VF="$VF,subtitles='$SUBS_VTT'"

echo "== transcoding + burning subs -> HLS"
setsid ffmpeg -hide_banner -loglevel warning -i "$SRC" \
  -vf "$VF" -c:v libx264 -preset veryfast -crf 23 -g 48 \
  -force_key_frames "expr:gte(t,n_forced*4)" \
  -c:a aac -b:a 128k \
  -f hls -hls_time 4 -hls_list_size 0 -hls_playlist_type event \
  -hls_segment_filename "$APP_DIR/seg_%05d.ts" "$APP_DIR/media.m3u8" \
  >"$LOG" 2>&1 &
echo $! > "$PIDFILE"

# Media-cache bookkeeping: meta.json rides along into the cache dir; the
# .gen token lets the detached finalizer notice a superseded/stopped run.
if [ "${YT_LIVE_NOCACHE:-0}" != "1" ] && [ "${NO_SUBS:-0}" != "1" ] \
   && [ -n "$VID" ]; then
  if [ -f "$SUBS_VTT" ]; then
    CACHE_KEY="${VID}.${SRCLANG}${LANGS_ARG:+.${LANGS_ARG//,/+}}"
    SUBS_KIND=yes
  else
    CACHE_KEY="${VID}.nosubs"; SUBS_KIND=no
  fi
  VID="$VID" TITLE="$TITLE" DURATION="$DURATION" URL="$URL" \
  SRCLANG="$SRCLANG" LANGS_ARG="$LANGS_ARG" SUBS_KIND="$SUBS_KIND" \
  TARGET_LANG="$TARGET_LANG" VOICE_REQ="$VOICE" \
  python3 - "$APP_DIR/meta.json" <<'PY'
import json, os, sys, time
g = os.environ.get
m = {"vid": g("VID"), "title": g("TITLE"),
     "duration": int(g("DURATION") or 0), "url": g("URL"),
     "srclang": g("SRCLANG"), "langs": g("LANGS_ARG"),
     "subs": g("SUBS_KIND"), "target": g("TARGET_LANG"),
     "created": int(time.time())}
if g("VOICE_REQ") not in (None, "", "off"):
    m["voice"] = g("VOICE_REQ")   # requested variant; __finalize rewrites
                                # to "off" if the dub never lands
json.dump(m, open(sys.argv[1], "w"), ensure_ascii=False)
PY
  mkdir -p "$MEDIA_CACHE"
  setsid "$0" __finalize "$MEDIA_CACHE/$CACHE_KEY" "$GEN_TOKEN" "$VOICE" \
    >/dev/null 2>&1 &
fi

# Cast only once the receiver can grab a real buffer: full playlist done,
# or >= MIN_SEGS segments (~4s each) so it never chases the live edge.
MIN_SEGS="${YT_MIN_SEGS:-25}"
for i in $(seq 1 600); do
  if [ -s "$APP_DIR/media.m3u8" ]; then
    grep -q ENDLIST "$APP_DIR/media.m3u8" && break
    [ "$(ls "$APP_DIR"/seg_*.ts 2>/dev/null | wc -l)" -ge "$MIN_SEGS" ] && break
  fi
  kill -0 "$(cat "$PIDFILE" 2>/dev/null)" 2>/dev/null \
    || { echo "ffmpeg died:"; tail -10 "$LOG"; exit 1; }
  sleep 1
done
[ -s "$APP_DIR/media.m3u8" ] || { echo "ffmpeg produced no playlist:"; tail -5 "$LOG"; stop_ffmpeg; exit 1; }

cast_now

# A requested dub keeps rendering in the detached __dub worker past this
# exit; it re-points the TV at dub.m3u8 when ready (gen-token gated) and
# __finalize stores the "<base>.<voice>" cache variant after ENDLIST.
