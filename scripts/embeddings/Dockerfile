FROM nvidia/cuda:11.8.0-cudnn8-runtime-ubuntu22.04

WORKDIR /app

# Install Python
RUN apt-get update && apt-get install -y \
    python3 \
    python3-pip \
    && rm -rf /var/lib/apt/lists/*

# Upgrade pip and install wheel first
RUN pip3 install --upgrade pip setuptools wheel

# Install GPU PyTorch first
RUN pip3 install --no-cache-dir torch==2.0.1+cu118 -f https://download.pytorch.org/whl/torch_stable.html

# Verify PyTorch installation
RUN python3 -c "import torch; print(f'PyTorch version: {torch.__version__}'); print(f'CUDA available: {torch.cuda.is_available()}')"

# Install other dependencies (use older transformers compatible with PyTorch 2.0.1)
COPY requirements.txt .
RUN pip3 install --no-cache-dir flask==3.0.0 sentence-transformers==2.7.0 transformers==4.35.0

# Copy GPU service
COPY embedding-service-gpu.py embedding-service.py

# Expose port
EXPOSE 5000

# Run service
CMD ["python3", "embedding-service.py"]
