#!/usr/bin/env python3
import sqlite3
import sys

def export_sql(db_path):
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    cur = conn.cursor()
    cur.execute('SELECT title, content, tags, created_at, updated_at FROM articles ORDER BY title')
    rows = cur.fetchall()
    
    print(f'-- mcp-wiki export: {len(rows)} articles')
    print('-- Run this on idc1 to import into PostgreSQL')
    print()
    
    for row in rows:
        title = row['title'].replace("'", "''")
        content = (row['content'] or '').replace("'", "''")
        tags = (row['tags'] or '').replace("'", "''")
        created = row['created_at'] or 'NOW()'
        updated = row['updated_at'] or 'NOW()'
        
        # Convert tags to PostgreSQL array format
        if tags:
            tag_list = ", ".join([f'"{t.strip()}"' for t in tags.split(',')])
            tags_arr = f'ARRAY[{tag_list}]'
        else:
            tags_arr = 'NULL'
        
        print(f"INSERT INTO articles (title, content, tags, entities, classification, created_at, updated_at)")
        print(f"VALUES ('{title}', '{content}', {tags_arr}, NULL, NULL, '{created}', '{updated}')")
        print(f"ON CONFLICT (title) DO NOTHING;")
        print()
    
    conn.close()

if __name__ == '__main__':
    db_path = sys.argv[1] if len(sys.argv) > 1 else '/data/wiki.db'
    export_sql(db_path)
