# AutoAgent Control Panel
# Extends base autoagent image with web control panel

FROM ghcr.io/tonezzz/autoagent:latest

# Install aiohttp for the control server
RUN pip install --no-cache-dir aiohttp

# Copy control panel files
COPY control-server.py /app/control-server.py
COPY entrypoint.sh /entrypoint.sh
COPY free-research.py /workspace/free-research.py
COPY smart-research.py /workspace/smart-research.py
COPY wiki-knowledge.py /workspace/wiki-knowledge.py
COPY postgres_kb.py /workspace/postgres_kb.py

# Make scripts executable
RUN chmod +x /entrypoint.sh

# Control panel port
EXPOSE 8080

# Use custom entrypoint
ENTRYPOINT ["/bin/bash", "/entrypoint.sh"]
