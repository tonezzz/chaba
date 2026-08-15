#!/bin/bash
set -e

echo "🔄 Syncing MDDB to Google Drive..."

# Variables
MDBB_DIR="/home/tony/CascadeProjects/chaba-kbman/stacks/web/mddb"
GDRIVE_REMOTE="gdrive"
GDRIVE_FOLDER="Tony AI/mddb"
TIMESTAMP=$(date +%Y%m%d-%H%M%S)

# Check if rclone is configured for gdrive
if ! rclone listremotes | grep -q "^$GDRIVE_REMOTE:"; then
    echo "❌ Google Drive remote '$GDRIVE_REMOTE' not configured in rclone"
    echo "Please configure rclone first:"
    echo "rclone config create $GDRIVE_REMOTE drive"
    exit 1
fi

# Create Google Drive folder if it doesn't exist
echo "📁 Ensuring Google Drive folder exists..."
rclone mkdir "$GDRIVE_REMOTE:$GDRIVE_FOLDER" 2>/dev/null || true

# Backup MDDB database
echo "💾 Backing up MDDB database..."
docker run --rm \
  -v mddb_mddb-data:/data:ro \
  -v /tmp:/backup \
  alpine tar czf "/backup/mddb-db-$TIMESTAMP.tar.gz" -C /data .

# Copy database backup to Google Drive
echo "☁️  Uploading database to Google Drive..."
rclone copy "/tmp/mddb-db-$TIMESTAMP.tar.gz" "$GDRIVE_REMOTE:$GDRIVE_FOLDER/"

# Sync vaults directory
echo "📁 Syncing vaults directory..."
rclone sync "$MDBB_DIR/vaults" "$GDRIVE_REMOTE:$GDRIVE_FOLDER/vaults" \
  --exclude ".DS_Store" \
  --exclude "node_modules/" \
  --exclude ".git/" \
  --progress

# Sync config directory
echo "⚙️  Syncing config directory..."
rclone sync "$MDBB_DIR/config" "$GDRIVE_REMOTE:$GDRIVE_FOLDER/config" \
  --progress

# Clean up local backup (ignore permission errors)
rm -f "/tmp/mddb-db-$TIMESTAMP.tar.gz" 2>/dev/null || true

echo "✅ MDDB sync to Google Drive completed"
echo "📍 Location: $GDRIVE_REMOTE:$GDRIVE_FOLDER"
echo "📅 Timestamp: $TIMESTAMP"