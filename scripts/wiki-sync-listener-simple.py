#!/usr/bin/env python3
"""
Simplified PostgreSQL → Weaviate Sync Listener
Uses polling-based approach for better compatibility.

Usage:
    python wiki-sync-listener-simple.py          # Run continuously
    python wiki-sync-listener-simple.py --test   # Test once and exit
"""

import os
import sys
import json
import signal
import time
import argparse
import psycopg2
import weaviate
from datetime import datetime
from typing import Dict, Any, Optional

# Configuration
POSTGRES_URL = os.getenv('DATABASE_URL', 'postgresql://chaba:changeme@localhost:5432/chaba')
WEAVIATE_URL = os.getenv('WEAVIATE_URL', 'http://localhost:8082')
GEMINI_API_KEY = os.getenv('GEMINI_API_KEY')
LISTEN_CHANNEL = 'wiki_article_change'
POLL_INTERVAL = 1.0  # seconds between polls
RECONNECT_DELAY = 5


class SimpleWikiSyncListener:
    """Polls PostgreSQL for notifications and syncs to Weaviate."""
    
    def __init__(self):
        self.pg_conn = None
        self.weaviate_client = None
        self.running = False
        self.stats = {'synced': 0, 'deleted': 0, 'failed': 0}
        
    def connect(self):
        """Connect to PostgreSQL and Weaviate."""
        self.pg_conn = psycopg2.connect(POSTGRES_URL)
        self.pg_conn.set_isolation_level(psycopg2.extensions.ISOLATION_LEVEL_AUTOCOMMIT)
        print(f"✅ Connected to PostgreSQL")
        
        # Use weaviate-client v3
        import weaviate
        self.weaviate_client = weaviate.Client(WEAVIATE_URL)
        print(f"✅ Connected to Weaviate at {WEAVIATE_URL}")
    
    def get_article_from_db(self, article_id: int) -> Optional[Dict]:
        """Fetch article from PostgreSQL."""
        cursor = self.pg_conn.cursor()
        cursor.execute(
            "SELECT id, title, content, tags, updated_at FROM articles WHERE id = %s",
            (article_id,)
        )
        row = cursor.fetchone()
        cursor.close()
        
        if not row:
            return None
            
        return {
            'id': row[0],
            'title': row[1],
            'content': row[2],
            'tags': row[3] if isinstance(row[3], list) else (row[3].split(',') if row[3] else []),
            'updated_at': row[4]
        }
    
    def sync_to_weaviate(self, article: Dict) -> bool:
        """Sync article to Weaviate (without embeddings for simplicity)."""
        try:
            # Format date
            updated_at = article.get('updated_at')
            if updated_at:
                updated_at_str = updated_at.strftime('%Y-%m-%dT%H:%M:%SZ') if hasattr(updated_at, 'strftime') else str(updated_at)
            else:
                updated_at_str = datetime.utcnow().strftime('%Y-%m-%dT%H:%M:%SZ')
            
            data_object = {
                "title": article['title'],
                "content": article['content'][:5000],  # Limit content
                "tags": article['tags'][:10],  # Limit tags
                "wikidb_id": article['id'],
                "updated_at": updated_at_str
            }
            
            # Use dummy vector (all zeros) - Weaviate accepts this
            vector = [0.0] * 768
            
            # Check if exists
            result = self.weaviate_client.query.get(
                "WikiArticle", ["wikidb_id"]
            ).with_where({
                "path": ["wikidb_id"],
                "operator": "Equal",
                "valueInt": article['id']
            }).with_limit(1).do()
            
            if result and 'data' in result and result['data']['Get']['WikiArticle']:
                # Update
                uuid = result['data']['Get']['WikiArticle'][0]['_additional']['id']
                self.weaviate_client.data_object.update(
                    data_object=data_object,
                    class_name="WikiArticle",
                    uuid=uuid,
                    vector=vector
                )
                print(f"🔄 Updated: {article['title'][:50]}")
            else:
                # Create
                self.weaviate_client.data_object.create(
                    data_object=data_object,
                    class_name="WikiArticle",
                    vector=vector
                )
                print(f"✅ Created: {article['title'][:50]}")
            
            return True
            
        except Exception as e:
            print(f"❌ Failed: {article.get('title', 'unknown')[:50]} - {e}")
            self.stats['failed'] += 1
            return False
    
    def delete_from_weaviate(self, article_id: int, title: str) -> bool:
        """Delete article from Weaviate."""
        try:
            result = self.weaviate_client.query.get(
                "WikiArticle", ["wikidb_id"]
            ).with_where({
                "path": ["wikidb_id"],
                "operator": "Equal",
                "valueInt": article_id
            }).with_limit(1).do()
            
            if result and 'data' in result and result['data']['Get']['WikiArticle']:
                uuid = result['data']['Get']['WikiArticle'][0]['_additional']['id']
                self.weaviate_client.data_object.delete(
                    class_name="WikiArticle",
                    uuid=uuid
                )
                print(f"🗑️  Deleted: {title[:50]}")
                self.stats['deleted'] += 1
                return True
            return False
        except Exception as e:
            print(f"❌ Delete failed: {e}")
            return False
    
    def process_notifications(self):
        """Poll for and process notifications."""
        # Use a cursor to listen
        cursor = self.pg_conn.cursor()
        cursor.execute(f"LISTEN {LISTEN_CHANNEL};")
        
        # Check for notifications
        self.pg_conn.poll()
        
        count = 0
        while self.pg_conn.notifies:
            notify = self.pg_conn.notifies.pop(0)
            count += 1
            
            try:
                data = json.loads(notify.payload)
                op = data.get('op')
                article_id = data.get('id')
                title = data.get('title', 'unknown')
                
                print(f"\n📨 {op}: {title[:50]} (ID: {article_id})")
                
                if op == 'DELETE':
                    self.delete_from_weaviate(article_id, title)
                elif op in ('INSERT', 'UPDATE'):
                    article = self.get_article_from_db(article_id)
                    if article:
                        if self.sync_to_weaviate(article):
                            self.stats['synced'] += 1
                    else:
                        print(f"⚠️  Article not found in DB: {article_id}")
                        
            except json.JSONDecodeError as e:
                print(f"❌ Invalid JSON: {e}")
            except Exception as e:
                print(f"❌ Error: {e}")
        
        cursor.close()
        return count
    
    def run(self):
        """Main loop."""
        print(f"\n👂 Listening on: {LISTEN_CHANNEL}")
        print(f"   Poll interval: {POLL_INTERVAL}s")
        print("   Press Ctrl+C to stop\n")
        
        self.running = True
        
        while self.running:
            try:
                count = self.process_notifications()
                if count > 0:
                    print(f"   Processed {count} notification(s)")
                
                # Sleep before next poll
                time.sleep(POLL_INTERVAL)
                
            except KeyboardInterrupt:
                print("\n\n👋 Stopping...")
                self.running = False
            except Exception as e:
                print(f"❌ Error: {e}")
                time.sleep(RECONNECT_DELAY)
    
    def run_once(self):
        """Process pending and exit."""
        print("📨 Checking for pending notifications...")
        count = self.process_notifications()
        print(f"   Processed {count} notification(s)")
    
    def print_stats(self):
        """Print statistics."""
        print(f"\n{'='*50}")
        print(f"Sync Statistics")
        print(f"{'='*50}")
        print(f"  ✅ Synced:  {self.stats['synced']}")
        print(f"  🗑️  Deleted: {self.stats['deleted']}")
        print(f"  ❌ Failed:  {self.stats['failed']}")
        print(f"{'='*50}\n")
    
    def close(self):
        if self.pg_conn:
            self.pg_conn.close()
            print("✅ PostgreSQL closed")


def main():
    global POLL_INTERVAL
    
    parser = argparse.ArgumentParser()
    parser.add_argument('--test', action='store_true', help='Test once and exit')
    parser.add_argument('--interval', type=float, default=POLL_INTERVAL, help='Poll interval (seconds)')
    args = parser.parse_args()
    
    POLL_INTERVAL = args.interval
    
    listener = SimpleWikiSyncListener()
    
    try:
        listener.connect()
        
        if args.test:
            listener.run_once()
        else:
            listener.run()
            
    except KeyboardInterrupt:
        pass
    finally:
        listener.print_stats()
        listener.close()


if __name__ == "__main__":
    main()
