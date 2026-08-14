# WiFi Camera Solutions

## Goal
Find and deploy a self-hosted NVR for multiple WiFi cameras.

## Status
Planning.

## Decision
- **Frigate** is the recommended NVR.
- Target host: `tony-omen` (`192.168.1.40`).
- Deployment method: Docker, managed by Ansible.

## Key details
- Coral USB accelerator availability is unknown.
- Camera RTSP URL formats are unknown.
- Possible install paths: `/opt/frigate` or `~/frigate`.

## References
- Detailed research: `tasks/2026-07-15-wifi-camera-solutions.md`
