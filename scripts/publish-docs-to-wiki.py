#!/usr/bin/env python3
"""
Publish documentation to mcp-wiki as wiki posts.
Usage: python publish-docs-to-wiki.py
"""
import os
import requests
import json
from pathlib import Path

WIKI_API_URL = os.getenv("WIKI_API_URL", "http://localhost:3008")

def read_file(path):
    """Read markdown file content."""
    with open(path, 'r') as f:
        return f.read()

def publish_to_wiki(title, content, tags=None, entities=None, classification="documentation"):
    """Publish a document to mcp-wiki."""
    url = f"{WIKI_API_URL}/api/articles"
    
    # Extract entities from content
    if entities is None:
        entities = []
    
    # Prepare article data
    data = {
        "title": title,
        "content": content,
        "tags": tags or [],
        "entities": entities,
        "classification": classification
    }
    
    try:
        response = requests.post(url, json=data)
        response.raise_for_status()
        print(f"✅ Published: {title}")
        return True
    except Exception as e:
        print(f"❌ Failed to publish {title}: {e}")
        return False

def main():
    """Publish all documentation files."""
    docs_dir = Path("/home/chaba/chaba/docs")
    assistance_docs_dir = Path("/home/chaba/chaba/services/assistance/docs")
    root_dir = Path("/home/chaba/chaba")
    
    # Define the 4 docs to publish
    docs = [
        {
            "path": docs_dir / "MCP_WIKI_ASSESSMENT.md",
            "title": "MCP-Wiki Technical Assessment",
            "tags": ["mcp-wiki", "architecture", "infrastructure", "llm", "knowledge-base"],
            "entities": ["mcp-wiki", "redis", "weaviate", "LLM", "smart-research"],
            "classification": "technical-assessment"
        },
        {
            "path": docs_dir / "MCP_WIKI_POST.md",
            "title": "MCP-Wiki: The Missing Knowledge Layer",
            "tags": ["mcp-wiki", "architecture", "cost-optimization", "caching", "blog"],
            "entities": ["mcp-wiki", "LLM", "knowledge-base", "smart-caching"],
            "classification": "blog-post"
        },
        {
            "path": assistance_docs_dir / "MCP_WIKI.md",
            "title": "MCP-Wiki Quick Reference",
            "tags": ["mcp-wiki", "reference", "api", "developer"],
            "entities": ["mcp-wiki", "API", "REST", "developer-guide"],
            "classification": "reference"
        },
        {
            "path": root_dir / "JARVIS_SYSTEM_DOCUMENTATION.md",
            "title": "Jarvis System Documentation",
            "tags": ["jarvis", "system", "architecture", "overview", "mcp"],
            "entities": ["Jarvis", "SmartProvider", "MCP", "multi-provider", "Gemini", "OpenRouter"],
            "classification": "system-documentation"
        }
    ]
    
    print("🚀 Publishing docs to mcp-wiki...")
    print(f"Wiki API: {WIKI_API_URL}")
    print()
    
    success_count = 0
    for doc in docs:
        if doc["path"].exists():
            content = read_file(doc["path"])
            if publish_to_wiki(
                title=doc["title"],
                content=content,
                tags=doc["tags"],
                entities=doc["entities"],
                classification=doc["classification"]
            ):
                success_count += 1
        else:
            print(f"⚠️  File not found: {doc['path']}")
    
    print()
    print(f"📊 Published {success_count}/{len(docs)} documents")
    
    if success_count == len(docs):
        print("✅ All documents published successfully!")
        return 0
    else:
        print("⚠️  Some documents failed to publish")
        return 1

if __name__ == "__main__":
    exit(main())
