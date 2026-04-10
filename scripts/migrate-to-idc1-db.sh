#!/bin/bash
# Migrate data from pc1 SQLite to idc1 PostgreSQL
# Run this on idc1 after copying wiki.db from pc1

set -e

# Configuration
PG_HOST="${PG_HOST:-localhost}"
PG_PORT="${PG_PORT:-5432}"
PG_DATABASE="${PG_DATABASE:-chaba}"
PG_USER="${PG_USER:-chaba}"
PG_PASSWORD="${PG_PASSWORD:-changeme}"
WIKI_DB_PATH="${WIKI_DB_PATH:-./wiki.db}"  # Copy from pc1 first
DRY_RUN="${DRY_RUN:-false}"

echo "=== idc1-db Data Migration ==="
echo ""

# Check if SQLite file exists
if [[ ! -f "$WIKI_DB_PATH" ]]; then
    echo "❌ Wiki database not found at: $WIKI_DB_PATH"
    echo ""
    echo "First, copy the database from pc1:"
    echo "  # On pc1 (PowerShell):"
    echo "  scp C:\chaba\stacks\pc1-wiki\wiki.db chaba@idc1.surf-thailand.com:/tmp/"
    echo ""
    echo "Then run: WIKI_DB_PATH=/tmp/wiki.db $0"
    exit 1
fi

# Test PostgreSQL connection
echo "Testing PostgreSQL connection..."
if ! PGPASSWORD="$PG_PASSWORD" psql -h "$PG_HOST" -p "$PG_PORT" -U "$PG_USER" -d "$PG_DATABASE" -c "SELECT version();" > /dev/null 2>&1; then
    echo "❌ Connection failed to PostgreSQL at $PG_HOST:$PG_PORT"
    exit 1
fi
echo "  ✅ Connected to PostgreSQL"
echo ""

# Count articles in SQLite
WIKI_COUNT=$(sqlite3 "$WIKI_DB_PATH" "SELECT COUNT(*) FROM articles;" 2>/dev/null || echo "0")
echo "Wiki articles to migrate: $WIKI_COUNT"
echo ""

if [[ "$WIKI_COUNT" -eq 0 ]]; then
    echo "No articles to migrate."
    exit 0
fi

if [[ "$DRY_RUN" == "true" ]]; then
    echo "🔍 DRY RUN - Preview of articles to migrate:"
    sqlite3 "$WIKI_DB_PATH" "SELECT title, updated_at FROM articles ORDER BY updated_at DESC LIMIT 5;"
    echo ""
    echo "To actually migrate, run without DRY_RUN=true"
    exit 0
fi

echo "Migrating wiki articles..."

python3 << EOF
import sqlite3
import psycopg2
import sys

pg_conn = None
sqlite_conn = None

try:
    # Connect to SQLite
    sqlite_conn = sqlite3.connect("$WIKI_DB_PATH")
    sqlite_conn.row_factory = sqlite3.Row
    sqlite_cur = sqlite_conn.cursor()

    # Connect to PostgreSQL
    pg_conn = psycopg2.connect(
        host="$PG_HOST",
        port=$PG_PORT,
        database="$PG_DATABASE",
        user="$PG_USER",
        password="$PG_PASSWORD"
    )
    pg_cur = pg_conn.cursor()

    # Get all articles from SQLite
    sqlite_cur.execute("SELECT title, content, tags, created_at, updated_at FROM articles")
    articles = sqlite_cur.fetchall()

    migrated = 0
    skipped = 0

    for row in articles:
        title = row['title']
        content = row['content']
        tags = row['tags'] if row['tags'] else None

        # Check if article exists in PostgreSQL
        pg_cur.execute("SELECT 1 FROM articles WHERE title = %s", (title,))
        if pg_cur.fetchone():
            print(f"  ⚠ Skipping (exists): {title}")
            skipped += 1
            continue

        # Insert into PostgreSQL
        try:
            tag_list = tags.split(',') if tags else []
            pg_cur.execute('''
                INSERT INTO articles (title, content, tags, entities, classification, created_at, updated_at)
                VALUES (%s, %s, %s, NULL, NULL, COALESCE(%s, NOW()), COALESCE(%s, NOW()))
            ''', (title, content, tag_list, row['created_at'], row['updated_at']))
            pg_conn.commit()
            print(f"  ✅ Migrated: {title}")
            migrated += 1
        except Exception as e:
            print(f"  ❌ Error migrating {title}: {e}")
            pg_conn.rollback()

    print(f"\n=== Migration Complete ===")
    print(f"Migrated: {migrated}, Skipped: {skipped}")

except Exception as e:
    print(f"\n❌ Migration failed: {e}")
    sys.exit(1)

finally:
    if sqlite_conn:
        sqlite_conn.close()
    if pg_conn:
        pg_conn.close()
EOF

echo ""
echo "Verify data in PostgreSQL:"
echo "  psql -h $PG_HOST -p $PG_PORT -U $PG_USER -d $PG_DATABASE -c 'SELECT COUNT(*) FROM articles;'"
