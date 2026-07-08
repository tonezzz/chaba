# Base image: CUDA 11.8 + cuDNN 8 + Python 3.10 + common deps
# All other images build FROM this one.

FROM nvidia/cuda:11.8.0-cudnn8-devel-ubuntu22.04

ARG DEBIAN_FRONTEND=noninteractive
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1

# ── System packages ──────────────────────────────────────────────────────────
RUN apt-get update && apt-get install -y --no-install-recommends \
    python3.10 python3.10-dev python3-pip python3.10-venv \
    git wget curl unzip ca-certificates \
    build-essential cmake ninja-build \
    libgl1-mesa-glx libglib2.0-0 libsm6 libxrender1 libxext6 \
    libboost-all-dev libfreeimage-dev libgoogle-glog-dev \
    libgflags-dev libglew-dev libglfw3-dev libgtest-dev \
    ffmpeg colmap \
    && rm -rf /var/lib/apt/lists/*

# ── Python alias ─────────────────────────────────────────────────────────────
RUN ln -sf /usr/bin/python3.10 /usr/bin/python && \
    ln -sf /usr/bin/python3.10 /usr/bin/python3

# ── pip + PyTorch 2.0 (CUDA 11.8) ────────────────────────────────────────────
RUN python -m pip install --upgrade pip setuptools wheel && \
    pip install \
        torch==2.0.1+cu118 torchvision==0.15.2+cu118 torchaudio==2.0.2 \
        --extra-index-url https://download.pytorch.org/whl/cu118

# ── Common Python libs ────────────────────────────────────────────────────────
RUN pip install \
    numpy==1.24.4 \
    scipy \
    Pillow \
    opencv-python-headless \
    matplotlib \
    tqdm \
    plyfile \
    scikit-image \
    lpips \
    tensorboard \
    pandas \
    rich \
    tyro

WORKDIR /workspace
