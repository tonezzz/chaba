---
category: operations
---

# Wifi Camera Solutions - July 15, 2026

## Context
Researching best ways to view and record multiple wifi cameras.

## Solutions Evaluated

### Self-Hosted/Open Source Options

**Frigate** (Recommended)
- Modern NVR with AI object detection
- Low latency, excellent UI
- Runs in Docker
- Supports RTSP/ONVIF cameras
- Designed for containerized deployment

**ZoneMinder**
- Mature, feature-rich NVR
- Motion detection
- Supports many camera types
- Very stable

**Shinobi**
- Open source NVR with modern UI
- Supports RTSP/ONVIF
- Good for multiple cameras

**Home Assistant**
- With Frigate integration
- Generic camera components
- Good for home automation

### Commercial Software

**Blue Iris** (Windows)
- Powerful, supports many cameras
- One-time license

**iSpy** (Windows)
- Free tier available
- Good for basic setups

### Hardware NVRs
- Hikvision, Dahua, Amcrest
- Plug-and-play but less flexible

## Deployment Plan

### Target System
- tony-omen

### Method
- Deploy Frigate via Docker
- Use Ansible devin_kb role for deployment
- Infrastructure-as-code approach

### Implementation Steps
1. Add Docker installation tasks to devin_kb role
2. Create Frigate docker-compose.yml template
3. Create Frigate config template
4. Add tasks to deploy Frigate service
5. Add variables for configuration (camera details, paths, etc.)

### Information Needed
- Installation path on tony-omen (e.g., `/opt/frigate` or `~/frigate`)
- Coral USB accelerator availability for AI detection
- Camera RTSP URL formats

## Ideas List

### Monitoring Knowledge Base
- Monitor GDrive kb accessibility/sync status
- Set up alerts when kb is down
- Notification method TBD (email, desktop, Telegram, etc.)

### Frigate Deployment
- Extend devin_kb role to include Frigate setup
- Single Ansible run to deploy to tony-omen
- Version-controlled configuration
- Easy updates by re-running playbook

## Notes
- Docker is recommended for Frigate deployment
- Frigate official documentation assumes Docker setup
- Clean removal and easy updates with container approach
