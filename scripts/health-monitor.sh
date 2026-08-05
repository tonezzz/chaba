#!/usr/bin/env bash
# Health monitor — runs as a systemd user timer every 10 minutes.
# Sends desktop notifications for critical issues, logs to logs/health-monitor.log

set -euo pipefail

ALERT_LOG="/home/tony/CascadeProjects/chaba/logs/health-monitor.log"
mkdir -p "$(dirname "$ALERT_LOG")"

ISSUES=()
ts=$(date '+%Y-%m-%d %H:%M:%S')

alert() {
    local severity="$1" title="$2" body="$3"
    local icon="dialog-warning"
    [[ "$severity" == "critical" ]] && icon="dialog-error"
    echo "[$ts] $severity: $title — $body" >> "$ALERT_LOG"
    # Desktop notification (works for the current X session)
    DISPLAY=:0 DBUS_SESSION_BUS_ADDRESS="unix:path=/run/user/$(id -u)/bus" \
        notify-send --urgency="${severity/critical/critical}" \
            --icon="$icon" \
            --expire-time=15000 \
            "🔔 $title" "$body" 2>/dev/null || true
    ISSUES+=("$severity: $title")
}

# ── Memory ──────────────────────────────────────────────────────────────────
read -r _ _ free _ _ avail < <(grep "^Mem:" /proc/meminfo || free -m | grep "^Mem:")
avail_mb=$(( $(awk '/^MemAvailable:/{print $2}' /proc/meminfo) / 1024 ))
swap_total=$(awk '/^SwapTotal:/{print $2}' /proc/meminfo)
swap_free=$(awk '/^SwapFree:/{print $2}' /proc/meminfo)
if [[ $swap_total -gt 0 ]]; then
    swap_used_pct=$(( (swap_total - swap_free) * 100 / swap_total ))
else
    swap_used_pct=0
fi

if [[ $avail_mb -lt 1024 ]]; then
    alert critical "Memory Critical" "${avail_mb}MB available — system may become unresponsive"
elif [[ $avail_mb -lt 2048 ]]; then
    alert warning "Memory Low" "${avail_mb}MB available"
fi

if [[ $swap_used_pct -gt 90 ]]; then
    alert critical "Swap Exhausted" "Swap ${swap_used_pct}% used — check for process leaks (run: docs/kb/yomi-mcp-process-leak.md)"
elif [[ $swap_used_pct -gt 80 ]]; then
    alert warning "Swap High" "Swap ${swap_used_pct}% used"
fi

# ── Disk ────────────────────────────────────────────────────────────────────
while IFS= read -r line; do
    pct=$(echo "$line" | awk '{print $5}' | tr -d '%')
    mp=$(echo "$line" | awk '{print $6}')
    if [[ $pct -gt 90 ]]; then
        alert critical "Disk Critical" "$mp at ${pct}% — free space urgently needed"
    elif [[ $pct -gt 85 ]]; then
        alert warning "Disk High" "$mp at ${pct}%"
    fi
done < <(df -h --output=pcent,target / /data 2>/dev/null | tail -n +2)

# ── CPU load ────────────────────────────────────────────────────────────────
load1=$(awk '{print $1}' /proc/loadavg)
nproc=$(nproc)
load_pct=$(echo "$load1 $nproc" | awk '{printf "%d", ($1/$2)*100}')
if [[ $load_pct -gt 200 ]]; then
    alert warning "CPU Load High" "Load ${load1} (${load_pct}% of ${nproc} cores)"
fi

# ── GPU temperature ─────────────────────────────────────────────────────────
if command -v nvidia-smi &>/dev/null; then
    gpu_temp=$(nvidia-smi --query-gpu=temperature.gpu --format=csv,noheader 2>/dev/null | head -1 | tr -d ' ')
    if [[ -n "$gpu_temp" && "$gpu_temp" =~ ^[0-9]+$ ]]; then
        if [[ $gpu_temp -gt 87 ]]; then
            alert critical "GPU Temperature Critical" "GPU at ${gpu_temp}°C — reduce workload or check cooling"
        elif [[ $gpu_temp -gt 83 ]]; then
            alert warning "GPU Temperature High" "GPU at ${gpu_temp}°C"
        fi
    fi
fi

# ── CPU temperature ─────────────────────────────────────────────────────────
max_cpu_temp=0
for f in /sys/class/thermal/thermal_zone*/temp; do
    t=$(cat "$f" 2>/dev/null || echo 0)
    t_c=$(( t / 1000 ))
    [[ $t_c -gt $max_cpu_temp ]] && max_cpu_temp=$t_c
done
if [[ $max_cpu_temp -gt 92 ]]; then
    alert warning "CPU Temperature High" "CPU at ${max_cpu_temp}°C"
fi

# ── Yomi MCP process leak ────────────────────────────────────────────────────
yomi_count=$(pgrep -f "yomi/mcpb/run.mjs" 2>/dev/null | wc -l)
# Count only orphaned ones (ppid=1)
orphaned=0
while IFS= read -r pid; do
    ppid=$(ps -o ppid= -p "$pid" 2>/dev/null | tr -d ' ')
    [[ "$ppid" == "1" ]] && (( orphaned++ )) || true
done < <(pgrep -f "yomi/mcpb/run.mjs" 2>/dev/null)
if [[ $orphaned -gt 8 ]]; then
    alert warning "Yomi Process Leak" "${orphaned} orphaned Yomi MCP instances — kill with: pkill -f 'yomi/mcpb/run.mjs'"
fi

# ── Key service health ───────────────────────────────────────────────────────
declare -A SERVICE_URLS=(
    [status-api]="http://tony-omen.local:8080/api/health"
    [yomi-api]="http://tony-omen.local:8080/api/yomi/health"
    [caddy]="http://tony-omen.local:8080/"
)
for name in "${!SERVICE_URLS[@]}"; do
    url="${SERVICE_URLS[$name]}"
    code=$(curl -s -o /dev/null -w "%{http_code}" --connect-timeout 3 "$url" 2>/dev/null || echo "000")
    if [[ "$code" != "200" ]]; then
        alert critical "Service Down" "${name} returned HTTP ${code} — ${url}"
    fi
done

# ── Summary log ─────────────────────────────────────────────────────────────
if [[ ${#ISSUES[@]} -eq 0 ]]; then
    echo "[$ts] OK — all checks passed" >> "$ALERT_LOG"
else
    echo "[$ts] ISSUES (${#ISSUES[@]}): ${ISSUES[*]}" >> "$ALERT_LOG"
fi

# Rotate log: keep last 500 lines
tail -500 "$ALERT_LOG" > "${ALERT_LOG}.tmp" && mv "${ALERT_LOG}.tmp" "$ALERT_LOG" 2>/dev/null || true
