# Manual Data Migration to idc1-db

## Option 1: Automated Script (Recommended)

```powershell
# Run on pc1
.\scripts\migrate-to-idc1-db.ps1 -PgPassword "your_password"
```

## Option 2: Manual Export/Import

### Export from pc1-wiki (SQLite)

```powershell
# On pc1
sqlite3 C:\chaba\stacks\pc1-wiki\wiki.db ".mode csv" ".headers on" "SELECT * FROM articles;" > wiki_export.csv
```

### Import to idc1-db (PostgreSQL)

```bash
# On idc1
ssh chaba@idc1.surf-thailand.com

# Copy CSV to idc1 (from pc1 in another terminal)
scp wiki_export.csv chaba@idc1.surf-thailand.com:/tmp/

# Import
# Connect to PostgreSQL container
docker exec -i idc1-postgres psql -U chaba -d chaba << 'EOF'
-- Create temp table
CREATE TEMP TABLE temp_articles (
    title TEXT,
    content TEXT,
    tags TEXT,
    created_at TIMESTAMP,
    updated_at TIMESTAMP
);

-- Import CSV
COPY temp_articles FROM '/tmp/wiki_export.csv' WITH (FORMAT csv, HEADER true);

-- Insert into actual table (skip duplicates)
INSERT INTO articles (title, content, tags, created_at, updated_at)
SELECT title, content, 
       CASE WHEN tags IS NOT NULL THEN string_to_array(tags, ',') ELSE NULL END,
       COALESCE(created_at, NOW()),
       COALESCE(updated_at, NOW())
FROM temp_articles
ON CONFLICT (title) DO NOTHING;

-- Check results
SELECT COUNT(*) FROM articles;
EOF
```

## Option 3: API-Based Migration

If wiki is running on both pc1 and idc1:

```powershell
# PowerShell script to copy via API
$sourceUrl = "http://localhost:3008"
$targetUrl = "http://idc1.surf-thailand.com:3008"

# Get all articles from pc1
$articles = Invoke-RestMethod -Uri "$sourceUrl/api/articles" -Method GET

# Post each to idc1
foreach ($article in $articles) {
    $fullArticle = Invoke-RestMethod -Uri "$sourceUrl/api/articles/$($article.title)" -Method GET
    $body = @{
        title = $fullArticle.title
        content = $fullArticle.content
        tags = $fullArticle.tags -split ","
    } | ConvertTo-Json -Depth 10
    
    Invoke-RestMethod -Uri "$targetUrl/api/articles" -Method POST -Body $body -ContentType "application/json"
    Write-Host "Migrated: $($article.title)"
}
```

## Verify Migration

```bash
# On idc1
docker exec idc1-postgres psql -U chaba -d chaba -c "SELECT title, updated_at FROM articles ORDER BY updated_at DESC LIMIT 10;"
```

## Notes

- AutoAgent uses PostgreSQL directly now - no SQLite to migrate
- Wiki on pc1 can keep local SQLite or switch to shared PostgreSQL
- Duplicate titles are skipped during migration (ON CONFLICT DO NOTHING)
