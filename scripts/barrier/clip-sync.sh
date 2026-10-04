#!/usr/bin/env bash
# clip-sync — one-way X clipboard poller: REMOTE clipboard -> local clipboard.
#
# Barrier 2.4.0 relays only text between seats; this mirrors image/* payloads
# too. Deployed as two user units so the pair is bidirectional:
#
#   tony-omen  clip-sync-dell.service  clip-sync tony-dell   (dell -> omen)
#   tony-dell  clip-sync-omen.service  clip-sync tony-omen   (omen -> dell)
#
# The local display comes from the unit's DISPLAY/XAUTHORITY. The remote
# display is set via REMOTE_DISPLAY/REMOTE_XAUTHORITY (dell seat: :1 +
# ~/.Xauthority — :1 does not enforce a cookie; omen seat: :0 +
# ~/.Xauthority).
#
# Change detection: the remote TIMESTAMP target is a cheap trigger. When it
# changes we sha256 the payload on the remote side and write locally only if
# the content hash differs — content-keyed, so the two directions converge
# after at most one redundant pull instead of ping-ponging the same payload
# back and forth (a TIMESTAMP-only key would loop: every xclip -in acquires a
# fresh timestamp). Owners that don't serve TIMESTAMP fall back to hashing
# every poll — heavier but still correct.

set -u

REMOTE="${1:?usage: clip-sync <ssh-alias>}"
POLL="${POLL:-1}"
REMOTE_DISPLAY="${REMOTE_DISPLAY:-:1}"
REMOTE_XAUTHORITY="${REMOTE_XAUTHORITY:-/home/tony/.Xauthority}"
IMG_TMP="${XDG_RUNTIME_DIR:-/tmp}/clip-sync-img.$$"
LOG_TAG="clip-sync($REMOTE)"

rx() { # run a command on the remote host with its X env
    ssh -o ConnectTimeout=3 -o BatchMode=yes "$REMOTE" \
        "DISPLAY=$REMOTE_DISPLAY XAUTHORITY=$REMOTE_XAUTHORITY $*" 2>/dev/null
}

img_target_of() { # pick the best image/* target offered, preference-ordered
    local t
    for t in image/png image/jpeg image/jpg image/bmp image/webp image/tiff image/gif; do
        printf '%s\n' "$1" | grep -qx "$t" && { echo "$t"; return; }
    done
    printf '%s\n' "$1" | grep -m1 '^image/'
}

PREV_TXT=""
PREV_IMG_HASH=""
PREV_IMG_TS="init"
trap 'rm -f "$IMG_TMP"' EXIT
echo "$LOG_TAG up: remote=$REMOTE remote_display=$REMOTE_DISPLAY poll=${POLL}s" >&2

while true; do
    targets=$(rx 'xclip -o -selection clipboard -t TARGETS')
    img=$(img_target_of "$targets")

    if [ -n "$img" ]; then
        ts=""
        if printf '%s\n' "$targets" | grep -qx 'TIMESTAMP'; then
            # TIMESTAMP is cheap; hash its raw bytes into a clean change key
            ts=$(rx 'xclip -o -selection clipboard -t TIMESTAMP | sha256sum | cut -d" " -f1')
        fi
        if [ -z "$ts" ] || [ "$ts" != "$PREV_IMG_TS" ]; then
            PREV_IMG_TS="$ts"
            h=$(rx "xclip -o -selection clipboard -t $img | sha256sum | cut -d' ' -f1")
            if [ -n "$h" ] && [ "$h" != "$PREV_IMG_HASH" ]; then
                if rx "xclip -o -selection clipboard -t $img" > "$IMG_TMP" && [ -s "$IMG_TMP" ]; then
                    xclip -in -selection clipboard -t "$img" < "$IMG_TMP"
                    PREV_IMG_HASH="$h"
                    echo "$LOG_TAG pulled $img ($(stat -c%s "$IMG_TMP") bytes)" >&2
                fi
            fi
        fi
    elif [ -n "$targets" ]; then
        clip=$(rx 'xclip -o -selection clipboard')
        if [ -n "$clip" ]; then
            h=$(printf '%s' "$clip" | sha256sum | cut -d' ' -f1)
            if [ "$h" != "$PREV_TXT" ]; then
                printf '%s' "$clip" | xclip -in -selection clipboard
                PREV_TXT="$h"
                echo "$LOG_TAG pulled text (${#clip} chars)" >&2
            fi
        fi
    fi
    sleep "$POLL"
done
