#!/bin/bash
set -e
pkill -f 'python3 /config/ha-live/bridge.py' || true
sleep 1
source /home/tony/.config/secrets/home-assistant-token.env
cd /home/tony/.config/home-assistant/ha-live
nohup podman exec -e "HA_LONG_LIVED_TOKEN=$HA_LONG_LIVED_TOKEN" home-assistant python3 /config/ha-live/bridge.py > /home/tony/.config/home-assistant/ha-live/bridge.log 2>&1 &
sleep 2
echo 'ha-live bridge restarted'
