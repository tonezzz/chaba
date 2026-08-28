#!/bin/bash
set -e

BACKUP_DIR="/backup/mddb"
TIMESTAMP=$(date +%Y%m%d-%H%M%S)
RETENTION_DAYS=30

echo "🔄 Starting MDDB backup..."

# Create backup directory
mkdir -p "$BACKUP_DIR"

# Backup MDDB data volume
echo "💾 Backing up MDDB data volume..."
docker run --rm \
  -v mddb-data:/data \
  -v "$BACKUP_DIR:/backup" \
  alpine tar czf "/backup/mddb-data-$TIMESTAMP.tar.gz" -C /data .

# Backup vaults directory
echo "📁 Backing up MDDB vaults..."
tar czf "$BACKUP_DIR/mddb-vaults-$TIMESTAMP.tar.gz" \
  /home/tony/CascadeProjects/chaba-kbman/stacks/web/mddb/vaults

# Backup configuration
echo "⚙️  Backing up MDDB configuration..."
tar czf "$BACKUP_DIR/mddb-config-$TIMESTAMP.tar.gz" \
  /home/tony/CascadeProjects/chaba-kbman/stacks/web/mddb/config

# Clean old backups
echo "🧹 Cleaning old backups (older than $RETENTION_DAYS days)..."
find "$BACKUP_DIR" -name "mddb-*.tar.gz" -mtime +$RETENTION_DAYS -delete

# Verify backup
echo "✅ Verifying backup..."
LATEST_BACKUP=$(ls -t "$BACKUP_DIR"/mddb-data-*.tar.gz | head -1)
if tar tzf "$LATEST_BACKUP" > /dev/null 2>&1; then
    echo "✅ Backup verification successful"
    echo "📊 Backup size: $(du -h "$LATEST_BACKUP" | cut -f1)"
else
    echo "❌ Backup verification failed"
    exit 1
fi

echo "🎉 MDDB backup completed successfully"
echo "📍 Backup location: $BACKUP_DIR"
echo "📅 Timestamp: $TIMESTAMP"