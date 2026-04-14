FROM nvidia/cuda:12.2.0-devel-ubuntu22.04 AS base

ENV DEBIAN_FRONTEND=noninteractive
ENV PYTHONUNBUFFERED=1

# Install system dependencies
RUN apt-get update && apt-get install -y \
    python3.10 python3-pip python3-venv \
    git wget curl gnupg lsb-release software-properties-common \
    cmake build-essential \
    && rm -rf /var/lib/apt/lists/*

# Install clang via LLVM script (gets latest version, clang-20+)
RUN bash -c "$(wget -O - https://apt.llvm.org/llvm.sh)" && \
    rm -rf /var/lib/apt/lists/*

# Find installed clang version and set as default
RUN CLANG_VER=$(ls /usr/bin/clang-* 2>/dev/null | grep -oP 'clang-\K[0-9]+' | sort -n | tail -1) && \
    update-alternatives --install /usr/bin/clang clang /usr/bin/clang-${CLANG_VER} 100 && \
    echo "Using clang-${CLANG_VER}"

WORKDIR /workspace

# Clone BitNet
RUN git clone --recursive https://github.com/microsoft/BitNet.git .

# Create virtual environment
RUN python3 -m venv /workspace/.venv
ENV PATH="/workspace/.venv/bin:$PATH"

# Install Python dependencies
RUN pip install --upgrade pip
RUN pip install huggingface-hub

# Pre-download model (Falcon3-1B supports x86_64)
RUN hf download tiiuae/Falcon3-1B-Instruct-1.58bit --local-dir models/falcon3-1b

# Ensure submodules are fully initialized
RUN git submodule update --init --recursive

# CPU: Build bitnet.cpp (split steps for debugging)
RUN pip install -r requirements.txt
RUN python setup_env.py --hf-repo tiiuae/Falcon3-1B-Instruct-1.58bit -q i2_s 2>&1 || (cat logs/*.log 2>/dev/null && exit 1)

# GPU: Skip GPU build for now (Falcon3 GPU support requires different setup)
# WORKDIR /workspace/gpu
# RUN pip install -r requirements.txt && \
#     cd bitnet_kernels && bash compile.sh && cd ..

WORKDIR /workspace

# Comparison script
COPY compare.py /workspace/compare.py

CMD ["python", "compare.py"]
