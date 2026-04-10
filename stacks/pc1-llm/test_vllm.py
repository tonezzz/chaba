#!/usr/bin/env python3
"""
vLLM Gemma 4B API Test Script
Tests the OpenAI-compatible endpoint running in Docker

Requirements:
    pip install openai

Usage:
    # First start vLLM:
    # docker-compose up -d vllm
    
    # Then run this test:
    python test_vllm.py
"""

import openai
import sys
import time

# vLLM local endpoint
client = openai.OpenAI(
    base_url="http://localhost:8000/v1",
    api_key="not-needed"  # vLLM doesn't require auth
)

def test_health():
    """Check if vLLM is running."""
    import urllib.request
    try:
        urllib.request.urlopen("http://localhost:8000/health", timeout=5)
        return True
    except:
        return False

def test_models():
    """List available models."""
    print("Available models:")
    models = client.models.list()
    for m in models.data:
        print(f"  - {m.id}")
    print()

def test_completion(prompt, max_tokens=200):
    """Test chat completion."""
    start = time.time()
    
    response = client.chat.completions.create(
        model="google/gemma-4b-it",
        messages=[
            {"role": "user", "content": prompt}
        ],
        max_tokens=max_tokens,
        temperature=0.7,
        stream=False
    )
    
    elapsed = time.time() - start
    result = response.choices[0].message.content
    tokens = response.usage.completion_tokens
    
    return result, elapsed, tokens, tokens/elapsed

def main():
    print("=" * 60)
    print("vLLM Gemma 4B - API Proof of Concept")
    print("=" * 60)
    
    # Check vLLM is up
    if not test_health():
        print("\nERROR: vLLM not responding at http://localhost:8000")
        print("Start it first: docker-compose up -d vllm")
        print("Wait ~2-3 minutes for model download on first run.")
        sys.exit(1)
    
    print("\nvLLM is running!")
    print("-" * 60)
    
    # List models
    test_models()
    
    # Test prompts
    prompts = [
        "Explain the difference between CPU and GPU in 3 sentences:",
        "Write a Python one-liner to reverse a string:",
        "What are the main benefits of running LLMs locally?",
    ]
    
    for i, prompt in enumerate(prompts, 1):
        print(f"\n{'='*60}")
        print(f"Test {i}: {prompt[:50]}...")
        print(f"{'='*60}")
        
        result, elapsed, tokens, speed = test_completion(prompt)
        
        print(f"\nResponse ({elapsed:.1f}s, {tokens} tokens, {speed:.1f} tok/s):")
        print(f"{result[:500]}...")
    
    print(f"\n{'='*60}")
    print("vLLM API test complete!")
    print(f"{'='*60}")
    print("\nIntegration ready for MCP/AutoAgent:")
    print('  base_url="http://localhost:8000/v1"')
    print('  model="google/gemma-4b-it"')

if __name__ == "__main__":
    main()
