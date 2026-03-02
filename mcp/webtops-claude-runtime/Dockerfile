FROM lscr.io/linuxserver/webtop:ubuntu-xfce

ENV DEBIAN_FRONTEND=noninteractive

WORKDIR /tmp

RUN apt-get update \
    && apt-get install -y --no-install-recommends \
        bash \
        ca-certificates \
        curl \
        git \
        gnupg \
        openssh-client \
    && rm -rf /var/lib/apt/lists/*

# Node.js 20 (required for Claude Code npm install fallback; also useful for dev tooling)
RUN set -eux; \
    mkdir -p /etc/apt/keyrings; \
    curl -fsSL https://deb.nodesource.com/gpgkey/nodesource-repo.gpg.key | gpg --dearmor -o /etc/apt/keyrings/nodesource.gpg; \
    echo "deb [signed-by=/etc/apt/keyrings/nodesource.gpg] https://deb.nodesource.com/node_20.x nodistro main" > /etc/apt/sources.list.d/nodesource.list; \
    apt-get update; \
    apt-get install -y --no-install-recommends nodejs; \
    rm -rf /var/lib/apt/lists/*

# Claude Code (official install script)
ENV PATH="/root/.local/bin:${PATH}"
RUN set -eux; \
    curl -fsSL https://claude.ai/install.sh | bash; \
    command -v claude; \
    ln -sf /root/.local/bin/claude /usr/local/bin/claude; \
    claude --version || true

RUN git config --system --add safe.directory /workspaces/chaba
