#!/usr/bin/env bash
# Health monitor notification plugins
# Provides multi-channel alerting capabilities

source "$(dirname "$0")/health-monitor-config.sh"

# Send desktop notification
notify_desktop() {
    local severity="$1" title="$2" body="$3"
    local icon="dialog-warning"
    [[ "$severity" == "critical" ]] && icon="dialog-error"
    
    DISPLAY=:0 DBUS_SESSION_BUS_ADDRESS="unix:path=/run/user/$(id -u)/bus" \
        notify-send --urgency="${severity/critical/critical}" \
            --icon="$icon" \
            --expire-time=15000 \
            "🔔 $title" "$body" 2>/dev/null || true
}

# Send email notification
notify_email() {
    local severity="$1" title="$2" body="$3"
    local subject="${EMAIL_SUBJECT_PREFIX} [${severity^^}] ${title}"
    
    if command -v mail &>/dev/null; then
        echo "$body" | mail -s "$subject" "$EMAIL_RECIPIENT" 2>/dev/null || true
    fi
}

# Send Yomi notification
notify_yomi() {
    local severity="$1" title="$2" body="$3"
    local message="🔔 [${severity^^}] ${title}: ${body}"
    
    if [[ -n "$YOMI_CHAT_ID" ]]; then
        curl -s -X POST "$YOMI_API_URL" \
            -H "Content-Type: application/json" \
            -d "{\"chatId\":\"$YOMI_CHAT_ID\",\"message\":\"$message\"}" 2>/dev/null || true
    fi
}

# Send Pushover notification
notify_pushover() {
    local severity="$1" title="$2" body="$3"
    
    if [[ -n "$PUSHOVER_USER_KEY" && -n "$PUSHOVER_API_TOKEN" ]]; then
        local priority="0"
        [[ "$severity" == "critical" ]] && priority="1"
        
        curl -s -X POST "https://api.pushover.net/1/messages.json" \
            -d "token=$PUSHOVER_API_TOKEN" \
            -d "user=$PUSHOVER_USER_KEY" \
            -d "title=$title" \
            -d "message=$body" \
            -d "priority=$priority" 2>/dev/null || true
    fi
}

# Main notification dispatcher
send_notification() {
    local severity="$1" title="$2" body="$3"
    local timestamp=$(date '+%Y-%m-%d %H:%M:%S')
    
    # Log all notifications
    echo "[$timestamp] $severity: $title — $body" >> "$ALERT_LOG"
    
    # Check rate limiting
    local alert_key="${severity}:${title}"
    local cooldown_file="/tmp/health-monitor-cooldown.txt"
    local last_sent=$(grep "^${alert_key}:" "$cooldown_file" 2>/dev/null | cut -d: -f2 || echo "0")
    local current_time=$(date +%s)
    
    if [[ $((current_time - last_sent)) -lt $ALERT_COOLDOWN ]]; then
        return 0  # Skip due to rate limiting
    fi
    
    # Update cooldown
    mkdir -p "$(dirname "$cooldown_file")"
    echo "${alert_key}:${current_time}" >> "$cooldown_file"
    
    # Send to enabled channels based on severity thresholds
    if [[ "$NOTIFY_DESKTOP" == "true" ]]; then
        if should_notify "$severity" "$DESKTOP_THRESHOLD"; then
            notify_desktop "$severity" "$title" "$body"
        fi
    fi
    
    if [[ "$NOTIFY_EMAIL" == "true" ]]; then
        if should_notify "$severity" "$EMAIL_THRESHOLD"; then
            notify_email "$severity" "$title" "$body"
        fi
    fi
    
    if [[ "$NOTIFY_YOMI" == "true" ]]; then
        if should_notify "$severity" "$YOMI_THRESHOLD"; then
            notify_yomi "$severity" "$title" "$body"
        fi
    fi
    
    if [[ "$NOTIFY_PUSHOVER" == "true" ]]; then
        if should_notify "$severity" "$PUSHOVER_THRESHOLD"; then
            notify_pushover "$severity" "$title" "$body"
        fi
    fi
}

# Check if severity meets threshold
should_notify() {
    local severity="$1" threshold="$2"
    local levels=("info" "warning" "critical")
    local severity_index=-1 threshold_index=-1
    
    for i in "${!levels[@]}"; do
        [[ "${levels[$i]}" == "$severity" ]] && severity_index=$i
        [[ "${levels[$i]}" == "$threshold" ]] && threshold_index=$i
    done
    
    [[ $severity_index -ge $threshold_index ]]
}