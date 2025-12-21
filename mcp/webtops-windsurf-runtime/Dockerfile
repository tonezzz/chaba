FROM lscr.io/linuxserver/webtop:latest

RUN apk add --no-cache \
    bash \
    ca-certificates \
    curl \
    binutils \
    xz \
    libarchive-tools

COPY cont-init.d/10-windsurf /etc/cont-init.d/10-windsurf
COPY windsurf-launch /usr/local/bin/windsurf-launch

RUN sed -i 's/\r$//' /etc/cont-init.d/10-windsurf /usr/local/bin/windsurf-launch \
    && chmod +x /etc/cont-init.d/10-windsurf /usr/local/bin/windsurf-launch
