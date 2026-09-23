#!/usr/bin/env bash
# chaba-guest deploy — run ON tony-dell. Idempotent, backs up before writing.
# Does: trusted_networks + config merge, www files, user units, HA restart.
# Prereq: ~/.config/secrets/chaba-guest.env exists, secrets.yaml has chaba_api_key,
# and the chaba worktree rendered context-guest.md into ~/.local/share/chaba/.
set -euo pipefail
cd "$(dirname "$0")"

HA_CFG=~/.config/home-assistant
STAMP=$(date +%Y%m%d-%H%M%S)
for f in configuration.yaml scripts.yaml input_texts.yaml; do
  [ -f "$HA_CFG/$f" ] && cp "$HA_CFG/$f" "$HA_CFG/$f.bak-$STAMP"
done

python3 - <<'PY'
import re, pathlib
cfg = pathlib.Path.home() / ".config/home-assistant/configuration.yaml"
src = cfg.read_text()

# --- trusted_networks += 127.0.0.1/32 (loopback trusted → bridge login flow)
block = re.search(
    r"(  auth_providers:\n    - type: trusted_networks\n      trusted_networks:\n)((?:        - .*\n)+)",
    src)
assert block, "trusted_networks block not found"
if "127.0.0.1" not in block.group(2):
    src = src[:block.end(2)] + "        - 127.0.0.1/32\n" + src[block.end(2):]
    print("added 127.0.0.1/32 to trusted_networks")

# --- rest_command: strip existing chaba_* entries, re-insert the full set
rc = re.search(r"^rest_command:\n((?:  .*\n)+)", src, re.M)
assert rc, "rest_command block not found"
rcbody = re.sub(r"  chaba_\w+:\n(?:    .*\n|      .*\n)+", "", rc.group(1))
src = src[:rc.start(1)] + rcbody + src[rc.end(1):]
rc = re.search(r"^rest_command:\n((?:  .*\n)+)", src, re.M)
insert = (
        '  chaba_guest_promote:\n'
        '    url: "http://127.0.0.1:8014/api/chaba/promote/{{ name | urlencode }}"\n'
        '    method: POST\n'
        '    headers:\n'
        '      X-Api-Key: !secret chaba_api_key\n'
        '    content_type: "application/json"\n'
        '    payload: "{}"\n'
        '  chaba_guest_revoke:\n'
        '    url: "http://127.0.0.1:8014/api/chaba/revoke/{{ name | urlencode }}"\n'
        '    method: POST\n'
        '    headers:\n'
        '      X-Api-Key: !secret chaba_api_key\n'
        '  chaba_ha_bridge_mint:\n'
        '    url: "http://127.0.0.1:8014/api/chaba/ha-bridge"\n'
        '    method: POST\n'
        '    headers:\n'
        '      X-Api-Key: !secret chaba_api_key\n'
        '  chaba_guest_reissue:\n'
        '    url: "http://127.0.0.1:8014/api/auth/keys/guest/redeem"\n'
        '    method: POST\n'
        '    content_type: "application/json"\n'
        '    headers:\n'
        '      X-Api-Key: !secret chaba_api_key\n'
        '    payload: \'{"path": "/", "redirect": "/guest/", "origin": "http://192.168.2.67:8126"}\'\n'
    )
src = src[:rc.end(1)] + insert + src[rc.end(1):]
print("chaba rest_commands merged")

# --- rest += pending-guests sensor (append to the rest: list block)
rest = re.search(r"^rest:\n((?:  .*\n)+)", src, re.M)
assert rest, "rest block not found"
if "chaba_pending_guests" not in rest.group(1):
    entry = (
        '  - resource: http://127.0.0.1:8014/api/chaba/pending\n'
        '    headers:\n'
        '      X-Api-Key: !secret chaba_api_key\n'
        '    scan_interval: 20\n'
        '    sensor:\n'
        '      - name: "Chaba pending guests"\n'
        '        unique_id: chaba_pending_guests\n'
        '        value_template: "{{ value_json.pending | length }}"\n'
        '        json_attributes:\n'
        '          - pending\n'
    )
    src = src[:rest.end(1)] + entry + src[rest.end(1):]
    print("added chaba_pending_guests sensor")

cfg.write_text(src)

# --- scripts.yaml: replace chaba_guest_* blocks wholesale (idempotent update)
sp = pathlib.Path.home() / ".config/home-assistant/scripts.yaml"
s = sp.read_text()
s = re.sub(r"\nchaba_guest_(promote|revoke|qr):\n(?:  .*\n|    .*\n|      .*\n|        .*\n|          .*\n)+", "\n", s)
s += '''
chaba_guest_promote:
  alias: "Chaba: promote guest"
  description: "Promote a pending guest to a named user."
  fields:
    name:
      name: Guest name
      required: true
  sequence:
    - action: rest_command.chaba_guest_promote
      data:
        name: "{{ name }}"

chaba_guest_revoke:
  alias: "Chaba: revoke guest"
  description: "Archive a guest/user's memory and drop live sessions."
  fields:
    name:
      name: Guest name
      required: true
  sequence:
    - action: rest_command.chaba_guest_revoke
      data:
        name: "{{ name }}"

chaba_guest_qr:
  alias: "Chaba: mint guest QR"
  description: "Mint a one-time HA auto-login bridge AND a fresh guest-chat redeem link; combined gate URL lands in input_text.chaba_guest_qr_url."
  sequence:
    - action: rest_command.chaba_ha_bridge_mint
      response_variable: bridge
    - action: rest_command.chaba_guest_reissue
      response_variable: chat
    - action: input_text.set_value
      target:
        entity_id: input_text.chaba_guest_qr_url
      data:
        value: "{{ bridge.response.gate_url }}&r={{ ('http://192.168.2.67:8126' ~ chat.response.redeem_url) | urlencode }}"
'''
    sp.write_text(s)
    print("chaba scripts merged")

# --- input_texts.yaml += qr url holder
ip = pathlib.Path.home() / ".config/home-assistant/input_texts.yaml"
i = ip.read_text()
if "chaba_guest_qr_url:" not in i:
    i += '''
chaba_guest_qr_url:
  name: "Chaba guest QR URL"
  max: 255
'''
    ip.write_text(i)
    print("added chaba_guest_qr_url input_text")
PY

# --- www files
cp ../tony-ha/www/chaba-gate.html "$HA_CFG/www/chaba-gate.html"
cp ../tony-ha/www/ada-users-card.js "$HA_CFG/www/ada-users-card.js"
echo "www files deployed"

# --- units + caddyfile
mkdir -p ~/.config/systemd/user ~/.config/chaba
cp Caddyfile.guest ~/.config/chaba/Caddyfile.guest
cp chaba-guest.service chaba-guest-lan.service ha-guest-lan.service ~/.config/systemd/user/
systemctl --user daemon-reload
systemctl --user enable --now chaba-guest.service chaba-guest-lan.service ha-guest-lan.service
systemctl --user --no-pager status chaba-guest.service | head -4

# --- HA restart (auth_providers + rest need it)
podman restart tony-ha
echo "tony-ha restarted — verify: curl -s http://127.0.0.1:8014/api/health"
