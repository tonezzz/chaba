#!/usr/bin/env python3
"""
NotebookLM Client for MCP-Wiki
Manual workflow integration until official API is available.
"""

import os
import sys
import json
import requests
from datetime import datetime
from pathlib import Path
import argparse

WIKI_API_URL = os.getenv('WIKI_API_URL', 'http://localhost:3008')


class NotebookLMWorkflow:
    """Manages the manual NotebookLM → Wiki workflow."""
    
    def __init__(self):
        self.wiki_url = WIKI_API_URL
        
    def get_wiki_article(self, title: str) -> dict:
        """Fetch article from MCP-Wiki."""
        try:
            response = requests.get(
                f"{self.wiki_url}/api/articles/{requests.utils.quote(title, safe='')}",
                timeout=10
            )
            if response.status_code == 200:
                return response.json()
            else:
                print(f"❌ Article not found: {title}")
                return None
        except Exception as e:
            print(f"❌ Error fetching article: {e}")
            return None
    
    def export_for_notebooklm(self, title: str, output_dir: str = "/tmp") -> str:
        """Export wiki article for NotebookLM upload."""
        article = self.get_wiki_article(title)
        if not article:
            return None
        
        # Create clean export
        export_content = f"""# {article['title']}

Source: MCP-Wiki
URL: {self.wiki_url}/article/{requests.utils.quote(article['title'], safe='')}
Exported: {datetime.now().isoformat()}

---

{article['content']}

---

Tags: {', '.join(article.get('tags', []))}
"""
        
        # Save to file
        safe_filename = title.replace(' ', '_').replace('/', '_')[:50]
        output_path = Path(output_dir) / f"{safe_filename}_notebooklm.md"
        
        with open(output_path, 'w') as f:
            f.write(export_content)
        
        print(f"✅ Exported to: {output_path}")
        print(f"\n📋 Next steps:")
        print(f"   1. Go to https://notebooklm.google.com")
        print(f"   2. Create new project: 'Analysis: {title[:40]}'")
        print(f"   3. Upload: {output_path}")
        print(f"   4. Request analysis (summary/insights/audio)")
        print(f"   5. Export results and import back to wiki")
        
        return str(output_path)
    
    def import_analysis(self, wiki_title: str, analysis_file: str, 
                       analysis_type: str = "summary") -> bool:
        """Import NotebookLM analysis back to wiki."""
        try:
            with open(analysis_file, 'r') as f:
                analysis_content = f.read()
            
            # Create new article with NotebookLM analysis
            new_title = f"{wiki_title} (NotebookLM {analysis_type.title()})"
            
            article_content = f"""# {new_title}

## Source Document
- **Original**: [{wiki_title}]({self.wiki_url}/article/{requests.utils.quote(wiki_title, safe='')})
- **Analysis Type**: {analysis_type}
- **Date**: {datetime.now().strftime('%Y-%m-%d')}
- **Tool**: NotebookLM (Google AI)

## NotebookLM Analysis

{analysis_content}

---

*This analysis was generated using Google NotebookLM. The insights are derived from AI processing of the source document.*
"""
            
            # Create in wiki
            response = requests.post(
                f"{self.wiki_url}/create",
                data={
                    'title': new_title,
                    'content': article_content,
                    'tags': f'notebooklm, deep-analysis, {analysis_type}, ai-generated'
                },
                timeout=30,
                allow_redirects=True
            )
            
            if response.status_code == 200:
                print(f"✅ Analysis imported: {new_title}")
                print(f"   View at: {self.wiki_url}/article/{requests.utils.quote(new_title, safe='')}")
                return True
            else:
                print(f"❌ Import failed: {response.status_code}")
                return False
                
        except Exception as e:
            print(f"❌ Error importing analysis: {e}")
            return False
    
    def list_candidates(self, min_length: int = 2000) -> list:
        """List wiki articles that are good candidates for NotebookLM analysis."""
        try:
            response = requests.get(
                f"{self.wiki_url}/api/articles?limit=100",
                timeout=10
            )
            articles = response.json()
            
            candidates = []
            for article in articles:
                content_length = len(article.get('content', ''))
                if content_length >= min_length:
                    candidates.append({
                        'title': article['title'],
                        'length': content_length,
                        'tags': article.get('tags', [])
                    })
            
            # Sort by length (longest first)
            candidates.sort(key=lambda x: x['length'], reverse=True)
            return candidates
            
        except Exception as e:
            print(f"❌ Error listing articles: {e}")
            return []


def main():
    parser = argparse.ArgumentParser(
        description='NotebookLM workflow for MCP-Wiki',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  # Export article for NotebookLM
  python notebooklm-client.py export "Weaviate Configuration Guide"
  
  # Import analysis back to wiki
  python notebooklm-client.py import "Weaviate Configuration Guide" analysis.md --type summary
  
  # List good candidates for analysis
  python notebooklm-client.py candidates
        """
    )
    
    subparsers = parser.add_subparsers(dest='command', help='Command to run')
    
    # Export command
    export_parser = subparsers.add_parser('export', help='Export article for NotebookLM')
    export_parser.add_argument('title', help='Article title to export')
    export_parser.add_argument('--output-dir', default='/tmp', help='Output directory')
    
    # Import command
    import_parser = subparsers.add_parser('import', help='Import NotebookLM analysis')
    import_parser.add_argument('wiki_title', help='Original wiki article title')
    import_parser.add_argument('analysis_file', help='Path to analysis markdown file')
    import_parser.add_argument('--type', default='summary', 
                               choices=['summary', 'insights', 'audio-brief'],
                               help='Type of analysis')
    
    # Candidates command
    candidates_parser = subparsers.add_parser('candidates', help='List analysis candidates')
    candidates_parser.add_argument('--min-length', type=int, default=2000,
                                   help='Minimum article length (chars)')
    candidates_parser.add_argument('--limit', type=int, default=10,
                                   help='Number of candidates to show')
    
    args = parser.parse_args()
    
    if not args.command:
        parser.print_help()
        sys.exit(1)
    
    workflow = NotebookLMWorkflow()
    
    if args.command == 'export':
        path = workflow.export_for_notebooklm(args.title, args.output_dir)
        if path:
            print(f"\n✅ Export complete: {path}")
        else:
            sys.exit(1)
    
    elif args.command == 'import':
        success = workflow.import_analysis(args.wiki_title, args.analysis_file, args.type)
        sys.exit(0 if success else 1)
    
    elif args.command == 'candidates':
        candidates = workflow.list_candidates(args.min_length)
        print(f"\n📚 Top {args.limit} candidates for NotebookLM analysis:")
        print("=" * 70)
        
        for i, c in enumerate(candidates[:args.limit], 1):
            tags = ', '.join(c['tags'][:3]) if c['tags'] else 'no tags'
            print(f"\n{i}. {c['title'][:55]}")
            print(f"   Length: {c['length']:,} chars | Tags: {tags}")
            print(f"   Export: python notebooklm-client.py export \"{c['title']}\"")
        
        print(f"\n   Total candidates: {len(candidates)} articles")
        print("=" * 70)


if __name__ == "__main__":
    main()
