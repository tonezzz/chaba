#!/usr/bin/env python3
"""Simple BitNet inference timing test"""

import subprocess
import time
import sys

def run_inference(prompt, tokens=50):
    """Run inference and time it"""
    cmd = [
        "python", "run_inference.py",
        "-m", "models/falcon3-1b-gguf/ggml-model-i2_s.gguf",
        "-p", prompt,
        "-n", str(tokens),
        "-t", "4",
        "-temp", "0.8"
    ]
    
    print(f"\nPrompt: {prompt}")
    print(f"Max tokens: {tokens}")
    print("Running inference...")
    
    start = time.time()
    result = subprocess.run(cmd, capture_output=True, text=True)
    elapsed = time.time() - start
    
    print(f"\nTime: {elapsed:.2f}s")
    print(f"Tokens/sec: {tokens/elapsed:.2f}")
    
    # Print last few lines of output
    lines = result.stdout.strip().split('\n')
    print("\n--- Output (last 10 lines) ---")
    for line in lines[-10:]:
        if line.strip() and not line.startswith('llm_load'):
            print(line[:100])  # Truncate long lines
    
    return elapsed

if __name__ == "__main__":
    print("=" * 60)
    print("BitNet CPU Inference Test (Falcon3-1B-Instruct-1.58bit)")
    print("=" * 60)
    
    prompts = [
        "Explain quantum computing in simple terms",
        "What is the capital of France?",
        "Write a haiku about nature"
    ]
    
    times = []
    for prompt in prompts:
        t = run_inference(prompt, tokens=30)
        times.append(t)
        print("\n" + "-" * 40)
    
    print(f"\n{'='*60}")
    print("Summary:")
    print(f"  Average time: {sum(times)/len(times):.2f}s")
    print(f"  Total time: {sum(times):.2f}s")
    print(f"{'='*60}")
