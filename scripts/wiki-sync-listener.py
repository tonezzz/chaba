#!/usr/bin/env python3
"""
PostgreSQL → Weaviate Real-time Sync Listener
Listens for NOTIFY events from PostgreSQL and syncs changes to Weaviate.

Usage:
    python wiki-sync-listener.py          # Run continuously
    python wiki-sync-listener.py --once   # Process pending and exit
    python wiki-sync-listener.py --daemon # Run as background daemon
"""

import os
import sys
import json
import signal
import select
import time
import argparse
import psycopg2
import psycopg2.extensions
import weaviate
from google.genai import Client as GeminiClient
from google.genai.types import EmbedContentConfig
from datetime import datetime
from typing import Dict, Any, Optional

# Configuration
POSTGRES_URL = os.getenv('DATABASE_URL', 'postgresql://chaba:changeme@localhost:5432/chaba')
WEAVIATE_URL = os.getenv('WEAVIATE_URL', 'http://localhost:8082')
GEMINI_API_KEY = os.getenv('GEMINI_API_KEY')
LISTEN_CHANNEL = 'wiki_article_change'
EMBEDDING_MODEL = 'text-embedding-004'
EMBEDDING_DIMENSION = 768
RECONNECT_DELAY = 5  # seconds


class WikiSyncListener:
    """Listens for PostgreSQL changes and syncs to Weaviate."""
    
    def __init__(self):
        self.pg_conn = None
        self.weaviate_client = None
        self.gemini_client = None
        self.running = False
        self.stats = {
            'synced': 0,
            'deleted': 0,
            'failed': 0,
            'errors': []
        }
        
    def connect(self):
        """Connect to PostgreSQL and Weaviate."""
        # PostgreSQL connection
        self.pg_conn = psycopg2.connect(POSTGRES_URL)
        self.pg_conn.set_isolation_level(psycopg2.extensions.ISOLATION_LEVEL_AUTOCOMMIT)
        print(f"✅ Connected to PostgreSQL")
        
        # Weaviate connection
        self.weaviate_client = weaviate.Client(WEAVIATE_URL)
        print(f"✅ Connected to Weaviate at {WEAVIATE_URL}")
        
        # Gemini client (for embeddings)
        if GEMINI_API_KEY:
            self.gemini_client = GeminiClient(api_key=GEMINI_API_KEY)
            print(f"✅ Connected to Gemini API")
        else:
            print(f"⚠️ No GEMINI_API_KEY - using dummy embeddings")
    
    def generate_embedding(self, text: str) -> list:
        """Generate embedding using Gemini API."""
        if not self.gemini_client:
            return [0.0] * EMBEDDING_DIMENSION
            
        try:
            truncated = text[:8000]
            response = self.gemini_client.models.embed_content(
                model=EMBEDDING_MODEL,
                contents=truncated,
                config=EmbedContentConfig(task_type="RETRIEVAL_DOCUMENT")
            )
            return response.embeddings[0].values
        except Exception as e:
            print(f"❌ Embedding generation failed: {e}")
            return [0.0] * EMBEDDING_DIMENSION
    
    def get_article_from_db(self, article_id: int) -> Optional[Dict]:
        """Fetch article details from PostgreSQL."""
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
        """Sync article to Weaviate."""
        try:
            # Generate embedding
            text_to_embed = f"{article['title']}\n\n{article['content'][:3000]}"
            vector = self.generate_embedding(text_to_embed)
            
            # Format date for RFC3339
            updated_at = article['updated_at']
            if updated_at:
                if hasattr(updated_at, 'tzinfo') and updated_at.tzinfo is None:
                    updated_at_str = updated_at.strftime('%Y-%m-%dT%H:%M:%SZ')
                else:
                    updated_at_str = updated_at.isoformat() if hasattr(updated_at, 'isoformat') else str(updated_at)
            else:
                updated_at_str = datetime.utcnow().strftime('%Y-%m-%dT%H:%M:%SZ')
            
            # Prepare data object
            data_object = {
                "title": article['title'],
                "content": article['content'],
                "tags": article['tags'],
                "wikidb_id": article['id'],
                "updated_at": updated_at_str
            }
            
            # Check if exists in Weaviate
            existing = self.weaviate_client.query.get(
                "WikiArticle", ["wikidb_id"]
            ).with_where({
                "path": ["wikidb_id"],
                "operator": "Equal",
                "valueInt": article['id']
            }).with_limit(1).do()
            
            if existing and 'data' in existing and existing['data']['Get']['WikiArticle']:
                # Update existing
                uuid = existing['data']['Get']['WikiArticle'][0]['_additional']['id']
                self.weaviate_client.data_object.update(
                    data_object=data_object,
                    class_name="WikiArticle",
                    uuid=uuid,
                    vector=vector
                )
                print(f"  🔄 Updated: {article['title'][:50]}")
            else:
                # Create new
                self.weaviate_client.data_object.create(
                    data_object=data_object,
                    class_name="WikiArticle",
                    vector=vector
                )
                print(f"  ✅ Created: {article['title'][:50]}")
            
            return True
            
        except Exception as e:
            print(f"  ❌ Failed to sync {article.get('title', 'unknown')}: {e}")
            self.stats['failed'] += 1
            self.stats['errors'].append(str(e))
            return False
    
    def delete_from_weaviate(self, article_id: int, title: str) -> bool:
        """Delete article from Weaviate."""
        try:
            # Find the object
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
                print(f"  🗑️  Deleted: {title[:50]}")
                self.stats['deleted'] += 1
                return True
            else:
                print(f"  ⚠️  Not found in Weaviate: {title[:50]}")
                return False
                
        except Exception as e:
            print(f"  ❌ Failed to delete {title}: {e}")
            self.stats['failed'] += 1
            return False
    
    def process_notification(self, payload: str):
        """Process a PostgreSQL notification."""
        try:
            data = json.loads(payload)
            op = data.get('op')
            article_id = data.get('id')
            title = data.get('title')
            
            print(f"\n📨 Notification: {op} article {article_id}")
            
            if op == 'DELETE':
                self.delete_from_weaviate(article_id, title)
            elif op in ('INSERT', 'UPDATE'):
                # Fetch full article from DB
                article = self.get_article_from_db(article_id)
                if article:
                    if self.sync_to_weaviate(article):
                        self.stats['synced'] += 1
                else:
                    print(f"  ⚠️  Article {article_id} not found in DB")
                    
        except json.JSONDecodeError as e:
            print(f"❌ Invalid JSON payload: {e}")
        except Exception as e:
            print(f"❌ Error processing notification: {e}")
    
    def listen(self):
        """Listen for PostgreSQL notifications."""
        cursor = self.pg_conn.cursor()
        cursor.execute(f"LISTEN {LISTEN_CHANNEL};")
        print(f"\n👂 Listening on channel: {LISTEN_CHANNEL}")
        print("   Press Ctrl+C to stop\n")
        
        self.running = True
        
        while self.running:
            try:
                # Wait for notification using select
                readable, _, _ = select.select([self.pg_conn], [], [], 1.0)
                
                if readable:
                    self.pg_conn.poll()
                    
                    while self.pg_conn.notifies:
                        notify = self.pg_conn.notifies.pop(0)
                        self.process_notification(notify.payload)
                        
            except psycopg2.OperationalError as e:
                print(f"⚠️ Connection lost: {e}")
                print(f"   Reconnecting in {RECONNECT_DELAY}s...")
                time.sleep(RECONNECT_DELAY)
                self.connect()
                cursor = self.pg_conn.cursor()
                cursor.execute(f"LISTEN {LISTEN_CHANNEL};")
            except KeyboardInterrupt:
                print("\n\n👋 Stopping listener...")
                self.running = False
            except select.error as e:
                print(f"⚠️ Select error: {e}")
                time.sleep(1)
            except Exception as e:
                print(f"❌ Error in listener loop: {e}")
                time.sleep(1)
                
        cursor.close()
    
    def run_once(self):
        """Process any pending notifications and exit."""
        cursor = self.pg_conn.cursor()
        cursor.execute(f"LISTEN {LISTEN_CHANNEL};")
        
        print("📨 Checking for pending notifications...")
        
        # Set non-blocking and poll once
        self.pg_conn.poll()
        
        count = 0
        while self.pg_conn.notifies:
            notify = self.pg_conn.notifies.pop(0)
            self.process_notification(notify.payload)
            count += 1
            
        if count == 0:
            print("   No pending notifications")
        else:
            print(f"   Processed {count} notifications")
            
        cursor.close()
    
    def print_stats(self):
        """Print sync statistics."""
        print(f"\n{'='*60}")
        print(f"Sync Statistics")
        print(f"{'='*60}")
        print(f"  ✅ Synced:   {self.stats['synced']}")
        print(f"  🗑️  Deleted:  {self.stats['deleted']}")
        print(f"  ❌ Failed:   {self.stats['failed']}")
        if self.stats['errors']:
            print(f"\n  Recent errors:")
            for err in self.stats['errors'][-3:]:
                print(f"    - {err}")
        print(f"{'='*60}\n")
    
    def close(self):
        """Close connections."""
        if self.pg_conn:
            self.pg_conn.close()
            print("✅ PostgreSQL connection closed")


def signal_handler(signum, frame):
    """Handle shutdown signals."""
    print(f"\n📡 Received signal {signum}, shutting down...")
    sys.exit(0)


def main():
    parser = argparse.ArgumentParser(
        description='Real-time sync listener for PostgreSQL → Weaviate'
    )
    parser.add_argument('--once', action='store_true',
                       help='Process pending notifications and exit')
    parser.add_argument('--daemon', action='store_true',
                       help='Run as daemon (redirect output to log)')
    parser.add_argument('--stats', action='store_true',
                       help='Print statistics on exit')
    
    args = parser.parse_args()
    
    # Set up signal handlers
    signal.signal(signal.SIGTERM, signal_handler)
    signal.signal(signal.SIGINT, signal_handler)
    
    listener = WikiSyncListener()
    
    try:
        listener.connect()
        
        if args.once:
            listener.run_once()
        else:
            listener.listen()
            
    except KeyboardInterrupt:
        pass
    except Exception as e:
        print(f"❌ Fatal error: {e}")
        sys.exit(1)
    finally:
        if args.stats:
            listener.print_stats()
        listener.close()


if __name__ == "__main__":
    main()
