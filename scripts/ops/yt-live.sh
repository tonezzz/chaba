#!/usr/bin/env bash
# yt-live.sh — cast a YouTube video to the TV with transcribed + translated
# subtitles burned into the picture, served as HLS from Caddy /apps/yt-live/.
#
# Usage:
#   yt-live.sh <youtube-url> [target_lang]   # default target_lang = th
#   yt-live.sh stop
#   yt-live.sh cache                         # list media-cache entries
#
# Env overrides: YT_LIVE_BASE, HA_BASE, YT_PLAYER, YT_MIN_SEGS, NO_SUBS=1,
# YT_LIVE_NOCACHE=1 (bypass media cache), YT_LIVE_CACHE_MAX (bytes, default
# 8 GiB LRU cap), GEMINI_MODEL. Ada announce needs
# ~/.config/secrets/ada-api-key.env with ADA_NOTIFY_URL + ADA_API_KEY
# (optional — cast works without it).
set -euo pipefail
export PATH="$HOME/.local/bin:$PATH"  # yt-dlp, deno live here

# Repo home: chaba scripts/ops/. Installed copies in ~/.local/bin resolve
# siblings from their own dir (real file or symlink — readlink -f covers both),
# falling back to ~/.local/bin for pre-repo-home installs.
SCRIPT_DIR="$(cd "$(dirname "$(readlink -f "$0")")" && pwd)"
YT_VTT_TRANSLATE="${YT_VTT_TRANSLATE:-$SCRIPT_DIR/yt-vtt-translate.py}"
[ -x "$YT_VTT_TRANSLATE" ] || YT_VTT_TRANSLATE="$HOME/.local/bin/yt-vtt-translate.py"

# Served by the containerized web Caddy (:80 -> 127.0.0.1:8080), docroot =
# live checkout stacks/web/public. (The old :8085 edge serving
# ~/.config/caddy/public was retired 2026-09-25.)
APP_DIR="/home/tony/CascadeProjects/chaba-tony-dell/stacks/web/public/apps/yt-live"
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
        "$APP_DIR"/.gen-* "$PIDFILE"
}

# --- media cache -----------------------------------------------------------
# Full HLS output per video+lang in ~/.cache/yt-live-media/<key>/ so replays
# skip download + translate + transcode entirely. A dir holds the copied
# APP_DIR artifacts plus meta.json and a `complete` marker written LAST —
# no marker means the populate was interrupted and the entry is ignored.
# LRU: `last_used` file mtime drives eviction once total > YT_LIVE_CACHE_MAX.
MEDIA_CACHE="$HOME/.cache/yt-live-media"
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

