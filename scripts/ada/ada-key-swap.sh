#!/usr/bin/env bash
# ada-key-swap — emergency Gemini key rotation for Ada on idc03.
#
# Standard procedure for "Ada WS dies with 1008 / Lightning dunning":
#   1. ssh idc03 journalctl --user -u ada-ha-tony | grep dunning  -> confirm
#   2. Put a fresh billed/free key in ~/.config/secrets/ada-paid or
#      ~/.config/secrets/ada-free on any host.
#   3. ada-key-swap.sh free            # point GEMINI_API_KEY at the free key
#      ada-key-swap.sh paid            # point it at the paid key
#      ada-key-swap.sh <literal-key>   # or a raw key
#      ada-key-swap.sh test            # just probe Live with the current key
#
# Rewrites GEMINI_API_KEY in every ada env on idc03 (gemini-keys.env FREE/
# PAID slots are the source of truth) and restarts the ada units.
set -euo pipefail
HOST="${ADA_HOST:-idc03}"
WHAT="${1:?usage: ada-key-swap.sh <free|paid|test|RAW_KEY>}"

case "$WHAT" in
  test)
    ssh "$HOST" 'cd ~/CascadeProjects/ada-voice && set -a && source ~/.config/secrets/ada-ha-tony.env && set -a &&
      .venv/bin/python -c "
import os,asyncio
async def t():
    from google import genai
    try:
        c=genai.Client(api_key=os.environ[\"GEMINI_API_KEY\"])
        async with c.aio.live.connect(model=\"gemini-2.5-flash-native-audio-preview-09-2025\", config={}) as s:
            print(\"LIVE OK\", os.environ[\"GEMINI_API_KEY\"][:14])
    except Exception as e:
        print(\"FAIL\", str(e)[:130])
asyncio.run(t())"'
    exit 0 ;;
  free|paid)
    KEY="$(cat "$HOME/.config/secrets/ada-$WHAT" 2>/dev/null)" \
      || KEY="$(ssh "$HOST" "cat ~/.config/secrets/ada-$WHAT")" ;;
  *) KEY="$WHAT" ;;
esac
[[ "$KEY" == AQ.* ]] || { echo "key doesn't look like a Gemini key (AQ.*)" >&2; exit 2; }

ssh "$HOST" "python3 - <<PY
import re, pathlib
KEY='$KEY'
for p in pathlib.Path('/home/tony/.config/secrets').glob('ada-*.env'):
    s = p.read_text()
    if 'GEMINI_API_KEY=' in s:
        p.write_text(re.sub(r'GEMINI_API_KEY=\S+', 'GEMINI_API_KEY='+KEY, s))
        print('updated', p.name)
PY
systemctl --user restart ada-ha-tony ada-ha-michael ada-kk ada-dev ada-pi-pwa"
sleep 15
echo "== verify:"; "$0" test
