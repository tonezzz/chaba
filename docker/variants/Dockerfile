# Gaussian Splatting Variants container
# Includes: 2D Gaussian Splatting, Mip-Splatting
# Select variant via the VARIANT env variable at runtime.

FROM gaussian-splatting-base:latest

# Set target CUDA arch for GTX 1650 (Turing 7.5). Adjust for your GPU if needed.
ENV TORCH_CUDA_ARCH_LIST="7.5"

# ── 2D Gaussian Splatting ─────────────────────────────────────────────────────
RUN git clone --recursive https://github.com/hbb1/2d-gaussian-splatting /workspace/2dgs

WORKDIR /workspace/2dgs
RUN pip install plyfile trimesh open3d && \
    pip install --no-build-isolation submodules/diff-surfel-rasterization && \
    pip install --no-build-isolation submodules/simple-knn

# ── Mip-Splatting ─────────────────────────────────────────────────────────────
RUN git clone --recursive https://github.com/autonomousvision/mip-splatting /workspace/mip-splatting

WORKDIR /workspace/mip-splatting
RUN pip install --no-build-isolation submodules/diff-gaussian-rasterization && \
    pip install --no-build-isolation submodules/simple-knn

# ── Gaussian Opacity Fields (GOF) ─────────────────────────────────────────────
RUN git clone --recursive https://github.com/autonomousvision/gaussian-opacity-fields /workspace/gof

WORKDIR /workspace/gof
RUN pip install tetgen pymeshlab && \
    pip install --no-build-isolation submodules/diff-gaussian-rasterization && \
    pip install --no-build-isolation submodules/simple-knn

WORKDIR /workspace
COPY entrypoint_variants.sh /entrypoint.sh
RUN chmod +x /entrypoint.sh

ENTRYPOINT ["/entrypoint.sh"]
CMD ["--help"]
