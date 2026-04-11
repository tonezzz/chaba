#!/usr/bin/env python3
"""
Wiki Knowledge Integration for AutoAgent
Save research results to mcp_wiki and query existing knowledge
"""

import os
import json
import requests
import sqlite3
from typing import Optional, List, Dict
from datetime import datetime

# Configuration
WIKI_DB_PATH = os.getenv("WIKI_DB_PATH", "/data/wiki.db")
WIKI_HTTP_PORT = os.getenv("WIKI_HTTP_PORT", "8082")
WIKI_API_URL = f"http://localhost:{WIKI_HTTP_PORT}"

# Free model for research (same as free-research.py)
OPENROUTER_API_KEY = os.getenv("OPENROUTER_API_KEY", "")
API_BASE_URL = "https://openrouter.ai/api/v1"
DEFAULT_MODEL = "nvidia/nemotron-3-super-120b-a12b:free"


class WikiKnowledgeBase:
    """Knowledge base using mcp_wiki SQLite database"""
    
    def __init__(self, db_path: str = WIKI_DB_PATH):
        self.db_path = db_path
        self._ensure_db()
    
    def _ensure_db(self):
        """Ensure database and tables exist"""
        os.makedirs(os.path.dirname(self.db_path), exist_ok=True)
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        
        # Articles table
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS articles (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                title TEXT UNIQUE NOT NULL,
                content TEXT NOT NULL,
                tags TEXT,
                created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
                updated_at DATETIME DEFAULT CURRENT_TIMESTAMP
            )
        ''')
        
        # Research sessions table (for tracking research history)
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS research_sessions (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                query TEXT NOT NULL,
                model_used TEXT,
                article_title TEXT,
                created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY (article_title) REFERENCES articles(title)
            )
        ''')
        
        conn.commit()
        conn.close()
    
    def search(self, query: str, limit: int = 10) -> List[Dict]:
        """Search existing knowledge"""
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        cursor = conn.cursor()
        
        pattern = f"%{query}%"
        cursor.execute('''
            SELECT title, tags, substr(content, 1, 300) as snippet, updated_at
            FROM articles
            WHERE title LIKE ? OR content LIKE ? OR tags LIKE ?
            ORDER BY updated_at DESC
            LIMIT ?
        ''', (pattern, pattern, pattern, limit))
        
        results = [dict(row) for row in cursor.fetchall()]
        conn.close()
        return results
    
    def get_article(self, title: str) -> Optional[Dict]:
        """Get full article content"""
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        cursor = conn.cursor()
        
        cursor.execute('SELECT * FROM articles WHERE title = ?', (title,))
        row = cursor.fetchone()
        conn.close()
        
        if row:
            return dict(row)
        return None
    
    def save_article(self, title: str, content: str, tags: List[str] = None) -> bool:
        """Save or update article"""
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        
        tags_str = ','.join(tags) if tags else None
        
        try:
            # Try insert first
            cursor.execute('''
                INSERT INTO articles (title, content, tags, updated_at)
                VALUES (?, ?, ?, CURRENT_TIMESTAMP)
            ''', (title, content, tags_str))
            conn.commit()
            conn.close()
            return True
        except sqlite3.IntegrityError:
            # Update existing
            cursor.execute('''
                UPDATE articles 
                SET content = ?, tags = ?, updated_at = CURRENT_TIMESTAMP
                WHERE title = ?
            ''', (content, tags_str, title))
            conn.commit()
            conn.close()
            return True
        except Exception as e:
            print(f"Error saving article: {e}")
            conn.close()
            return False
    
    def list_articles(self, tag: str = None, limit: int = 20) -> List[Dict]:
        """List all articles, optionally filtered by tag"""
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        cursor = conn.cursor()
        
        if tag:
            cursor.execute('''
                SELECT title, tags, substr(content, 1, 200) as snippet, updated_at
                FROM articles
                WHERE tags LIKE ?
                ORDER BY updated_at DESC
                LIMIT ?
            ''', (f"%{tag}%", limit))
        else:
            cursor.execute('''
                SELECT title, tags, substr(content, 1, 200) as snippet, updated_at
                FROM articles
                ORDER BY updated_at DESC
                LIMIT ?
            ''', (limit,))
        
        results = [dict(row) for row in cursor.fetchall()]
        conn.close()
        return results
    
    def log_research(self, query: str, model_used: str, article_title: str = None):
        """Log a research session"""
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        
        cursor.execute('''
            INSERT INTO research_sessions (query, model_used, article_title)
            VALUES (?, ?, ?)
        ''', (query, model_used, article_title))
        
        conn.commit()
        conn.close()


