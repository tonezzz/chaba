#!/usr/bin/env python3
"""Import wiki SQL file via MCP Wiki API"""

import re
import json
import urllib.request
import os

WIKI_API = os.getenv('WIKI_API', 'http://idc1.surf-thailand.com:3008')
SQL_FILE = '/home/chaba/chaba/services/assistance_data/wiki.sql'

def parse_inserts(filepath):
    """Parse INSERT statements from SQL file"""
    with open(filepath, 'r', encoding='utf-8') as f:
        lines = f.readlines()

    articles = []
    i = 0
    while i < len(lines):
        line = lines[i]
        if 'INSERT INTO articles' in line and 'VALUES' not in line:
            i += 1
            if i < len(lines) and 'VALUES (' in lines[i]:
                value_lines = [lines[i]]
                i += 1
                while i < len(lines) and 'ON CONFLICT' not in lines[i]:
                    value_lines.append(lines[i])
                    i += 1
                value_text = ''.join(value_lines)
                article = parse_insert_value(value_text)
                if article:
                    articles.append(article)
        i += 1

    return articles

def parse_insert_value(value_text):
    """Parse a single INSERT VALUES clause"""
    # Remove VALUES (
    value_text = value_text.replace('VALUES (', '')

    # Find title
    title_match = re.search(r"^'([^']+)',", value_text)
    if not title_match:
        return None
    title = title_match.group(1)

    remaining = value_text[title_match.end():].strip()

    # Find content - everything between title and ARRAY[
    content_match = re.search(r"^'([\s\S]*?)',\s*ARRAY\[", remaining)
    if not content_match:
        return None
    content = content_match.group(1)

    remaining = remaining[content_match.end() - len('ARRAY['):]

    # Find tags
    tags_match = re.search(r"ARRAY\[([^\]]*)\]", remaining)
    tags = []
    if tags_match:
        tags_str = tags_match.group(1)
        for tag in re.findall(r"'([^']*)'", tags_str):
            if tag.strip():
                tags.append(tag.strip())

    # Find timestamps
    time_match = re.search(r"'(\d{4}-\d{2}-\d{2}[\s\d:\.]+)',\s*'(\d{4}-\d{2}-\d{2}[\s\d:\.]+)'", remaining)
    created_at = time_match.group(1) if time_match else '2026-04-10 00:00:00'
    updated_at = time_match.group(2) if time_match else '2026-04-10 00:00:00'

    return {
        'title': title,
        'content': content,
        'tags': tags,
        'created_at': created_at,
        'updated_at': updated_at
    }

def wiki_create(title, content, tags):
    """Create article via wiki API"""
    url = f"{WIKI_API}/api/articles"
    data = {
        'title': title,
        'content': content,
        'tags': ','.join(tags) if tags else ''
    }

    req = urllib.request.Request(
        url,
        data=json.dumps(data).encode('utf-8'),
        headers={'Content-Type': 'application/json'},
        method='POST'
    )

    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            return json.loads(resp.read().decode('utf-8'))
    except urllib.error.HTTPError as e:
        if e.code == 409:  # Article exists
            return {'exists': True}
        raise

def main():
    print("=== Wiki SQL Import via API ===\n")

    articles = parse_inserts(SQL_FILE)
    print(f"Found {len(articles)} articles to import\n")

    if not articles:
        print("No articles found!")
        return

    migrated = 0
    skipped = 0
    errors = 0

    for article in articles:
        try:
            result = wiki_create(article['title'], article['content'], article['tags'])
            if result.get('exists'):
                print(f"  ⚠ Skipping (exists): {article['title'][:50]}")
                skipped += 1
            else:
                print(f"  ✅ Migrated: {article['title'][:50]}")
                migrated += 1
        except Exception as e:
            print(f"  ❌ Error with '{article['title'][:30]}': {e}")
            errors += 1

    print(f"\n=== Import Complete ===")
    print(f"Migrated: {migrated}, Skipped: {skipped}, Errors: {errors}")
    print(f"\nVerify at: {WIKI_API}/")

if __name__ == "__main__":
    main()
