#!/bin/bash
set -e
pkill -f 'python3 /config/ha-live/bridge.py' || true
sleep 1
set -a
source /home/tony/.config/secrets/home-assistant-token.env
set +a
cd /home/tony/.config/home-assistant/ha-live
nohup podman exec -i -e HA_LONG_LIVED_TOKEN home-assistant python3 /config/ha-live/bridge.py > /home/tony/.config/home-assistant/ha-live/bridge.log 2>&1 &
echo 'ha-live bridge restarted'
