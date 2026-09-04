#!/bin/bash
# Setup script for Yomi Weaviate message indexing systemd service

echo "Setting up Yomi Weaviate message indexing systemd service..."

# Copy service file
sudo cp /home/tony/CascadeProjects/chaba-tony-dell/scripts/yomi/yomi-index-weaviate.service /etc/systemd/system/

# Copy timer file  
sudo cp /home/tony/CascadeProjects/chaba-tony-dell/scripts/yomi/yomi-index-weaviate.timer /etc/systemd/system/

# Reload systemd
sudo systemctl daemon-reload

# Enable and start timer
sudo systemctl enable yomi-index-weaviate.timer
sudo systemctl start yomi-index-weaviate.timer

# Check status
systemctl list-timers yomi-index-weaviate.timer

echo "Yomi Weaviate indexing service installed and enabled."
echo "It will run daily to index the last 24 hours of messages."
