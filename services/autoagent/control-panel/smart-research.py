#!/usr/bin/env python3
"""
Smart Research with LLM-Powered Knowledge Base
- LLM classifies and tags queries
- Searches KB semantically before internet
- Identifies gaps for targeted research
- Auto cross-references related articles
"""

import os
import json
import re
import requests
from typing import Optional, List, Dict, Tuple
from datetime import datetime

# Import PostgreSQL KB (fallback to HTTP API if not available)
try:
    from postgres_kb import PostgresKnowledgeBase
    KB_CLASS = PostgresKnowledgeBase
    KB_TYPE = "postgresql"
except ImportError:
    KB_CLASS = None
    KB_TYPE = "http"

# Configuration
OPENROUTER_API_KEY = os.getenv("OPENROUTER_API_KEY", "")
API_BASE_URL = "https://openrouter.ai/api/v1"
DEFAULT_MODEL = "nvidia/nemotron-3-super-120b-a12b:free"
ANALYSIS_MODEL = "openai/gpt-4o-mini"  # Cheap model for analysis
WIKI_API_URL = os.getenv("WIKI_API_URL", "http://mcp-wiki:8080")  # Docker network hostname
DATABASE_URL = os.getenv("DATABASE_URL", "postgresql://chaba:changeme@idc1.surf-thailand.com:5432/chaba")


class WikiKnowledgeBase:
    """HTTP API client for mcp-wiki (fallback when PostgreSQL not available)"""
    
    def __init__(self, api_base: str = None):
        self.api_base = api_base or os.getenv("WIKI_API_URL", "http://mcp-wiki:8080")
    
    def _api_get(self, endpoint: str, params: dict = None) -> List[Dict]:
        """GET request to wiki API"""
        try:
            url = f"{self.api_base}{endpoint}"
            resp = requests.get(url, params=params, timeout=10)
            resp.raise_for_status()
            return resp.json()
        except Exception as e:
            print(f"   ⚠️  API error (GET {endpoint}): {e}")
            return []
    
    def _api_post(self, endpoint: str, data: dict) -> Optional[Dict]:
        """POST request to wiki API"""
        try:
            url = f"{self.api_base}{endpoint}"
            resp = requests.post(url, json=data, timeout=10)
            resp.raise_for_status()
            return resp.json()
        except Exception as e:
            print(f"   ⚠️  API error (POST {endpoint}): {e}")
            return None
    
    def search(self, query: str, limit: int = 10) -> List[Dict]:
        """Search articles via API"""
        return self._api_get("/api/search", {"q": query, "limit": limit})
    
    def get_article(self, title: str) -> Optional[Dict]:
        """Get single article via API"""
        try:
            encoded_title = requests.utils.quote(title)
            url = f"{self.api_base}/api/articles/{encoded_title}"
            resp = requests.get(url, timeout=10)
            if resp.status_code == 404:
                return None
            resp.raise_for_status()
            return resp.json()
        except Exception as e:
            print(f"   ⚠️  API error (get_article): {e}")
            return None
    
    def save_article(self, title: str, content: str, tags: List[str], 
                     entities: List[str], classification: str) -> bool:
        """Create or update article via API"""
        # First try to create
        data = {
            "title": title,
            "content": content,
            "tags": tags,
            "entities": entities,
            "classification": classification
        }
        
        result = self._api_post("/api/articles", data)
        if result:
            return True
        
        # If exists, try to update via PUT (we need to add PUT endpoint or handle differently)
        # For now, update won't work - would need PUT endpoint added
        print(f"   ⚠️  Article may already exist (update not supported via API yet)")
        return False
    
    def list_articles(self, tag: str = None, limit: int = 20) -> List[Dict]:
        """List articles via API"""
        articles = self._api_get("/api/articles", {"limit": limit})
        
        if tag and articles:
            # Filter by tag client-side (API doesn't support tag filter yet)
            filtered = []
            for a in articles:
                article_tags = a.get("tags", "")
                if tag.lower() in article_tags.lower():
                    filtered.append(a)
            return filtered
        
        return articles
    
    def log_session(self, query: str, model: str, article: str, cached: bool):
        """Log to local file instead of DB (decoupled)"""
        log_file = os.path.expanduser("~/.smart_research.log")
        import json
        entry = {
            "timestamp": datetime.now().isoformat(),
            "query": query,
            "model": model,
            "article": article,
            "cached": cached
        }
        with open(log_file, "a") as f:
            f.write(json.dumps(entry) + "\n")


