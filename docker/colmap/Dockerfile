# COLMAP container — Structure-from-Motion preprocessing
# Produces sparse/ + images/ ready for all Gaussian Splatting methods.

FROM gaussian-splatting-base:latest

RUN apt-get update && apt-get install -y --no-install-recommends \
    libatlas-base-dev libsuitesparse-dev \
    libcgal-dev libcgal-qt5-dev \
    qtbase5-dev libqt5opengl5-dev \
    libceres-dev \
    && rm -rf /var/lib/apt/lists/*

# Install hloc (Hierarchical Localization) for improved feature matching
RUN pip install \
    pycolmap==0.6.1 \
    h5py \
    kornia

WORKDIR /workspace
COPY entrypoint_colmap.sh /entrypoint.sh
RUN chmod +x /entrypoint.sh

ENTRYPOINT ["/entrypoint.sh"]
CMD ["--help"]
