# Original 3D Gaussian Splatting (graphdeco-inria/gaussian-splatting)
# Paper: Kerbl et al., SIGGRAPH 2023

FROM gaussian-splatting-base:latest

# Clone the official repository
RUN git clone --recursive https://github.com/graphdeco-inria/gaussian-splatting /workspace/gaussian-splatting

WORKDIR /workspace/gaussian-splatting

# Install Python dependencies (WORKDIR must be set before building CUDA submodules)
RUN pip install plyfile joblib einops && \
    pip install submodules/diff-gaussian-rasterization && \
    pip install submodules/simple-knn

# Pre-download (optional) — comment out if no internet at build time
# RUN python -c "import torchvision; torchvision.models.vgg16(pretrained=False)"

COPY entrypoint_3dgs.sh /entrypoint.sh
RUN chmod +x /entrypoint.sh

ENTRYPOINT ["/entrypoint.sh"]
CMD ["--help"]