class LLMAnalyzer:
    """LLM-powered query analysis"""
    
    def __init__(self, api_key: str = OPENROUTER_API_KEY):
        self.api_key = api_key
    
    def _call_llm(self, messages: List[Dict], model: str = ANALYSIS_MODEL, 
                  max_tokens: int = 500) -> Optional[str]:
        if not self.api_key:
            return None
        
        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
            "HTTP-Referer": "http://localhost:8059"
        }
        
        data = {
            "model": model,
            "messages": messages,
            "temperature": 0.3,
            "max_tokens": max_tokens
        }
        
        try:
            resp = requests.post(f"{API_BASE_URL}/chat/completions",
                               headers=headers, json=data, timeout=30)
            resp.raise_for_status()
            return resp.json()["choices"][0]["message"]["content"]
        except Exception as e:
            print(f"LLM error: {e}")
            return None
    
    def analyze_query(self, query: str) -> Dict:
        """Classify query and extract entities/tags"""
        system = """You are a query analyzer. Analyze the user's research query and output ONLY valid JSON.

Output format:
{
  "classification": "definition|comparison|tutorial|list|how-to|troubleshooting|analysis",
  "entities": ["primary subjects, products, APIs, models mentioned"],
  "key_concepts": ["key technical concepts"],
  "suggested_tags": ["5-7 relevant category tags"],
  "complexity": "basic|intermediate|advanced",
  "expected_output": "brief description of what answer should contain"
}"""
        
        result = self._call_llm([
            {"role": "system", "content": system},
            {"role": "user", "content": query}
        ])
        
        if result:
            try:
                # Extract JSON from possible markdown
                json_match = re.search(r'```json\n(.*?)\n```', result, re.DOTALL)
                if json_match:
                    result = json_match.group(1)
                return json.loads(result)
            except:
                pass
        
        # Fallback
        return {
            "classification": "research",
            "entities": [query.split()[0], query.split()[-1]] if len(query.split()) > 1 else [query],
            "key_concepts": [],
            "suggested_tags": ["research"],
            "complexity": "intermediate",
            "expected_output": "General information"
        }
    
    def check_similarity(self, query: str, article: Dict) -> Dict:
        """Check if query is similar to existing article"""
        system = """Compare the user's query with the existing article. Output ONLY valid JSON.

Output format:
{
  "similarity_score": 0.0-1.0,
  "explanation": "why similar or different",
  "coverage_percent": 0-100,
  "missing_aspects": ["what query asks that article doesn't cover"],
  "recommendation": "use_cache|partial_research|full_research"
}"""
        
        content = f"Query: {query}\n\nArticle Title: {article['title']}\nArticle Content (first 1000 chars): {article['content'][:1000]}"
        
        result = self._call_llm([
            {"role": "system", "content": system},
            {"role": "user", "content": content}
        ])
        
        if result:
            try:
                json_match = re.search(r'```json\n(.*?)\n```', result, re.DOTALL)
                if json_match:
                    result = json_match.group(1)
                return json.loads(result)
            except:
                pass
        
        return {"similarity_score": 0, "recommendation": "full_research", "coverage_percent": 0, "missing_aspects": []}
    
    def identify_gaps(self, query: str, article_content: str) -> Dict:
        """Identify what's missing from article vs query"""
        system = """Analyze what information from the query is NOT covered in the existing article. Output ONLY valid JSON.

Output format:
{
  "already_covered": ["list of aspects already in article"],
  "missing_aspects": ["specific aspects query asks for that are missing"],
  "coverage_percent": 0-100,
  "targeted_research_query": "refined query focusing only on missing info"
}"""
        
        content = f"User Query: {query}\n\nExisting Article Content:\n{article_content[:1500]}"
        
        result = self._call_llm([
            {"role": "system", "content": system},
            {"role": "user", "content": content}
        ])
        
        if result:
            try:
                json_match = re.search(r'```json\n(.*?)\n```', result, re.DOTALL)
                if json_match:
                    result = json_match.group(1)
                return json.loads(result)
            except:
                pass
        
        return {"already_covered": [], "missing_aspects": [query], "coverage_percent": 0, "targeted_research_query": query}
    
    def generate_cross_references(self, new_title: str, new_content: str, 
                                   existing_articles: List[Dict]) -> List[str]:
        """Generate related article suggestions"""
        system = """Given a new article and list of existing articles, suggest which 3-5 are most relevant to link. Output ONLY valid JSON array of titles."""
        
        articles_list = "\n".join([f"- {a['title']}" for a in existing_articles[:20]])
        content = f"New Article: {new_title}\n\nContent Preview: {new_content[:500]}\n\nExisting Articles:\n{articles_list}"
        
        result = self._call_llm([
            {"role": "system", "content": system},
            {"role": "user", "content": content}
        ], max_tokens=200)
        
        if result:
            try:
                json_match = re.search(r'```json\n(.*?)\n```', result, re.DOTALL)
                if json_match:
                    result = json_match.group(1)
                return json.loads(result)
            except:
                pass
        
        return []


