# Frigate Setup Plan Brief

## 1. Goal
Deploy a local, AI-powered NVR for IP cameras using Frigate with real-time object detection and optional Home Assistant integration.

## 2. Hardware & AI Accelerator
- **Host:** Linux server (Ubuntu/Debian) or Proxmox/VM with Docker
- **Cameras:** IP cameras with RTSP/ONVIF or HTTP streams
- **AI accelerator (recommended):** one of the following
  - Google Coral EdgeTPU (USB/PCIe/M.2)
  - Intel GPU/NPU (OpenVINO)
  - NVIDIA GPU (ONNX / TensorRT)
  - Hailo-8 / Rockchip NPU / AMD ROCm

## 3. Storage
- Fast media storage for recordings (SATA/NVMe)
- Separate drive for Frigate DB (`/frigate-db`) recommended
- Retention: event-based or 24/7, with object filter rules

## 4. Network
- Cameras reachable on stable IP or mDNS/ONVIF
- Optional VLAN isolation for cameras
- MQTT broker if integrating with Home Assistant / Node-RED

## 5. Deployment
- Use Docker Compose with `blakeblackshear/frigate:stable` image
- Mount `config.yml`, media directory, and DB cache
- Expose web UI port (usually `5000`) and optionally RTMP/RTSP ports

## 6. Configuration Checklist
- [x] Define camera streams in `config.yml` (VSTARCAM on 192.168.1.41)
- [x] Choose detector — CPU (default, for testing)
- [x] Set recording retention and zones
- [ ] Configure objects to detect — `person`, `car` work; `animal`, `package` need custom model
- [ ] Enable MQTT for Home Assistant
- [ ] Set up notifications and automations

## 7. Verification
- [x] Web UI loads at `http://localhost:5000`
- [x] Camera feed visible in Frigate UI
- [x] Recording segments saved to disk (H.264 transcoded from H.265)
- [ ] Object detection runs and logs appear
- [ ] Home Assistant integration shows camera entities and sensors

## 8. Camera Details

| Property | Value |
|----------|-------|
| Brand | VSTARCAM |
| IP | 192.168.1.41 |
| RTSP port | 10554 (non-standard) |
| Auth | Digest (realm: RTSPD) |
| Video codec | H.265/HEVC |
| Main stream | `rtsp://admin:tonytony@192.168.1.41:10554/tcp/av0_0` (2304x1296 @ 15fps) |
| Sub stream | `rtsp://admin:tonytony@192.168.1.41:10554/tcp/av0_1` (640x360 @ 20fps) |
| Audio | PCM A-law (dropped — not supported in MP4) |

### Known Issues
- VSTARCAM uses `/tcp/av0_0` path format, not the standard `/stream1`
- Main stream H.265 bitstream has non-standard VPS — cannot stream-copy to MP4, must transcode to H.264 (`libx264`)
- Camera rate-limits rapid connection attempts (connection reset by peer)

## 9. Next Steps
1. Upgrade detector to Coral/OpenVINO/TensorRT for better performance
2. Tune detection zones / masks for the camera view
3. Remove unsupported objects (`animal`, `package`) or install a custom model
4. Enable MQTT and integrate with Home Assistant
5. Configure notifications and automations
