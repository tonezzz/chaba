FROM lscr.io/linuxserver/webtop:ubuntu-xfce

ENV DEBIAN_FRONTEND=noninteractive

WORKDIR /tmp

COPY cont-init.d/10-claude-perms /etc/cont-init.d/10-claude-perms
COPY cont-init.d/25-claude-auto-auth /etc/cont-init.d/25-claude-auto-auth
COPY cont-init.d/20-claude-default-model /etc/cont-init.d/20-claude-default-model
COPY cont-init.d/30-glama-cli /etc/cont-init.d/30-glama-cli

RUN apt-get update \
    && apt-get install -y --no-install-recommends \
        bash \
        ca-certificates \
        curl \
        expect \
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
    export PATH="$HOME/.local/bin:$PATH"; \
    if command -v claude >/dev/null 2>&1; then \
      CLAUDE_BIN="$(command -v claude)"; \
    else \
      CLAUDE_BIN="$(find "$HOME" -type f -name claude -path '*/.local/bin/claude' -print -quit || true)"; \
    fi; \
    test -n "$CLAUDE_BIN"; \
    mkdir -p /usr/local/libexec/claude; \
    install -m 0755 "$CLAUDE_BIN" /usr/local/libexec/claude/claude; \
    ln -sf /usr/local/libexec/claude/claude /usr/local/bin/claude; \
    ln -sf /usr/local/libexec/claude/claude /usr/local/bin/claude.real; \
    claude --version || true

RUN sed -i 's/\r$//' /etc/cont-init.d/10-claude-perms \
    /etc/cont-init.d/20-claude-default-model \
    /etc/cont-init.d/25-claude-auto-auth \
    /etc/cont-init.d/30-glama-cli \
    && chmod +x /etc/cont-init.d/10-claude-perms /etc/cont-init.d/20-claude-default-model /etc/cont-init.d/25-claude-auto-auth /etc/cont-init.d/30-glama-cli

RUN git config --system --add safe.directory /workspaces/chaba
