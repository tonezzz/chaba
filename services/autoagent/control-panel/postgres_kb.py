#!/usr/bin/env python3
"""
PostgreSQL Knowledge Base for AutoAgent
Replaces mcp-wiki HTTP API with direct PostgreSQL connection
"""

import os
import json
import re
import psycopg2
from psycopg2.extras import RealDictCursor
from typing import Optional, List, Dict, Tuple
from datetime import datetime
from contextlib import contextmanager


class PostgresKnowledgeBase:
    """PostgreSQL-based knowledge base for team documentation"""
    
    def __init__(self, database_url: str = None):
        self.database_url = database_url or os.getenv(
            "DATABASE_URL", 
            "postgresql://chaba:changeme@idc1.surf-thailand.com:5432/chaba"
        )
        self._init_tables()
    
    @contextmanager
    def _get_connection(self):
        """Get PostgreSQL connection context manager"""
        conn = psycopg2.connect(self.database_url)
        try:
            yield conn
            conn.commit()
        except Exception as e:
            conn.rollback()
            raise e
        finally:
            conn.close()
    
    def _init_tables(self):
        """Initialize knowledge base tables"""
        with self._get_connection() as conn:
            with conn.cursor() as cur:
                # Articles table (similar to mcp-wiki structure)
                cur.execute("""
                    CREATE TABLE IF NOT EXISTS kb_articles (
                        id SERIAL PRIMARY KEY,
                        title VARCHAR(255) UNIQUE NOT NULL,
                        content TEXT NOT NULL,
                        tags TEXT[],
                        entities JSONB,
                        classification VARCHAR(100),
                        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                        updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                    )
                """)
                
                # Search index
                cur.execute("""
                    CREATE INDEX IF NOT EXISTS idx_kb_articles_title 
                    ON kb_articles USING gin(to_tsvector('english', title))
                """)
                cur.execute("""
                    CREATE INDEX IF NOT EXISTS idx_kb_articles_content 
                    ON kb_articles USING gin(to_tsvector('english', content))
                """)
                cur.execute("""
                    CREATE INDEX IF NOT EXISTS idx_kb_articles_tags 
                    ON kb_articles USING gin(tags)
                """)
    
    def search(self, query: str, limit: int = 10) -> List[Dict]:
        """Search articles by title or content using full-text search"""
        with self._get_connection() as conn:
            with conn.cursor(cursor_factory=RealDictCursor) as cur:
                cur.execute("""
                    SELECT id, title, content, tags, created_at, updated_at,
                           ts_rank(to_tsvector('english', title || ' ' || content), 
                                   plainto_tsquery('english', %s)) as rank
                    FROM kb_articles
                    WHERE to_tsvector('english', title || ' ' || content) 
                          @@ plainto_tsquery('english', %s)
                    ORDER BY rank DESC, updated_at DESC
                    LIMIT %s
                """, (query, query, limit))
                return [dict(row) for row in cur.fetchall()]
    
    def get_article(self, title: str) -> Optional[Dict]:
        """Get article by exact title match"""
        with self._get_connection() as conn:
            with conn.cursor(cursor_factory=RealDictCursor) as cur:
                cur.execute("""
                    SELECT * FROM kb_articles WHERE title = %s
                """, (title,))
                row = cur.fetchone()
                return dict(row) if row else None
    
    def create_article(self, title: str, content: str, tags: List[str] = None,
                      entities: Dict = None, classification: str = None) -> Dict:
        """Create new article"""
        with self._get_connection() as conn:
            with conn.cursor(cursor_factory=RealDictCursor) as cur:
                cur.execute("""
                    INSERT INTO kb_articles (title, content, tags, entities, classification)
                    VALUES (%s, %s, %s, %s, %s)
                    RETURNING *
                """, (title, content, tags or [], json.dumps(entities) if entities else None, classification))
                return dict(cur.fetchone())
    
    def update_article(self, title: str, content: str, tags: List[str] = None,
                       entities: Dict = None, classification: str = None) -> Optional[Dict]:
        """Update existing article"""
        with self._get_connection() as conn:
            with conn.cursor(cursor_factory=RealDictCursor) as cur:
                cur.execute("""
                    UPDATE kb_articles
                    SET content = %s, tags = %s, entities = %s, classification = %s,
                        updated_at = CURRENT_TIMESTAMP
                    WHERE title = %s
                    RETURNING *
                """, (content, tags or [], json.dumps(entities) if entities else None, classification, title))
                row = cur.fetchone()
                return dict(row) if row else None

    def save_article(self, title: str, content: str, tags: List[str] = None,
                     entities: List[str] = None, classification: str = None) -> Dict:
        """Create or update article (convenience method matching WikiKnowledgeBase interface)"""
        # Convert entities list to dict if needed
        entities_dict = {"entities": entities} if entities else None

        # Try update first, if fails create new
        result = self.update_article(title, content, tags, entities_dict, classification)
        if result:
            return result
        return self.create_article(title, content, tags, entities_dict, classification)

    def list_articles(self, limit: int = 20, offset: int = 0) -> List[Dict]:
        """List recent articles"""
        with self._get_connection() as conn:
            with conn.cursor(cursor_factory=RealDictCursor) as cur:
                cur.execute("""
                    SELECT id, title, tags, created_at, updated_at
                    FROM kb_articles
                    ORDER BY updated_at DESC
                    LIMIT %s OFFSET %s
                """, (limit, offset))
                return [dict(row) for row in cur.fetchall()]
    
    def delete_article(self, title: str) -> bool:
        """Delete article by title"""
        with self._get_connection() as conn:
            with conn.cursor() as cur:
                cur.execute("DELETE FROM kb_articles WHERE title = %s", (title,))
                return cur.rowcount > 0
    
    def get_by_tag(self, tag: str, limit: int = 20) -> List[Dict]:
        """Get articles by tag"""
        with self._get_connection() as conn:
            with conn.cursor(cursor_factory=RealDictCursor) as cur:
                cur.execute("""
                    SELECT id, title, content, tags, created_at, updated_at
                    FROM kb_articles
                    WHERE %s = ANY(tags)
                    ORDER BY updated_at DESC
                    LIMIT %s
                """, (tag, limit))
                return [dict(row) for row in cur.fetchall()]


# Backward compatibility - same interface as WikiKnowledgeBase
KnowledgeBase = PostgresKnowledgeBase


if __name__ == "__main__":
    # Test the knowledge base
    kb = PostgresKnowledgeBase()
    
    # Create test article
    print("Creating test article...")
    article = kb.create_article(
        title="Test Article",
        content="This is a test article for the PostgreSQL knowledge base.",
        tags=["test", "postgres"],
        classification="test"
    )
    print(f"Created: {article['title']}")
    
    # Search
    print("\nSearching for 'test'...")
    results = kb.search("test")
    for r in results:
        print(f"  - {r['title']} (rank: {r['rank']:.2f})")
    
    # List all
    print("\nListing all articles...")
    articles = kb.list_articles()
    for a in articles:
        print(f"  - {a['title']} ({a['updated_at']})")
