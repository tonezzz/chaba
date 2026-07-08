# Gaussian Splatting Variants container
# Includes: 2D Gaussian Splatting, Mip-Splatting
# Select variant via the VARIANT env variable at runtime.

FROM gaussian-splatting-base:latest

# ── 2D Gaussian Splatting ─────────────────────────────────────────────────────
RUN git clone --recursive https://github.com/hbb1/2d-gaussian-splatting /workspace/2dgs

WORKDIR /workspace/2dgs
RUN pip install \
    submodules/diff-surfel-rasterization \
    submodules/simple-knn \
    && pip install \
    plyfile \
    trimesh \
    open3d

# ── Mip-Splatting ─────────────────────────────────────────────────────────────
RUN git clone --recursive https://github.com/autonomousvision/mip-splatting /workspace/mip-splatting

WORKDIR /workspace/mip-splatting
RUN pip install \
    submodules/diff-gaussian-rasterization \
    submodules/simple-knn

# ── Gaussian Opacity Fields (GOF) ─────────────────────────────────────────────
RUN git clone --recursive https://github.com/autonomousvision/gaussian-opacity-fields /workspace/gof

WORKDIR /workspace/gof
RUN pip install \
    submodules/diff-gaussian-rasterization \
    submodules/simple-knn \
    && pip install \
    tetgen \
    pymeshlab

WORKDIR /workspace
COPY entrypoint_variants.sh /entrypoint.sh
RUN chmod +x /entrypoint.sh

ENTRYPOINT ["/entrypoint.sh"]
CMD ["--help"]
