#!/bin/bash
set -e

echo "🔄 Restoring MDDB from Google Drive..."

# Variables
MDBB_DIR="/home/tony/CascadeProjects/chaba-kbman/stacks/web/mddb"
GDRIVE_REMOTE="gdrive"
GDRIVE_FOLDER="Tony AI/mddb"

# Check if rclone is configured for gdrive
if ! rclone listremotes | grep -q "^$GDRIVE_REMOTE:"; then
    echo "❌ Google Drive remote '$GDRIVE_REMOTE' not configured in rclone"
    exit 1
fi

# Stop MDDB container
echo "🛑 Stopping MDDB container..."
cd "$MDBB_DIR"
docker compose down

# Restore vaults directory
echo "📁 Restoring vaults directory..."
rclone sync "$GDRIVE_REMOTE:$GDRIVE_FOLDER/vaults" "$MDBB_DIR/vaults" \
  --progress

# Restore config directory
echo "⚙️  Restoring config directory..."
rclone sync "$GDRIVE_REMOTE:$GDRIVE_FOLDER/config" "$MDBB_DIR/config" \
  --progress

# Find latest database backup
echo "💾 Finding latest database backup..."
LATEST_DB=$(rclone lsf "$GDRIVE_REMOTE:$GDRIVE_FOLDER" --files-only | grep "mddb-db-" | tail -1)

if [ -n "$LATEST_DB" ]; then
    echo "📥 Downloading database backup: $LATEST_DB"
    rclone copy "$GDRIVE_REMOTE:$GDRIVE_FOLDER/$LATEST_DB" /tmp/

    # Extract database backup
    echo "📦 Extracting database backup..."
    docker run --rm \
      -v mddb_mddb-data:/data \
      -v /tmp:/backup \
      alpine tar xzf "/backup/$LATEST_DB" -C /data
else
    echo "⚠️  No database backup found in Google Drive"
fi

# Start MDDB container
echo "🚀 Starting MDDB container..."
docker compose up -d

echo "✅ MDDB restore from Google Drive completed"