class SmartResearcher:
    """Main smart research orchestrator"""
    
    def __init__(self):
        # Use HTTP API (WikiKnowledgeBase) to save articles to mcp-wiki
        # PostgresKnowledgeBase saves to kb_articles which is separate from wiki
        self.kb = WikiKnowledgeBase()
        print(f"   📚 Using HTTP API knowledge base (wiki)")
        self.analyzer = LLMAnalyzer()
    
    def _do_research(self, query: str, model: str) -> str:
        """Execute research with free model"""
        headers = {
            "Authorization": f"Bearer {OPENROUTER_API_KEY}",
            "Content-Type": "application/json",
            "HTTP-Referer": "http://localhost:8059",
            "X-Title": "Smart Research"
        }
        
        system = """You are a research assistant. Provide comprehensive, well-structured information with:
- Clear overview/definition
- Key features or components  
- Technical details
- Use cases or examples
- Recent developments if relevant

Format with clear headers and bullet points."""
        
        data = {
            "model": model,
            "messages": [
                {"role": "system", "content": system},
                {"role": "user", "content": query}
            ],
            "temperature": 0.7,
            "max_tokens": 2000
        }
        
        try:
            resp = requests.post(f"{API_BASE_URL}/chat/completions",
                               headers=headers, json=data, timeout=120)
            resp.raise_for_status()
            return resp.json()["choices"][0]["message"]["content"]
        except Exception as e:
            return f"Research error: {str(e)}"
    
    def research(self, query: str, model: str = DEFAULT_MODEL, 
                 use_cache: bool = True) -> Tuple[str, Dict]:
        """
        Smart research with KB-first approach
        Returns: (result, metadata)
        """
        metadata = {
            "query": query,
            "used_cache": False,
            "article_title": None,
            "similarity_score": 0,
            "classification": None,
            "entities": [],
            "model_used": model
        }
        
        # Step 1: Analyze query with LLM
        print(f"🔍 Analyzing query: {query}")
        analysis = self.analyzer.analyze_query(query)
        metadata["classification"] = analysis.get("classification", "research")
        metadata["entities"] = analysis.get("entities", [])
        print(f"   Classification: {metadata['classification']}")
        print(f"   Entities: {', '.join(metadata['entities'])}")
        
        # Step 2: Search KB for candidates
        if use_cache:
            print(f"\n📚 Searching knowledge base...")
            
            # Search by entities and keywords
            search_terms = metadata["entities"] + analysis.get("key_concepts", [])
            candidates = []
            
            for term in search_terms:
                candidates.extend(self.kb.search(term, limit=3))
            
            # Deduplicate
            seen = set()
            unique_candidates = []
            for c in candidates:
                if c["title"] not in seen:
                    seen.add(c["title"])
                    unique_candidates.append(c)
            
            if unique_candidates:
                print(f"   Found {len(unique_candidates)} candidate articles")
                
                # Step 3: LLM similarity check
                best_match = None
                best_score = 0
                
                for article in unique_candidates[:5]:  # Check top 5
                    full_article = self.kb.get_article(article["title"])
                    if full_article:
                        sim = self.analyzer.check_similarity(query, full_article)
                        score = sim.get("similarity_score", 0)
                        
                        if score > best_score:
                            best_score = score
                            best_match = (full_article, sim)
                
                if best_match and best_score > 0.8:
                    # High similarity - use cache
                    article, sim_info = best_match
                    metadata["used_cache"] = True
                    metadata["article_title"] = article["title"]
                    metadata["similarity_score"] = best_score
                    
                    self.kb.log_session(query, "wiki_cache", article["title"], True)
                    
                    result = f"""📚 **From Knowledge Base: {article['title']}**

{article['content']}

---
*Retrieved from cache (similarity: {best_score:.0%})*
*Classification: {article.get('classification', 'unknown')} | Tags: {article.get('tags', 'none')}*"""
                    
                    return result, metadata
                
                elif best_match and best_score > 0.4:
                    # Partial match - do targeted research
                    article, sim_info = best_match
                    print(f"\n⚡ Partial match ({best_score:.0%}): {article['title']}")
                    
                    gaps = self.analyzer.identify_gaps(query, article["content"])
                    missing = gaps.get("missing_aspects", [])
                    
                    if missing:
                        targeted_query = gaps.get("targeted_research_query", query)
                        print(f"   Researching gaps: {', '.join(missing[:3])}")
                        
                        new_content = self._do_research(targeted_query, model)
                        
                        # Combine
                        combined = f"""📚 **Based on Knowledge Base + Fresh Research**

**From existing article "{article['title']}":**
{article['content'][:800]}...

---
**New Research (focusing on gaps):**
{new_content}

---
*Combined result: Cached ({best_score:.0%}) + Fresh research*
*Gaps addressed: {', '.join(missing[:3])}*"""
                        
                        # Save as new combined article
                        title = f"{query.strip().rstrip('?').title()[:90]}"
                        tags = list(set(analysis.get("suggested_tags", []) + 
                                       (article.get("tags") or "").split(",")))
                        
                        self.kb.save_article(title, combined, tags,
                                           metadata["entities"], metadata["classification"])
                        
                        metadata["article_title"] = title
                        self.kb.log_session(query, model, title, False)
                        
                        return combined, metadata
        
        # Step 4: Full research
        print(f"\n🔬 No suitable cache found. Researching with {model}...")
        content = self._do_research(query, model)
        
        # Step 5: Save to KB with cross-references
        title = f"{query.strip().rstrip('?').title()[:90]}"
        tags = analysis.get("suggested_tags", ["research"])
        
        # Get cross-references
        existing = self.kb.list_articles(limit=20)
        related = self.analyzer.generate_cross_references(title, content, existing)
        
        if related:
            cross_refs = "\n\n**See Also:**\n" + "\n".join([f"- [[{r}]]" for r in related[:5]])
            content += cross_refs
        
        # Add metadata footer
        content += f"""

---
**Article Metadata:**
- Original Query: {query}
- Classification: {metadata['classification']}
- Entities: {', '.join(metadata['entities'])}
- Research Date: {datetime.now().isoformat()}
- Model: {model}
- Tags: {', '.join(tags)}
"""
        
        self.kb.save_article(title, content, tags, metadata["entities"], metadata["classification"])
        metadata["article_title"] = title
        self.kb.log_session(query, model, title, False)
        
        print(f"✅ Saved to wiki: {title}")
        if related:
            print(f"   Cross-referenced: {', '.join(related[:3])}")
        
        return content, metadata


