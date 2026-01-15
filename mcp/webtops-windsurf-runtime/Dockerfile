FROM lscr.io/linuxserver/webtop:ubuntu-xfce

RUN apt-get update \
    && apt-get install -y --no-install-recommends \
        bash \
        ca-certificates \
        curl \
        git \
        binutils \
        xz-utils \
        libarchive-tools \
    && rm -rf /var/lib/apt/lists/*

RUN git config --system --add safe.directory /workspaces/chaba

COPY cont-init.d/10-windsurf /etc/cont-init.d/99-windsurf
COPY windsurf-launch /usr/local/bin/windsurf-launch

COPY s6-rc.d/init-windsurf-desktop-fix /etc/s6-overlay/s6-rc.d/init-windsurf-desktop-fix
COPY s6-rc.d/user/contents.d/init-windsurf-desktop-fix /etc/s6-overlay/s6-rc.d/user/contents.d/init-windsurf-desktop-fix

RUN sed -i 's/\r$//' /etc/cont-init.d/99-windsurf /usr/local/bin/windsurf-launch \
    && chmod +x /etc/cont-init.d/99-windsurf /usr/local/bin/windsurf-launch \
    && sed -i 's/\r$//' \
        /etc/s6-overlay/s6-rc.d/init-windsurf-desktop-fix/type \
        /etc/s6-overlay/s6-rc.d/init-windsurf-desktop-fix/up \
        /etc/s6-overlay/s6-rc.d/init-windsurf-desktop-fix/run \
    && printf 'oneshot' > /etc/s6-overlay/s6-rc.d/init-windsurf-desktop-fix/type \
    && printf '/etc/s6-overlay/s6-rc.d/init-windsurf-desktop-fix/run\n' > /etc/s6-overlay/s6-rc.d/init-windsurf-desktop-fix/up \
    && chmod +x /etc/s6-overlay/s6-rc.d/init-windsurf-desktop-fix/run
