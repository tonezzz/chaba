# AutoAgent Control Panel
# Extends base autoagent image with web control panel

FROM ghcr.io/tonezzz/autoagent:latest

# Install aiohttp for the control server
RUN pip install --no-cache-dir aiohttp

# Copy control panel files
COPY control-server.py /app/control-server.py
COPY entrypoint.sh /entrypoint.sh

# Copy research scripts to /app/ (entrypoint copies them to /workspace/ on startup)
# This handles the volume shadowing issue where named volumes mount over build-time files
COPY free-research.py /app/free-research.py
COPY smart-research.py /app/smart-research.py
COPY wiki-knowledge.py /app/wiki-knowledge.py
COPY postgres_kb.py /app/postgres_kb.py

# Make scripts executable
RUN chmod +x /entrypoint.sh

# Control panel port
EXPOSE 8080

# Use custom entrypoint
ENTRYPOINT ["/bin/bash", "/entrypoint.sh"]
