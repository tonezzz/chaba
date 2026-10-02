#!/bin/bash
# cast-desktop-run.sh <display_num> <out_m3u8> [pad|crop]
# Merges the right X auth cookies for the given X11 display, then runs ffmpeg x11grab -> HLS.
# Adapted for tony-omen (DISPLAY :0, XAUTHORITY from gdm).
d=$1
out=$2
mode=${3:-pad}
base="${out%.m3u8}"
tmp=$(mktemp /tmp/cast-xauth.XXXXXX)
trap "rm -f $tmp" EXIT

# Pull cookie for this display from all likely authority files.
for f in "/run/user/$(id -u)/gdm/Xauthority" "$HOME/.Xauthority"; do
  [ -f "$f" ] || continue
  xauth -f "$f" nlist ":$d" 2>/dev/null | xauth -f "$tmp" nmerge - 2>/dev/null
done

export DISPLAY=":$d"
export XAUTHORITY="$tmp"

if [ "$mode" = "crop" ]; then
  vf="scale=1280:720:force_original_aspect_ratio=increase,crop=1280:720"
else
  vf="scale=1280:720:force_original_aspect_ratio=decrease,pad=1280:720:-1:-1"
fi

exec /usr/bin/ffmpeg -hide_banner -loglevel warning \
  -f x11grab -framerate 10 -i ":$d" \
  -f lavfi -i anullsrc=r=44100:cl=mono \
  -vf "$vf" -c:v libx264 -preset ultrafast -tune zerolatency \
  -pix_fmt yuv420p -g 20 -c:a aac -b:a 16k -f hls -hls_time 2 -hls_list_size 6 -hls_delete_threshold 20 \
  -strftime 1 -hls_segment_filename "${base}_%Y%m%d%H%M%S.ts" \
  -hls_flags delete_segments+program_date_time \
  "$out"
