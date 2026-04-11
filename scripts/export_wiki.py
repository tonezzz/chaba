#!/usr/bin/env python3
import sqlite3
import sys
import io

# Fix Windows console encoding
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')

def export_wiki(db_path):
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    cur = conn.cursor()
    cur.execute('SELECT title, content, tags, created_at, updated_at FROM articles ORDER BY title')
    rows = cur.fetchall()
    print(f'Total articles: {len(rows)}')
    for row in rows:
        print()
        print('--- ARTICLE: ' + row['title'] + ' ---')
        print('Tags: ' + (row['tags'] or ''))
        print('Created: ' + str(row['created_at']))
        print('Content:')
        print(row['content'])
        print('--- END ---')
    conn.close()

if __name__ == '__main__':
    db_path = sys.argv[1] if len(sys.argv) > 1 else '/data/wiki.db'
    export_wiki(db_path)
