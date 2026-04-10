#!/usr/bin/env pwsh
# Migrate data from pc1 SQLite to idc1 PostgreSQL

param(
    [string]$Idc1Host = "idc1.surf-thailand.com",
    [int]$PgPort = 5432,
    [string]$PgDatabase = "chaba",
    [string]$PgUser = "chaba",
    [string]$PgPassword = "changeme",
    [string]$WikiDbPath = "C:\chaba\stacks\pc1-wiki\wiki.db",
    [switch]$DryRun
)

$ErrorActionPreference = "Stop"

Write-Host "=== idc1-db Data Migration ===" -ForegroundColor Cyan
Write-Host ""

# Connection strings
$pgConnString = "postgresql://${PgUser}:${PgPassword}@${Idc1Host}:${PgPort}/${PgDatabase}"

# Test PostgreSQL connection
Write-Host "Testing PostgreSQL connection..." -ForegroundColor Yellow
try {
    $testResult = python3 -c "
import psycopg2
conn = psycopg2.connect(host='$Idc1Host', port=$PgPort, database='$PgDatabase', user='$PgUser', password='$PgPassword')
cur = conn.cursor()
cur.execute('SELECT version()')
print(f'PostgreSQL: {cur.fetchone()[0][:50]}...')
cur.close()
conn.close()
" 2>&1
    Write-Host "  ✅ Connected: $testResult" -ForegroundColor Green
} catch {
    Write-Host "  ❌ Connection failed: $($_.Exception.Message)" -ForegroundColor Red
    exit 1
}
Write-Host ""

# Migrate Wiki Data
if (Test-Path $WikiDbPath) {
    Write-Host "Found wiki database: $WikiDbPath" -ForegroundColor Green
    
    $wikiCount = python3 -c "
import sqlite3
conn = sqlite3.connect('$WikiDbPath')
cur = conn.cursor()
cur.execute('SELECT COUNT(*) FROM articles')
count = cur.fetchone()[0]
print(count)
conn.close()
" 2>&1
    
    Write-Host "  Wiki articles to migrate: $wikiCount" -ForegroundColor Yellow
    
    if ($wikiCount -gt 0 -and -not $DryRun) {
        Write-Host "  Migrating wiki articles..." -ForegroundColor Yellow
        
        $result = python3 -c "
import sqlite3
import psycopg2
from datetime import datetime

# Connect to SQLite
sqlite_conn = sqlite3.connect('$WikiDbPath')
sqlite_conn.row_factory = sqlite3.Row
sqlite_cur = sqlite_conn.cursor()

# Connect to PostgreSQL  
pg_conn = psycopg2.connect(host='$Idc1Host', port=$PgPort, database='$PgDatabase', user='$PgUser', password='$PgPassword')
pg_cur = pg_conn.cursor()

# Get all articles from SQLite
sqlite_cur.execute('SELECT title, content, tags, created_at, updated_at FROM articles')
articles = sqlite_cur.fetchall()

migrated = 0
skipped = 0
for row in articles:
    title = row['title']
    content = row['content']
    tags = row['tags'] if row['tags'] else None
    
    # Check if article exists in PostgreSQL
    pg_cur.execute('SELECT 1 FROM articles WHERE title = %s', (title,))
    if pg_cur.fetchone():
        print(f'  Skipping (exists): {title}')
        skipped += 1
        continue
    
    # Insert into PostgreSQL
    try:
        pg_cur.execute('''
            INSERT INTO articles (title, content, tags, entities, classification, created_at, updated_at)
            VALUES (%s, %s, %s, NULL, NULL, COALESCE(%s, NOW()), COALESCE(%s, NOW()))
        ''', (title, content, tags.split(',') if tags else [], row['created_at'], row['updated_at']))
        pg_conn.commit()
        print(f'  Migrated: {title}')
        migrated += 1
    except Exception as e:
        print(f'  Error migrating {title}: {e}')
        pg_conn.rollback()

sqlite_conn.close()
pg_conn.close()
print(f'\nMigrated: {migrated}, Skipped: {skipped}')
" 2>&1
        
        Write-Host ""
        Write-Host $result -ForegroundColor Green
    }
} else {
    Write-Host "Wiki database not found at: $WikiDbPath" -ForegroundColor Yellow
}
Write-Host ""

# Migrate AutoAgent KB Data (if SQLite file exists)
$autoagentDbPath = "C:\chaba\stacks\autoagent-test\autoagent.db"
if (Test-Path $autoagentDbPath) {
    Write-Host "Found autoagent database: $autoagentDbPath" -ForegroundColor Green
    Write-Host "  Note: AutoAgent now uses PostgreSQL directly, no migration needed" -ForegroundColor Gray
} else {
    Write-Host "No local autoagent SQLite database found (expected - uses PostgreSQL now)" -ForegroundColor Gray
}

Write-Host ""
Write-Host "=== Migration Complete ===" -ForegroundColor Cyan
Write-Host ""
Write-Host "Verify data in PostgreSQL:" -ForegroundColor Yellow
Write-Host "  psql -h $Idc1Host -p $PgPort -U $PgUser -d $PgDatabase -c 'SELECT COUNT(*) FROM articles;'" -ForegroundColor Gray
