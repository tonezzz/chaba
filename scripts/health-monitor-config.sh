#!/usr/bin/env bash
# Health monitor notification configuration
# Configure which notification channels to use for different severity levels

# Notification channels: desktop, email, yomi, pushover
# Enable/disable channels by setting to true/false

export NOTIFY_DESKTOP=true
export NOTIFY_EMAIL=false
export NOTIFY_YOMI=false
export NOTIFY_PUSHOVER=false

# Email configuration
export EMAIL_RECIPIENT="tony@example.com"
export EMAIL_SUBJECT_PREFIX="[Chaba Health Monitor]"

# Yomi API configuration
export YOMI_API_URL="http://tony-omen.local:8080/api/yomi/send"
export YOMI_CHAT_ID=""  # Set to specific chat ID or leave empty for default

# Pushover configuration
export PUSHOVER_USER_KEY=""
export PUSHOVER_API_TOKEN=""

# Severity thresholds for each channel
# Channels will only send notifications for severities at or above these levels
# Severity levels: info, warning, critical

export DESKTOP_THRESHOLD="info"
export EMAIL_THRESHOLD="warning"
export YOMI_THRESHOLD="critical"
export PUSHOVER_THRESHOLD="critical"

# Rate limiting (seconds between same alert)
export ALERT_COOLDOWN=300  # 5 minutes