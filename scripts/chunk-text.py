#!/usr/bin/env python3
"""
Text chunking using Chonkie for Weaviate indexing
Integrates with existing sentence-transformers embedding pipeline
"""

import sys
import json
from chonkie import SentenceChunker

def chunk_text(text, chunk_size=512, chunk_overlap=50):
    """
    Chunk text using Chonkie SentenceChunker
    
    Args:
        text: Input text to chunk
        chunk_size: Maximum tokens per chunk
        chunk_overlap: Token overlap between chunks
    
    Returns:
        List of chunked text segments
    """
    if not text or not text.strip():
        return []
    
    chunker = SentenceChunker(chunk_size=chunk_size, chunk_overlap=chunk_overlap)
    chunks = chunker.chunk(text)
    
    return [chunk.text for chunk in chunks]

def main():
    if len(sys.argv) < 2:
        print("Usage: chunk-text.py <text_to_chunk> [chunk_size] [chunk_overlap]")
        sys.exit(1)
    
    text = sys.argv[1]
    chunk_size = int(sys.argv[2]) if len(sys.argv) > 2 else 512
    chunk_overlap = int(sys.argv[3]) if len(sys.argv) > 3 else 50
    
    chunks = chunk_text(text, chunk_size, chunk_overlap)
    
    # Output as JSON for easy parsing by Node.js
    result = {
        "chunks": chunks,
        "count": len(chunks),
        "original_length": len(text)
    }
    
    print(json.dumps(result))

if __name__ == "__main__":
    main()
