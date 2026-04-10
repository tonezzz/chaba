#!/usr/bin/env python3
"""
Gemma 4B Proof of Concept Test Script
Quick local GPU test for google/gemma-4b-it model

Requirements:
    pip install torch transformers accelerate

Usage:
    python test_gemma.py
"""

import torch
from transformers import AutoTokenizer, AutoModelForCausalLM
import time
import sys

def check_gpu():
    """Check CUDA availability and GPU info."""
    if not torch.cuda.is_available():
        print("ERROR: CUDA not available. GPU required for Gemma 4B.")
        sys.exit(1)
    
    gpu_name = torch.cuda.get_device_name(0)
    gpu_memory = torch.cuda.get_device_properties(0).total_memory / 1024**3
    print(f"GPU: {gpu_name}")
    print(f"VRAM: {gpu_memory:.1f} GB")
    print(f"CUDA: {torch.version.cuda}")
    print("-" * 50)

def load_model(model_id="google/gemma-4b-it"):
    """Load Gemma 4B model with optimizations."""
    print(f"Loading {model_id}...")
    start = time.time()
    
    tokenizer = AutoTokenizer.from_pretrained(model_id)
    
    # Load with optimizations for consumer GPUs
    model = AutoModelForCausalLM.from_pretrained(
        model_id,
        torch_dtype=torch.float16,  # Half precision saves VRAM
        device_map="auto",          # Auto-distribute across GPU/CPU if needed
        trust_remote_code=True
    )
    
    load_time = time.time() - start
    print(f"Loaded in {load_time:.1f}s")
    print(f"Model device: {next(model.parameters()).device}")
    print("-" * 50)
    
    return tokenizer, model

def generate(tokenizer, model, prompt, max_tokens=200):
    """Generate text from prompt."""
    inputs = tokenizer(prompt, return_tensors="pt").to(model.device)
    
    start = time.time()
    with torch.no_grad():
        outputs = model.generate(
            **inputs,
            max_new_tokens=max_tokens,
            do_sample=True,
            temperature=0.7,
            top_p=0.9,
            pad_token_id=tokenizer.eos_token_id
        )
    gen_time = time.time() - start
    
    result = tokenizer.decode(outputs[0], skip_special_tokens=True)
    tokens_generated = len(outputs[0]) - len(inputs[0])
    speed = tokens_generated / gen_time
    
    return result, gen_time, speed

def main():
    print("=" * 50)
    print("Gemma 4B - Local GPU Proof of Concept")
    print("=" * 50)
    
    # Check GPU
    check_gpu()
    
    # Load model
    tokenizer, model = load_model("google/gemma-4b-it")
    
    # Test prompts
    prompts = [
        "Explain machine learning in 3 sentences:",
        "What are the benefits of local LLMs?",
        "Write a Python function to calculate fibonacci numbers:",
    ]
    
    print("\nRunning test generations...\n")
    
    for i, prompt in enumerate(prompts, 1):
        print(f"\n{'='*50}")
        print(f"Test {i}: {prompt[:50]}...")
        print(f"{'='*50}")
        
        result, gen_time, speed = generate(tokenizer, model, prompt)
        
        # Print just the generated part (remove prompt echo if present)
        generated = result[len(prompt):].strip() if result.startswith(prompt) else result
        
        print(f"\nGenerated ({gen_time:.1f}s, {speed:.1f} tok/s):\n{generated[:500]}...")
        print(f"\nVRAM used: {torch.cuda.memory_allocated()/1024**3:.1f} GB")
    
    print(f"\n{'='*50}")
    print("POC Complete! Model working on local GPU.")
    print(f"{'='*50}")

if __name__ == "__main__":
    main()
