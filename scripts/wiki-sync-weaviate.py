#!/usr/bin/env python3
"""
Wiki Sync: PostgreSQL → Weaviate
Synchronizes MCP-Wiki articles from PostgreSQL to Weaviate for semantic search.
"""

import os
import sys
import psycopg2
import weaviate
from datetime import datetime
from google.genai import Client as GeminiClient
from google.genai.types import EmbedContentConfig
from dotenv import load_dotenv
import argparse

load_dotenv()

# Configuration
POSTGRES_URL = os.getenv('DATABASE_URL', 'postgresql://chaba:changeme@localhost:5432/chaba')
WEAVIATE_URL = os.getenv('WEAVIATE_URL', 'http://localhost:8082')
GEMINI_API_KEY = os.getenv('GEMINI_API_KEY')
BATCH_SIZE = 50
EMBEDDING_MODEL = 'text-embedding-004'
EMBEDDING_DIMENSION = 768


class WikiWeaviateSync:
    def __init__(self):
        self.pg_conn = None
        self.weaviate_client = None
        self.gemini_client = None
        self.stats = {'synced': 0, 'failed': 0, 'skipped': 0}
        
    def connect(self):
        """Connect to PostgreSQL and Weaviate."""
        try:
            self.pg_conn = psycopg2.connect(POSTGRES_URL)
            print(f"✅ Connected to PostgreSQL")
        except Exception as e:
            print(f"❌ PostgreSQL connection failed: {e}")
            sys.exit(1)
            
        try:
            self.weaviate_client = weaviate.Client(WEAVIATE_URL)
            print(f"✅ Connected to Weaviate at {WEAVIATE_URL}")
        except Exception as e:
            print(f"❌ Weaviate connection failed: {e}")
            sys.exit(1)
            
        if GEMINI_API_KEY:
            try:
                self.gemini_client = GeminiClient(api_key=GEMINI_API_KEY)
                print(f"✅ Connected to Gemini API")
            except Exception as e:
                print(f"⚠️ Gemini API connection failed: {e}")
                print("   Will use dummy embeddings (not recommended for production)")
        else:
            print("⚠️ No GEMINI_API_KEY set - using dummy embeddings")
    
    def generate_embedding(self, text: str) -> list:
        """Generate embedding using Gemini API."""
        if not self.gemini_client:
            # Return dummy embedding for testing
            return [0.0] * EMBEDDING_DIMENSION
            
        try:
            # Truncate to avoid token limits
            truncated = text[:8000]
            
            response = self.gemini_client.models.embed_content(
                model=EMBEDDING_MODEL,
                contents=truncated,
                config=EmbedContentConfig(
                    task_type="RETRIEVAL_DOCUMENT"
                )
            )
            
            embedding = response.embeddings[0].values
            
            # Verify dimension
            if len(embedding) != EMBEDDING_DIMENSION:
                print(f"⚠️ Unexpected embedding dimension: {len(embedding)}")
                
            return embedding
            
        except Exception as e:
            print(f"❌ Embedding generation failed: {e}")
            return [0.0] * EMBEDDING_DIMENSION
    
    def get_wikidb_articles(self, since: datetime = None) -> list:
        """Fetch articles from PostgreSQL."""
        cursor = self.pg_conn.cursor()
        
        if since:
            cursor.execute("""
                SELECT id, title, content, tags, updated_at 
                FROM articles 
                WHERE updated_at > %s
                ORDER BY updated_at
            """, (since,))
        else:
            cursor.execute("""
                SELECT id, title, content, tags, updated_at 
                FROM articles 
                ORDER BY id
            """)
            
        return cursor.fetchall()
    
    def get_existing_wikidb_ids(self) -> set:
        """Get set of already synced wikidb_ids from Weaviate."""
        existing = set()
        
        try:
            result = self.weaviate_client.query.get(
                "WikiArticle", ["wikidb_id"]
            ).with_limit(10000).do()
            
            if result and 'data' in result and 'Get' in result['data']:
                for item in result['data']['Get']['WikiArticle']:
                    existing.add(item['wikidb_id'])
                    
        except Exception as e:
            print(f"⚠️ Could not fetch existing IDs: {e}")
            
        return existing
    
    def sync_article(self, article: tuple, force: bool = False) -> bool:
        """Sync a single article to Weaviate."""
        wikidb_id, title, content, tags, updated_at = article
        
        # Convert tags to list if needed
        if isinstance(tags, str):
            tag_list = [t.strip() for t in tags.split(',')]
        elif isinstance(tags, list):
            tag_list = tags
        else:
            tag_list = []
        
        # Generate embedding from title + content
        text_to_embed = f"{title}\n\n{content[:3000]}"  # Limit content length
        vector = self.generate_embedding(text_to_embed)
        
        # Prepare data object
        # Format date as RFC3339 with timezone
        if updated_at:
            # Ensure the datetime has timezone info (or append Z for UTC)
            if updated_at.tzinfo is None:
                updated_at_str = updated_at.strftime('%Y-%m-%dT%H:%M:%SZ')
            else:
                updated_at_str = updated_at.isoformat()
        else:
            updated_at_str = datetime.utcnow().strftime('%Y-%m-%dT%H:%M:%SZ')
        
        data_object = {
            "title": title,
            "content": content,
            "tags": tag_list,
            "wikidb_id": wikidb_id,
            "updated_at": updated_at_str
        }
        
        try:
            # Check if exists
            if not force:
                existing = self.weaviate_client.query.get(
                    "WikiArticle", ["wikidb_id"]
                ).with_where({
                    "path": ["wikidb_id"],
                    "operator": "Equal",
                    "valueInt": wikidb_id
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
                    print(f"  🔄 Updated: {title[:50]}")
                    return True
            
            # Create new
            self.weaviate_client.data_object.create(
                data_object=data_object,
                class_name="WikiArticle",
                vector=vector
            )
            print(f"  ✅ Created: {title[:50]}")
            return True
            
        except Exception as e:
            print(f"  ❌ Failed: {title[:50]} - {e}")
            return False
    
    def sync_all(self, force: bool = False, dry_run: bool = False):
        """Sync all articles from PostgreSQL to Weaviate."""
        print(f"\n{'='*60}")
        print(f"Starting Wiki Sync: PostgreSQL → Weaviate")
        print(f"{'='*60}\n")
        
        # Get articles from PostgreSQL
        print("📥 Fetching articles from PostgreSQL...")
        articles = self.get_wikidb_articles()
        print(f"   Found {len(articles)} articles")
        
        if dry_run:
            print(f"\n🧪 DRY RUN - Would process {len(articles)} articles")
            for article in articles[:5]:
                wikidb_id, title, _, _, _ = article
                print(f"   - {title[:50]} (ID: {wikidb_id})")
            return
        
        # Get existing IDs
        print("\n📋 Checking existing articles in Weaviate...")
        existing_ids = self.get_existing_wikidb_ids()
        print(f"   {len(existing_ids)} articles already in Weaviate")
        
        # Sync articles
        print(f"\n🚀 Syncing articles...")
        for i, article in enumerate(articles, 1):
            wikidb_id, title, _, _, _ = article
            
            if not force and wikidb_id in existing_ids:
                self.stats['skipped'] += 1
                continue
            
            if self.sync_article(article, force=force):
                self.stats['synced'] += 1
            else:
                self.stats['failed'] += 1
            
            # Progress
            if i % 10 == 0:
                print(f"   Progress: {i}/{len(articles)} articles")
        
        # Print summary
        print(f"\n{'='*60}")
        print(f"Sync Complete!")
        print(f"{'='*60}")
        print(f"  ✅ Created/Updated: {self.stats['synced']}")
        print(f"  ⏭️  Skipped: {self.stats['skipped']}")
        print(f"  ❌ Failed: {self.stats['failed']}")
        print(f"{'='*60}\n")
    
    def verify_sync(self):
        """Verify sync by comparing counts."""
        print("\n🔍 Verification:")
        
        # PostgreSQL count
        cursor = self.pg_conn.cursor()
        cursor.execute("SELECT COUNT(*) FROM articles")
        pg_count = cursor.fetchone()[0]
        print(f"   PostgreSQL articles: {pg_count}")
        
        # Weaviate count
        try:
            result = self.weaviate_client.query.aggregate("WikiArticle").with_meta_count().do()
            wv_count = result['data']['Aggregate']['WikiArticle'][0]['meta']['count']
            print(f"   Weaviate articles: {wv_count}")
            
            if pg_count == wv_count:
                print(f"   ✅ Counts match!")
            else:
                print(f"   ⚠️  Count mismatch: {pg_count - wv_count} articles not synced")
        except Exception as e:
            print(f"   ❌ Could not verify Weaviate count: {e}")
    
    def close(self):
        """Close connections."""
        if self.pg_conn:
            self.pg_conn.close()
            print("✅ PostgreSQL connection closed")


def main():
    parser = argparse.ArgumentParser(description='Sync MCP-Wiki articles to Weaviate')
    parser.add_argument('--force', action='store_true', 
                       help='Force update all articles (not just new ones)')
    parser.add_argument('--dry-run', action='store_true',
                       help='Show what would be done without making changes')
    parser.add_argument('--verify', action='store_true',
                       help='Verify sync after completing')
    
    args = parser.parse_args()
    
    sync = WikiWeaviateSync()
    
    try:
        sync.connect()
        sync.sync_all(force=args.force, dry_run=args.dry_run)
        
        if args.verify:
            sync.verify_sync()
            
    except KeyboardInterrupt:
        print("\n\n⚠️ Sync interrupted by user")
    except Exception as e:
        print(f"\n❌ Sync failed: {e}")
        sys.exit(1)
    finally:
        sync.close()


if __name__ == "__main__":
    main()
