#!/bin/bash
set -e

echo "🔄 Creating MDDB backup using native API..."

# Variables
MDBB_DIR="/home/tony/CascadeProjects/chaba-kbman/stacks/web/mddb"
BACKUP_DIR="$MDBB_DIR/backups"
TIMESTAMP=$(date +%Y%m%d-%H%M%S)
BACKUP_NAME="backup-$TIMESTAMP.db"

# Create backup directory
mkdir -p "$BACKUP_DIR"

# Create backup using native API
echo "💾 Creating backup via MDDB API..."
curl -X GET "http://localhost:11023/v1/backup?to=$BACKUP_NAME" > /dev/null

# Copy backup from container to host
echo "📥 Copying backup to host..."
docker cp mddb:/app/backups/$BACKUP_NAME "$BACKUP_DIR/"

# Copy backup to Google Drive
echo "☁️  Syncing to Google Drive..."
rclone copy "$BACKUP_DIR/$BACKUP_NAME" "gdrive:Tony AI/mddb/"

# Clean up old backups (keep last 7 days)
echo "🧹 Cleaning old backups..."
find "$BACKUP_DIR" -name "backup-*.db" -mtime +7 -delete

# Clean up container backup
docker exec mddb rm /app/backups/$BACKUP_NAME

echo "✅ MDDB backup completed using native API"
echo "📍 Location: $BACKUP_DIR/$BACKUP_NAME"
echo "📅 Timestamp: $TIMESTAMP"
echo "☁️  Google Drive: Tony AI/mddb/$BACKUP_NAME"