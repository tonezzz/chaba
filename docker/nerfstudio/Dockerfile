# Nerfstudio + gsplat container
# Includes: splatfacto, splatfacto-big, gsplat web viewer

FROM gaussian-splatting-base:latest

# Install nerfstudio and gsplat
RUN pip install \
    nerfstudio==1.1.4 \
    gsplat==1.3.0

# Install nerfstudio CLI completion and tiny-cuda-nn (optional but speeds up training)
RUN pip install \
    tyro \
    viser \
    open3d \
    jaxtyping \
    nerfacc

# Expose web viewer port
EXPOSE 7007

COPY entrypoint_nerfstudio.sh /entrypoint.sh
RUN chmod +x /entrypoint.sh

ENTRYPOINT ["/entrypoint.sh"]
CMD ["--help"]
