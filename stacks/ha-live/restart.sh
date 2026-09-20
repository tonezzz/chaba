#!/bin/bash
set -e
systemctl --user restart ha-live.service
sleep 2
echo 'ha-live bridge restarted'
