# John the Ripper (Jumbo)
# https://github.com/openwall/john/tree/bleeding-jumbo

FROM ubuntu:22.04

ARG DEBIAN_FRONTEND=noninteractive
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

# ── Build & runtime dependencies ───────────────────────────────────────────────
RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    autoconf automake libtool pkg-config \
    git wget curl ca-certificates \
    libssl-dev \
    libpcap-dev \
    libnss3-dev \
    libkrb5-dev \
    libgmp-dev \
    libdb-dev \
    zlib1g-dev libbz2-dev \
    python3 python3-dev python3-pip python3-venv \
    libperl-dev cpanminus \
    && rm -rf /var/lib/apt/lists/*

# ── Clone bleeding-jumbo ─────────────────────────────────────────────────────
RUN git clone --depth 1 --branch bleeding-jumbo \
    https://github.com/openwall/john.git /workspace/john

WORKDIR /workspace/john/src

# ── Compile John ─────────────────────────────────────────────────────────────
RUN ./configure && make -sj4

WORKDIR /workspace/john/run

# ── Python helper tools virtualenv ───────────────────────────────────────────
RUN python3 -m venv venv && \
    . venv/bin/activate && \
    pip install --upgrade pip && \
    pip install -r requirements.txt && \
    deactivate

# ── Sanity check ───────────────────────────────────────────────────────────────
RUN ./john --test=0

COPY entrypoint_john.sh /entrypoint.sh
RUN chmod +x /entrypoint.sh

ENTRYPOINT ["/entrypoint.sh"]
CMD ["--help"]
