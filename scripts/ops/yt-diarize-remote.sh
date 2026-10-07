#!/usr/bin/env bash
# yt-diarize-remote.sh — diarize on the tony-omen GPU, land the turn file
# in the mn01 media corpus for renders on tony-dell.
#
#   yt-diarize-remote.sh <media> [<turns-out>]
#
# <media>: local path, or mn01:~/media-corpus/... (corpus path) — routed
# through this host to tony-omen either way. Default <turns-out> is
# mn01:~/media-corpus/yt-dub-prep/<stem>.diarize.txt plus a local copy
# next to the media (or cwd for remote media).
#
# Handoff: tony-omen diarizes (pyannote, ~/.venvs/diarize) -> mn01 corpus
# holds the turn file next to the staged mp4/vtt -> tony-dell renders with
# yt-vtt-dub.py --diarize-file. No GPU or pyannote needed off-omen.
set -euo pipefail

OMEN="${YT_DIARIZE_OMEN:-tony-omen}"
VENV='~/.venvs/diarize/bin/python'
CORPUS="mn01:media-corpus/yt-dub-prep"

media="${1:?usage: yt-diarize-remote.sh <media> [turns-out]}"
stem="$(basename "$media")"; stem="${stem%.*}"
remote=/tmp/yt-diarize-$$
trap 'ssh -o BatchMode=yes "$OMEN" "rm -rf $remote" >/dev/null 2>&1 || true' EXIT

ssh -o BatchMode=yes "$OMEN" "mkdir -p $remote"
scp -q "$(dirname "$0")/yt-diarize.py" "$OMEN:$remote/"

if [[ "$media" == mn01:* ]]; then
    scp -q "$media" "$OMEN:$remote/in.${media##*.}"
elif [[ -f "$media" ]]; then
    scp -q "$media" "$OMEN:$remote/in.${media##*.}"
else
    echo "media not found: $media" >&2; exit 1
fi

ssh -o BatchMode=yes "$OMEN" \
    "$VENV $remote/yt-diarize.py $remote/in.${media##*.} \
     $remote/out.txt --rttm $remote/out.rttm"

out="${2:-}"
if [[ -z "$out" ]]; then
    out="$stem.diarize.txt"
    scp -q "$OMEN:$remote/out.txt" "$out"
    scp -q "$out" "$CORPUS/$stem.diarize.txt"
    scp -q "$OMEN:$remote/out.rttm" "$CORPUS/$stem.diarize.rttm"
    echo "turns: $out + $CORPUS/$stem.diarize.{txt,rttm}" >&2
else
    scp -q "$OMEN:$remote/out.txt" "$out"
    echo "turns: $out" >&2
fi
