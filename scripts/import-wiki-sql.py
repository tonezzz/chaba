#!/usr/bin/env python3
"""Import wiki SQL file into PostgreSQL with proper escaping"""

import re
import psycopg2
import os

PG_HOST = os.getenv('PG_HOST', 'localhost')
PG_PORT = int(os.getenv('PG_PORT', '5432'))
PG_DATABASE = os.getenv('PG_DATABASE', 'chaba')
PG_USER = os.getenv('PG_USER', 'chaba')
PG_PASSWORD = os.getenv('PG_PASSWORD', 'changeme')
SQL_FILE = '/home/chaba/chaba/services/assistance_data/wiki.sql'

def parse_inserts(filepath):
    """Parse INSERT statements from SQL file by reading line by line"""
    with open(filepath, 'r', encoding='utf-8') as f:
        lines = f.readlines()

    articles = []
    i = 0
    while i < len(lines):
        line = lines[i]
        # Look for INSERT INTO line
        if 'INSERT INTO articles' in line and 'VALUES' not in line:
            # Next line should be VALUES
            i += 1
            if i < len(lines) and 'VALUES (' in lines[i]:
                # Collect all lines until ON CONFLICT
                value_lines = [lines[i]]
                i += 1
                while i < len(lines) and 'ON CONFLICT' not in lines[i]:
                    value_lines.append(lines[i])
                    i += 1
                # Now we have all lines for this INSERT
                value_text = ''.join(value_lines)
                article = parse_insert_value(value_text)
                if article:
                    articles.append(article)
        i += 1

    return articles

def parse_insert_value(value_text):
    """Parse a single INSERT VALUES clause"""
    # Remove VALUES ( and trailing )
    value_text = value_text.strip()
    if value_text.startswith('VALUES ('):
        value_text = value_text[8:]  # Remove 'VALUES ('

    # Find the split points: we need to extract:
    # 1. title (first single-quoted string)
    # 2. content (second single-quoted string, multi-line)
    # 3. tags (ARRAY[...])
    # 4. entities (NULL)
    # 5. classification (NULL)
    # 6. created_at (timestamp)
    # 7. updated_at (timestamp)

    # Pattern to match the VALUES structure
    # The tricky part is content can contain almost anything
    pattern = r"^'([^']+)',\s*'([\s\S]*?)',\s*(ARRAY\[[^\]]*\]|NULL),\s*(NULL),\s*(NULL),\s*'([^']+)',\s*'([^']+)'\)?$"

    match = re.match(pattern, value_text, re.DOTALL)
    if not match:
        # Try simpler approach - find key markers
        return parse_insert_simple(value_text)

    title, content, tags_str, _, _, created_at, updated_at = match.groups()

    # Parse tags
    tags = []
    if tags_str and tags_str.startswith('ARRAY['):
        tags_content = tags_str[6:-1]  # Remove ARRAY[ and ]
        # Split by comma, but handle quoted strings
        for tag in re.findall(r"'([^']*)'", tags_content):
            if tag.strip():
                tags.append(tag.strip())

    return {
        'title': title.strip(),
        'content': content,
        'tags': tags,
        'created_at': created_at,
        'updated_at': updated_at
    }

def parse_insert_simple(value_text):
    """Simple parser that finds markers in the value text"""
    try:
        # Find title: first '...',
        title_match = re.search(r"^'([^']+)',", value_text)
        if not title_match:
            return None
        title = title_match.group(1)

        # Find the position after title
        pos = title_match.end()
        remaining = value_text[pos:].strip()

        # Find content: next '...', (ends before ARRAY[)
        # Content is everything between title's closing quote and the ARRAY[ marker
        content_match = re.search(r"^'([\s\S]*?)',\s*ARRAY\[", remaining)
        if not content_match:
            # Try finding by NULL markers instead
            content_match = re.search(r"^'([\s\S]*?)',\s*NULL,\s*NULL,\s*NULL", remaining)
        if not content_match:
            return None
        content = content_match.group(1)

        # Find remaining after content
        after_content = remaining[content_match.end() - len("ARRAY[") - 1:]

        # Find tags: ARRAY[...],
        tags_match = re.search(r"ARRAY\[([^\]]*)\]", after_content)
        tags = []
        if tags_match:
            tags_str = tags_match.group(1)
            for tag in re.findall(r"'([^']*)'", tags_str):
                if tag.strip():
                    tags.append(tag.strip())

        # Find timestamps: '...', '...'
        time_match = re.search(r"'(\d{4}-\d{2}-\d{2}[\s\d:\.]+)',\s*'?(\d{4}-\d{2}-\d{2}[\s\d:\.]+)'?", after_content)
        if time_match:
            created_at = time_match.group(1)
            updated_at = time_match.group(2)
        else:
            created_at = updated_at = '2026-04-10 00:00:00'

        return {
            'title': title,
            'content': content,
            'tags': tags,
            'created_at': created_at,
            'updated_at': updated_at
        }
    except Exception as e:
        print(f"Parse error: {e}")
        return None

def main():
    print("=== Wiki SQL Import ===")
    print("")

    # Parse articles from SQL
    print("Parsing SQL file...")
    articles = parse_inserts(SQL_FILE)
    print(f"Found {len(articles)} articles to import")
    print("")

    if not articles:
        print("No articles found!")
        return

    # Connect to PostgreSQL
    print("Connecting to PostgreSQL...")
    conn = psycopg2.connect(
        host=PG_HOST,
        port=PG_PORT,
        database=PG_DATABASE,
        user=PG_USER,
        password=PG_PASSWORD
    )
    cur = conn.cursor()
    print("Connected!")
    print("")

    # Import articles
    migrated = 0
    skipped = 0
    errors = 0

    for article in articles:
        try:
            # Check if exists
            cur.execute("SELECT 1 FROM articles WHERE title = %s", (article['title'],))
            if cur.fetchone():
                print(f"  ⚠ Skipping (exists): {article['title'][:50]}")
                skipped += 1
                continue

            # Insert
            cur.execute('''
                INSERT INTO articles (title, content, tags, entities, classification, created_at, updated_at)
                VALUES (%s, %s, %s, NULL, NULL, %s, %s)
            ''', (
                article['title'],
                article['content'],
                article['tags'],
                article['created_at'],
                article['updated_at']
            ))
            conn.commit()
            print(f"  ✅ Migrated: {article['title'][:50]}")
            migrated += 1

        except Exception as e:
            print(f"  ❌ Error with '{article['title'][:30]}': {e}")
            errors += 1
            conn.rollback()

    cur.close()
    conn.close()

    print("")
    print("=== Import Complete ===")
    print(f"Migrated: {migrated}, Skipped: {skipped}, Errors: {errors}")

if __name__ == "__main__":
    main()
