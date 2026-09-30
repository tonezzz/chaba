#!/usr/bin/env bash
# yt-transcript.sh <url|id> [lang] — pull YouTube auto-captions, emit plain text.
# Runs on mn01 (or any host with yt-dlp). Called by Ada's yt_transcript tool:
#   ssh <host> yt-transcript.sh <url>
# Thai news sites block scrapers; YouTube auto-captions are the open lane.
set -uo pipefail
URL="${1:?url required}"; LANG="${2:-th}"
WORK=$(mktemp -d); trap 'rm -rf "$WORK"' EXIT
YTDLP="${YTDLP:-$HOME/.local/bin/yt-dlp}"
TITLE=$("$YTDLP" "$URL" --skip-download --no-warnings --print "%(title)s" 2>/dev/null || echo "?")
# one lang per attempt — multi-lang fanout hits HTTP 429
VTT=""
for L in "${LANG}-orig" "$LANG" en; do
    "$YTDLP" "$URL" --write-auto-subs --sub-langs "$L" --skip-download \
        --no-warnings -o "$WORK/%(id)s" >/dev/null 2>&1 || true
    VTT=$(ls -t "$WORK"/*."$L".vtt 2>/dev/null | head -1) || true
    [ -n "$VTT" ] && break
done
if [ -z "$VTT" ]; then echo "NO_CAPTIONS ${TITLE}"; exit 0; fi
echo "TITLE: $TITLE"
echo "LANG: $(basename "$VTT" | sed -E 's/.*\.([a-z-]+)\.vtt/\1/')"
# VTT -> text: unescape entities, strip tags/timestamps, dedupe, cap ~6k chars
sed -E 's/<[^>]+>//g; s/\[.*\]//g' "$VTT" \
  | grep -vE -- '^WEBVTT|^$|-->|^Kind|^Language' \
  | python3 -c 'import html,sys
seen=set(); out=[]
for line in sys.stdin:
    line = html.unescape(line).strip()
    if not line or line in seen: continue
    seen.add(line); out.append(line)
sys.stdout.write("\n".join(out)[:6000])'