def research_with_wiki(query: str, 
                       model: str = DEFAULT_MODEL,
                       save_to_wiki: bool = True,
                       use_existing_knowledge: bool = True) -> str:
    """
    Research with knowledge base integration
    
    1. Check if answer exists in wiki
    2. If not, do research with free model
    3. Save result to wiki for future use
    """
    if not OPENROUTER_API_KEY:
        return "Error: OPENROUTER_API_KEY not set"
    
    wiki = WikiKnowledgeBase()
    
    # Step 1: Check existing knowledge
    if use_existing_knowledge:
        print(f"🔍 Checking wiki for: {query}")
        existing = wiki.search(query, limit=3)
        
        if existing:
            print(f"✅ Found {len(existing)} existing articles:")
            for i, article in enumerate(existing, 1):
                print(f"  {i}. {article['title']} (updated: {article['updated_at']})")
            
            # If exact match found, return it
            for article in existing:
                if query.lower() in article['title'].lower():
                    full = wiki.get_article(article['title'])
                    if full:
                        print(f"\n📚 Using existing knowledge: {article['title']}")
                        wiki.log_research(query, "wiki_cache", article['title'])
                        return full['content']
    
    # Step 2: Do fresh research
    print(f"\n🔬 Researching with {model}...")
    
    headers = {
        "Authorization": f"Bearer {OPENROUTER_API_KEY}",
        "Content-Type": "application/json",
        "HTTP-Referer": "http://localhost:8059",
        "X-Title": "AutoAgent Wiki Research"
    }
    
    # Enhanced prompt for better structured output
    system_prompt = """You are a research assistant. Provide comprehensive, well-structured information.
Include:
- Overview/definition
- Key features or components
- Technical details if relevant
- Use cases or examples
- Sources or references when possible

Format your response in clear sections with headers."""
    
    data = {
        "model": model,
        "messages": [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": query}
        ],
        "temperature": 0.7,
        "max_tokens": 2000
    }
    
    try:
        response = requests.post(
            f"{API_BASE_URL}/chat/completions",
            headers=headers,
            json=data,
            timeout=120
        )
        response.raise_for_status()
        
        result = response.json()
        content = result["choices"][0]["message"]["content"]
        
        # Step 3: Save to wiki
        if save_to_wiki:
            # Generate title from query
            title = query.strip().rstrip('?').title()
            # Truncate if too long
            if len(title) > 100:
                title = title[:97] + "..."
            
            # Add tags based on content
            tags = ["research", "auto-generated"]
            if "api" in query.lower():
                tags.append("api")
            if "model" in query.lower():
                tags.append("ai-model")
            
            # Append metadata
            full_content = f"""{content}

---
**Research Metadata:**
- Original Query: {query}
- Model Used: {model}
- Research Date: {datetime.now().isoformat()}
- Tags: {', '.join(tags)}
"""
            
            success = wiki.save_article(title, full_content, tags)
            if success:
                print(f"✅ Saved to wiki: {title}")
                wiki.log_research(query, model, title)
            else:
                print("⚠️  Failed to save to wiki")
        
        return content
        
    except Exception as e:
        return f"Error during research: {str(e)}"


def main():
    """CLI interface"""
    import sys
    
    if len(sys.argv) < 2:
        print("Usage: python wiki-knowledge.py '<query>' [options]")
        print()
        print("Options:")
        print("  --no-save       Don't save results to wiki")
        print("  --no-cache      Skip checking existing knowledge")
        print("  --model <name>  Use specific model")
        print()
        print("Examples:")
        print('  python wiki-knowledge.py "What is Gemini Live API?"')
        print('  python wiki-knowledge.py "What is Gemini Live API?" --no-cache')
        print('  python wiki-knowledge.py "List all GPT-4 capabilities" --model minimax/minimax-m2.5:free')
        print()
        
        # Show existing knowledge
        wiki = WikiKnowledgeBase()
        articles = wiki.list_articles(limit=10)
        if articles:
            print("📚 Existing Knowledge Base:")
            print("=" * 50)
            for article in articles:
                tags = article.get('tags', '')
                tag_str = f" [{tags}]" if tags else ""
                print(f"  • {article['title']}{tag_str}")
        else:
            print("📚 Knowledge base is empty. Start researching!")
        
        sys.exit(1)
    
    query = sys.argv[1]
    save_to_wiki = "--no-save" not in sys.argv
    use_cache = "--no-cache" not in sys.argv
    
    # Check for model override
    model = DEFAULT_MODEL
    if "--model" in sys.argv:
        idx = sys.argv.index("--model")
        if idx + 1 < len(sys.argv):
            model = sys.argv[idx + 1]
    
    print(f"Research Query: {query}")
    print(f"Model: {model}")
    print(f"Save to wiki: {save_to_wiki}")
    print(f"Use cache: {use_cache}")
    print("=" * 60)
    
    result = research_with_wiki(query, model, save_to_wiki, use_cache)
    print("\n" + "=" * 60)
    print("RESULT:")
    print("=" * 60)
    print(result)


if __name__ == "__main__":
    main()
