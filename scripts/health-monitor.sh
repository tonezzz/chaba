#!/usr/bin/env bash
# Health monitor — runs as a systemd user timer every 10 minutes.
# Multi-channel alerting for critical issues, logs to logs/health-monitor.log

set -euo pipefail

ALERT_LOG="/home/tony/CascadeProjects/chaba-tony-dell/logs/health-monitor.log"
mkdir -p "$(dirname "$ALERT_LOG")"

# Source notification plugins
SCRIPT_DIR="$(dirname "$0")"
export SCRIPT_DIR
source "$SCRIPT_DIR/health-monitor-notifications.sh"

ISSUES=()
ts=$(date '+%Y-%m-%d %H:%M:%S')

alert() {
    local severity="$1" title="$2" body="$3"
    send_notification "$severity" "$title" "$body"
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

# ── CPU frequency and throttling ─────────────────────────────────────────────
if [[ -d /sys/devices/system/cpu/cpu0/cpufreq ]]; then
    # Get current and max CPU frequency
    current_freq=$(cat /sys/devices/system/cpu/cpu0/cpufreq/scaling_cur_freq 2>/dev/null || echo 0)
    max_freq=$(cat /sys/devices/system/cpu/cpu0/cpufreq/scaling_max_freq 2>/dev/null || echo 0)
    
    if [[ $current_freq -gt 0 && $max_freq -gt 0 ]]; then
        current_mhz=$(( current_freq / 1000 ))
        max_mhz=$(( max_freq / 1000 ))
        freq_pct=$(( (current_freq * 100) / max_freq ))
        
        # Check if CPU is significantly below max frequency under load
        if [[ $load_pct -gt 50 && $freq_pct -lt 80 ]]; then
            alert warning "CPU Throttling Detected" "CPU at ${current_mhz}MHz (${freq_pct}% of ${max_mhz}MHz) under ${load_pct}% load"
        fi
        
        # Check if CPU is stuck at minimum frequency
        min_freq=$(cat /sys/devices/system/cpu/cpu0/cpufreq/scaling_min_freq 2>/dev/null || echo 0)
        if [[ $min_freq -gt 0 ]]; then
            min_mhz=$(( min_freq / 1000 ))
            if [[ $current_mhz -le $((min_mhz + 100)) && $load_pct -gt 10 ]]; then
                alert warning "CPU Frequency Low" "CPU stuck at ${current_mhz}MHz (near min ${min_mhz}MHz) under load"
            fi
        fi
    fi
    
    # Check CPU frequency scaling governor
    governor=$(cat /sys/devices/system/cpu/cpu0/cpufreq/scaling_governor 2>/dev/null || echo "unknown")
    if [[ "$governor" == "powersave" || "$governor" == "conservative" ]]; then
        alert info "CPU Governor" "Using ${governor} governor (may limit performance)"
    fi
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
    [status-api]="http://100.68.142.13:8000/health"
    [yomi-api]="http://100.68.142.13:3000/api/yomi/health"
    [caddy]="http://tony-dell:8080/"
)
for name in "${!SERVICE_URLS[@]}"; do
    url="${SERVICE_URLS[$name]}"
    code=$(curl -s -o /dev/null -w "%{http_code}" --connect-timeout 3 "$url" 2>/dev/null || echo "000")
    if [[ "$code" != "200" ]]; then
        alert critical "Service Down" "${name} returned HTTP ${code} — ${url}"
    fi
done

# ── Barrier client on tony-dell ─────────────────────────────────────────────
client_pid=$(ssh -o ConnectTimeout=3 -o BatchMode=yes tony@tony-dell 'pgrep -x barrierc' 2>/dev/null || true)
if [[ -z "$client_pid" ]]; then
    alert warning "Barrier Client Missing" "barrierc not running on tony-dell — restarting via ssh"
    ssh -o ConnectTimeout=3 -o BatchMode=yes tony@tony-dell 'pkill -x barrierc 2>/dev/null; nohup /home/tony/.local/bin/barrierc --no-daemon --disable-crypto --name tony-dell --log /tmp/barrier-client.log 100.75.102.88 >/dev/null 2>&1 &' >/dev/null 2>&1 || true
else
    client_log=$(ssh -o ConnectTimeout=3 -o BatchMode=yes tony@tony-dell 'tail -n 10 /tmp/barrier-client.log' 2>/dev/null || true)
    if ! grep -q "connected to server" <<< "$client_log" 2>/dev/null; then
        alert warning "Barrier Client Not Connected" "barrierc on tony-dell is not connected — restarting"
        ssh -o ConnectTimeout=3 -o BatchMode=yes tony@tony-dell 'pkill -x barrierc 2>/dev/null; nohup /home/tony/.local/bin/barrierc --no-daemon --disable-crypto --name tony-dell --log /tmp/barrier-client.log 100.75.102.88 >/dev/null 2>&1 &' >/dev/null 2>&1 || true
    fi
fi

# ── Barrier server on tony-omen ─────────────────────────────────────────────
if ! systemctl --user is-active barriers.service >/dev/null 2>&1; then
    alert warning "Barrier Server Not Running" "barriers.service is not active — starting"
    systemctl --user start barriers.service || true
fi

# ── Google Drive backup mount ───────────────────────────────────────────────
if ! mountpoint -q /home/tony/GoogleDrive; then
    alert critical "Google Drive Not Mounted" "Backup storage unavailable — remount with: rclone mount gdrive: /home/tony/GoogleDrive --daemon"
fi

# Check backup directory accessibility
if [[ -d "/home/tony/GoogleDrive/Tony AI/backup/chaba" ]]; then
    if ! touch "/home/tony/GoogleDrive/Tony AI/backup/chaba/.health-check" 2>/dev/null; then
        alert critical "Google Drive Not Writable" "Backup directory not writable — check mount and permissions"
    else
        rm -f "/home/tony/GoogleDrive/Tony AI/backup/chaba/.health-check" 2>/dev/null
    fi
else
    alert warning "Backup Directory Missing" "Backup directory not found — may need manual creation"
fi

# ── Summary log ─────────────────────────────────────────────────────────────
if [[ ${#ISSUES[@]} -eq 0 ]]; then
    echo "[$ts] OK — all checks passed" >> "$ALERT_LOG"
else
    echo "[$ts] ISSUES (${#ISSUES[@]}): ${ISSUES[*]}" >> "$ALERT_LOG"
fi

# ── Health snapshot ─────────────────────────────────────────────────────────
"$SCRIPT_DIR/health-snapshot.sh" >/dev/null 2>&1 || true

# Rotate log: keep last 500 lines
tail -500 "$ALERT_LOG" > "${ALERT_LOG}.tmp" && mv "${ALERT_LOG}.tmp" "$ALERT_LOG" 2>/dev/null || true