cache_lookup() {  # $1 vid, $2 target_lang -> cache dir on stdout
  [ "${NO_SUBS:-0}" = "1" ] || [ "${YT_LIVE_NOCACHE:-0}" = "1" ] && return 1
  local d
  for d in "$MEDIA_CACHE/$1".*/; do
    [ -f "${d}complete" ] && [ -f "${d}media.m3u8" ] || continue
    # Match on the langs the request would actually burn, recomputed from the
    # entry's srclang — mirrors the subtitle-selection block below.
    python3 - "${d%/}" "$2" <<'PY' && { echo "${d%/}"; return 0; }
import json, sys
d, tgt = sys.argv[1], sys.argv[2]
try:
    m = json.load(open(d + "/meta.json"))
except Exception:
    sys.exit(1)
if m.get("subs") == "no":       # source had no captions -> same output for all
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
sys.exit(0 if want == (m.get("langs") or "") else 1)
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
cache_finalize() {  # $1 dest dir, $2 gen token path
  local d="$1" gen="$2" i
  for i in $(seq 1 720); do   # up to ~2h of transcode
    [ -f "$gen" ] || exit 0
    grep -q ENDLIST "$APP_DIR/media.m3u8" 2>/dev/null && break
    kill -0 "$(cat "$PIDFILE" 2>/dev/null)" 2>/dev/null || exit 0
    sleep 10
  done
  [ -f "$gen" ] || exit 0
  grep -q ENDLIST "$APP_DIR/media.m3u8" 2>/dev/null || exit 0
  mkdir -p "$d"
  cp -al "$APP_DIR"/. "$d"/ 2>/dev/null || cp -a "$APP_DIR"/. "$d"/
  rm -f "$d"/.gen-* "$d"/run.pid "$d"/ffmpeg.pid "$d"/.lock "$d"/*.log
  # validate: ENDLIST present and every listed segment actually copied
  if python3 - "$d" <<'PY'
import os, sys
d = sys.argv[1]
pls = [l.strip() for l in open(os.path.join(d, "media.m3u8"), errors="replace")]
segs = [l for l in pls if l and not l.startswith("#")]
sys.exit(0 if any(l == "#EXT-X-ENDLIST" for l in pls) and segs
         and all(os.path.exists(os.path.join(d, s)) for s in segs) else 1)
PY
  then touch "$d/last_used" "$d/complete"
  else rm -rf "$d"
  fi
}

cache_replay() {  # $1 cache dir -> populate APP_DIR, then cast_now
  local d="$1"
  cp -al "$d"/. "$APP_DIR"/ 2>/dev/null || cp -a "$d"/. "$APP_DIR"/
  rm -f "$APP_DIR"/.gen-* "$APP_DIR"/complete "$APP_DIR"/last_used \
        "$APP_DIR"/run.pid "$APP_DIR"/ffmpeg.pid
  [ -s "$APP_DIR/media.m3u8" ] \
    || { echo "cache replay: copy failed, falling back to full pipeline"; return 1; }
  VID="$(meta_get "$d" vid)"; TITLE="$(meta_get "$d" title)"
  touch "$d/last_used"
  echo "== replay from media cache ($(du -sh "$d" | cut -f1) cached, \
$(ls "$APP_DIR"/seg_*.ts 2>/dev/null | wc -l) segs)"
  [ -n "$TITLE" ] && echo "   title: $TITLE"
  cast_now
}

cast_now() {  # assumes APP_DIR/media.m3u8 exists
  echo "== casting $BASE_URL/media.m3u8"
  local code
  code="$(ha_call media_player/play_media \
    "{\"entity_id\":\"$PLAYER\",\"media_content_id\":\"$BASE_URL/media.m3u8\",\"media_content_type\":\"application/vnd.apple.mpegurl\"}" \
    || echo 000)"
  if [ "$code" != "200" ]; then
    code="$(ha_call media_player/play_media \
      "{\"entity_id\":\"$PLAYER\",\"media_content_id\":\"$BASE_URL/media.m3u8\",\"media_content_type\":\"video\"}" \
      || echo 000)"
  fi
  echo "   play_media: HTTP $code   player state: $(ha_state "$PLAYER")"
  echo "   ffmpeg log: $LOG   (transcode continues in background)"
  [ "$code" = "200" ] && ada_notify
  return 0
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
    cache_finalize "$2" "$3"; exit 0 ;;
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
trap 'rm -f "$RUNFILE"' EXIT

stop_ffmpeg
clean_dir

# Fast path: a URL whose id is already in the media cache replays instantly —
# no yt-dlp, no transcode. (Search queries still resolve first, then recheck.)
VID_GUESS="$(extract_vid "$URL" || true)"
if [ -n "$VID_GUESS" ] && HIT="$(cache_lookup "$VID_GUESS" "$TARGET_LANG")" \
   && [ -n "$HIT" ]; then
  cache_replay "$HIT" && exit 0
fi

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
subs = list(d.get("subtitles", {})) + list(d.get("automatic_captions", {}))
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
if [ -n "$VID" ] && HIT="$(cache_lookup "$VID" "$TARGET_LANG")" \
   && [ -n "$HIT" ]; then
  cache_replay "$HIT" && exit 0
fi

cache_prune   # free LRU space before the incoming download

echo "== downloading${SUBLANG:+ (subs: $SUBLANG)}"
SUBS_ARGS=()
[ -n "$SUBLANG" ] && SUBS_ARGS=(--write-subs --write-auto-subs
  --sub-langs "$SUBLANG" --sub-format 'vtt/best')
# -i: a subtitle 429 must not kill the video download
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
  TARGET_LANG="$TARGET_LANG" \
  python3 - "$APP_DIR/meta.json" <<'PY'
import json, os, sys, time
g = os.environ.get
json.dump({"vid": g("VID"), "title": g("TITLE"),
           "duration": int(g("DURATION") or 0), "url": g("URL"),
           "srclang": g("SRCLANG"), "langs": g("LANGS_ARG"),
           "subs": g("SUBS_KIND"), "target": g("TARGET_LANG"),
           "created": int(time.time())},
          open(sys.argv[1], "w"), ensure_ascii=False)
PY
  GEN_TOKEN="$APP_DIR/.gen-$$"; touch "$GEN_TOKEN"
  mkdir -p "$MEDIA_CACHE"
  setsid "$0" __finalize "$MEDIA_CACHE/$CACHE_KEY" "$GEN_TOKEN" \
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