def main():
    import sys
    
    if len(sys.argv) < 2:
        print("Usage: python smart-research.py '<query>' [options]")
        print()
        print("Options:")
        print("  --no-cache      Skip KB cache check")
        print("  --model <name>  Use specific model")
        print()
        print("Examples:")
        print('  python smart-research.py "What is Gemini Live API?"')
        print('  python smart-research.py "Compare GPT-4 and Claude"')
        print()
        
        # Show KB stats via API
        kb = WikiKnowledgeBase()
        articles = kb.list_articles(limit=10)
        
        if articles:
            print(f"📚 Knowledge Base Stats:")
            print(f"   Articles: {len(articles)}")
            print()
            print("Recent Articles:")
            for a in articles[:5]:
                tag_str = f" [{a.get('tags', '')}]" if a.get('tags') else ""
                print(f"   • {a['title']}{tag_str}")
        else:
            print("📚 Knowledge base is empty. Start researching!")
            print(f"   API: {kb.api_base}")
        
        sys.exit(1)
    
    query = sys.argv[1]
    use_cache = "--no-cache" not in sys.argv
    
    model = DEFAULT_MODEL
    if "--model" in sys.argv:
        idx = sys.argv.index("--model")
        if idx + 1 < len(sys.argv):
            model = sys.argv[idx + 1]
    
    print(f"🔬 Smart Research")
    print(f"Query: {query}")
    print(f"Model: {model}")
    print(f"Cache: {'enabled' if use_cache else 'disabled'}")
    print("=" * 60)
    
    researcher = SmartResearcher()
    result, meta = researcher.research(query, model, use_cache)
    
    print("\n" + "=" * 60)
    print("RESULT:")
    print("=" * 60)
    print(result)
    
    print("\n" + "-" * 60)
    print(f"Metadata: {json.dumps(meta, indent=2, default=str)}")


if __name__ == "__main__":
    main()
