#!/usr/bin/env python3
"""BitNet CPU vs GPU Text Generation Comparison"""

import subprocess
import time
import sys
import os

PROMPT = "Explain quantum computing in simple terms"
MAX_TOKENS = 100
MODEL_NAME = "falcon3-1b"
HF_REPO = "tiiuae/Falcon3-1B-Instruct-1.58bit"

def run_cmd(cmd, cwd=None, env=None):
    """Run command and capture output"""
    print(f"\n> {' '.join(cmd)}")
    start = time.time()
    result = subprocess.run(
        cmd,
        capture_output=True,
        text=True,
        cwd=cwd,
        env={**os.environ, **(env or {})}
    )
    duration = time.time() - start
    return result, duration

def print_header(text):
    print("\n" + "=" * 60)
    print(text)
    print("=" * 60)

def main():
    print_header("BitNet CPU vs GPU Comparison")
    print(f"Prompt: '{PROMPT}'")
    print(f"Max Tokens: {MAX_TOKENS}")

    # CPU Inference
    print_header("CPU Inference (bitnet.cpp)")
    model_path = f"models/{HF_REPO.split('/')[-1]}/ggml-model-i2_s.gguf"
    cpu_cmd = [
        "python", "run_inference.py",
        "-m", model_path,
        "-p", PROMPT,
        "-n", str(MAX_TOKENS),
        "-t", "4",
        "-temp", "0.8"
    ]
    cpu_result, cpu_time = run_cmd(cpu_cmd)

    print(f"\n--- CPU Output (last 20 lines) ---")
    lines = cpu_result.stdout.split('\n')
    print('\n'.join(lines[-20:]))
    if cpu_result.stderr:
        print("\n--- CPU stderr ---")
        print(cpu_result.stderr[-1000:] if len(cpu_result.stderr) > 1000 else cpu_result.stderr)
    print(f"\n--- CPU Time: {cpu_time:.2f}s ---")

    # GPU Inference (Skipped - Falcon3 GPU support not in this build)
    print_header("GPU Inference (CUDA Kernels)")
    print("GPU inference skipped - Falcon3 model uses different GPU kernel structure.")
    print("For GPU comparison, use the original BitNet-b1.58-2B-4T model on ARM64.")
    gpu_time = 0

    # Summary
    print_header("Summary")
    print(f"Model: {HF_REPO}")
    print(f"CPU Time:  {cpu_time:.2f}s")
    print("Note: GPU comparison requires BitNet-b1.58-2B-4T model on ARM64 architecture.")

    # Benchmark
    print_header("Running E2E Benchmark")
    bench_cmd = [
        "python", "utils/e2e_benchmark.py",
        "-m", model_path,
        "-n", "128",
        "-p", "512",
        "-t", "4"
    ]
    bench_result, _ = run_cmd(bench_cmd)
    print(bench_result.stdout[-2000:] if len(bench_result.stdout) > 2000 else bench_result.stdout)

    return 0

if __name__ == "__main__":
    sys.exit(main())
