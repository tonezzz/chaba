#!/usr/bin/env bash
# Health monitor notification configuration
# Configure which notification channels to use for different severity levels

# Notification channels: desktop, email, yomi, pushover
# Enable/disable channels by setting to true/false

NOTIFY_DESKTOP=true
NOTIFY_EMAIL=false
NOTIFY_YOMI=false
NOTIFY_PUSHOVER=false

# Email configuration
EMAIL_RECIPIENT="tony@example.com"
EMAIL_SUBJECT_PREFIX="[Chaba Health Monitor]"

# Yomi API configuration
YOMI_API_URL="http://tony-omen.local:8080/api/yomi/send"
YOMI_CHAT_ID=""  # Set to specific chat ID or leave empty for default

# Pushover configuration
PUSHOVER_USER_KEY=""
PUSHOVER_API_TOKEN=""

# Severity thresholds for each channel
# Channels will only send notifications for severities at or above these levels
# Severity levels: info, warning, critical

DESKTOP_THRESHOLD="info"
EMAIL_THRESHOLD="warning"
YOMI_THRESHOLD="critical"
PUSHOVER_THRESHOLD="critical"

# Rate limiting (seconds between same alert)
ALERT_COOLDOWN=300  # 5 minutes