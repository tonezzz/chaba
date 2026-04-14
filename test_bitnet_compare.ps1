#!/usr/bin/env pwsh
# BitNet CPU vs GPU Text Generation Comparison
# Run this from the BitNet repo root after cloning

$ErrorActionPreference = "Stop"
$Prompt = "Explain quantum computing in simple terms"
$MaxTokens = 100
$ModelName = "bitnet-b1.58-2B-4T"

function Write-Header($text) {
    Write-Host "`n$('=' * 60)" -ForegroundColor Cyan
    Write-Host $text -ForegroundColor Cyan
    Write-Host "$('=' * 60)" -ForegroundColor Cyan
}

# ===== STEP 1: Environment Setup =====
Write-Header "STEP 1: Environment Setup"

# Check if we're in the BitNet directory
if (-not (Test-Path "setup_env.py")) {
    Write-Host "Cloning BitNet repo..."
    git clone --recursive https://github.com/microsoft/BitNet.git
    Set-Location BitNet
}

# Create venv if it doesn't exist
if (-not (Test-Path ".venv")) {
    Write-Host "Creating Python venv..."
    python -m venv .venv
}
. .venv/Scripts/Activate.ps1
pip install --upgrade pip
pip install -r requirements.txt

# ===== STEP 2: Download Model (shared for both) =====
Write-Header "STEP 2: Download Model ($ModelName)"

if (-not (Test-Path "models/$ModelName")) {
    huggingface-cli download "microsoft/BitNet-b1.58-2B-4T-gguf" --local-dir "models/$ModelName"
    huggingface-cli download "microsoft/bitnet-b1.58-2B-4T-bf16" --local-dir "models/$ModelName-bf16"
}

# ===== STEP 3: CPU Inference =====
Write-Header "STEP 3: CPU Inference (bitnet.cpp)"

# Build if needed
if (-not (Test-Path "build/Release/bitnet.dll") -and -not (Test-Path "build/libbitnet.so")) {
    python setup_env.py -md "models/$ModelName" -q i2_s
}

$cpuStart = Get-Date
Write-Host "Running CPU generation..." -ForegroundColor Yellow
$cpuOutput = python run_inference.py `
    -m "models/$ModelName/ggml-model-i2_s.gguf" `
    -p "$Prompt" `
    -n $MaxTokens `
    -t 4 `
    -temp 0.8 2>&1
$cpuEnd = Get-Date
$cpuDuration = ($cpuEnd - $cpuStart).TotalSeconds

Write-Host "`n--- CPU Output ---" -ForegroundColor Green
$cpuOutput | Select-Object -Last 20 | ForEach-Object { Write-Host $_ }
Write-Host "--- CPU Time: $([math]::Round($cpuDuration, 2))s ---" -ForegroundColor Green

# ===== STEP 4: GPU Inference =====
Write-Header "STEP 4: GPU Inference (CUDA Kernels)"

Set-Location gpu

# Install GPU deps and build
pip install -r requirements.txt
if (-not (Test-Path "bitnet_kernels/bitnet_cuda.cp*")) {
    Set-Location bitnet_kernels
    bash compile.sh
    Set-Location ..
}

# Convert model for GPU if needed
if (-not (Test-Path "../checkpoints/model.pt")) {
    New-Item -ItemType Directory -Force -Path ../checkpoints
    python ../convert_safetensors.py `
        --safetensors_file "../models/$ModelName-bf16/model.safetensors" `
        --output ../checkpoints/model_state.pt `
        --model_name 2B
    python convert_checkpoint.py --input ../checkpoints/model_state.pt
    Remove-Item ../checkpoints/model_state.pt
}

$gpuStart = Get-Date
Write-Host "Running GPU generation..." -ForegroundColor Yellow
$gpuOutput = python generate.py `
    ./checkpoints/ `
    --prompt "$Prompt" `
    --max_tokens $MaxTokens `
    --temperature 0.8 2>&1
$gpuEnd = Get-Date
$gpuDuration = ($gpuEnd - $gpuStart).TotalSeconds

Write-Host "`n--- GPU Output ---" -ForegroundColor Green
$gpuOutput | Select-Object -Last 20 | ForEach-Object { Write-Host $_ }
Write-Host "--- GPU Time: $([math]::Round($gpuDuration, 2))s ---" -ForegroundColor Green

Set-Location ..

# ===== STEP 5: Comparison Summary =====
Write-Header "STEP 5: Comparison Summary"

$speedup = $cpuDuration / $gpuDuration
Write-Host "Prompt: '$Prompt'" -ForegroundColor White
Write-Host "Max Tokens: $MaxTokens" -ForegroundColor White
Write-Host ""
Write-Host "CPU Time:  $([math]::Round($cpuDuration, 2))s" -ForegroundColor Yellow
Write-Host "GPU Time:  $([math]::Round($gpuDuration, 2))s" -ForegroundColor Green
Write-Host "Speedup:   $([math]::Round($speedup, 2))x" -ForegroundColor Cyan

# Run benchmark for more rigorous comparison
Write-Host "`n--- Running E2E Benchmark ---" -ForegroundColor Magenta
python utils/e2e_benchmark.py -m "models/$ModelName/ggml-model-i2_s.gguf" -n 128 -p 512 -t 4
