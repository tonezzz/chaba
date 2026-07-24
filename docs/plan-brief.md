# Frigate / Camera Surveillance Plan Brief

## 1. Goal
Deploy a local, AI-powered NVR for IP cameras using Frigate with real-time object detection, an interactive camera map, and a web-based control panel.

## 2. Hardware & Host
- **Host:** Linux server (`tony-omen`, LAN IP `192.168.1.48`) with Docker 24+
- **Cameras:** Local RTSP cameras + public HLS traffic cameras
- **AI accelerator:** currently CPU detector; NVIDIA GPU available for ONNX/TensorRT
- **Storage:** Frigate recordings in `stacks/nvr/storage/`, DB in `stacks/nvr/db/`

## 3. Camera Management Workflow

All cameras are stored in `stacks/nvr/cameras.json` (single source of truth).

```bash
# Edit cameras.json, then regenerate config + map
python3 stacks/nvr/generate_config.py

# Copy generated map to the web public directory
cp stacks/nvr/camera-map.html stacks/web/public/camera-map.html

# Restart Frigate to pick up config changes
docker compose -f stacks/nvr/docker-compose.yml restart
```

The generator can also list, enable, disable, and run stream checks:

```bash
python3 stacks/nvr/generate_config.py --list
python3 stacks/nvr/generate_config.py --check
python3 stacks/nvr/generate_config.py --enable camera_name
python3 stacks/nvr/generate_config.py --disable camera_name
```

## 4. Camera Registry (34 cameras)

| Group | Count | Source |
|-------|-------|--------|
| Local | 1 | VSTARCAM RTSP (192.168.1.41:10554) |
| Traffic (Bangkok) | 11 | DOH Wowza + iTIC |
| Burapha Withi Expressway | 10 | DOH / iTIC |
| Chonburi (DOH direct) | 12 | DOH direct IP |

Each camera has a `heading` field (0°=N, 90°=E, 180°=S, 270°=W) used to rotate arrow markers on the map.

Optional location and coverage metadata can be added to any camera:

- `location` — `{ road, km, side, area }` describing where the camera is physically mounted
- `perspective` — camera angle, e.g. `bird's eye`, `ground-level`, `elevated`, `close-up`, `wide-angle`
- `view` — `{ heading, heading_description, coverage[] }` describing what the camera is looking at
- `description` — free-form human-readable note

These fields are rendered in the camera map popup and help distinguish inbound/outbound coverage on expressway cameras.

## 5. Camera Control Panel

A Flask management UI for the camera registry runs on port `8090` as part of the web stack.

```bash
cd web
docker compose up -d camera-control
# Open: http://192.168.1.48:8090/
```

Features:
- Enable/disable cameras and assign groups
- Run discovery / stream-check jobs
- Regenerate Frigate config and sync camera map

A second instance is available on `tony-dell` at `http://tony-dell.local:8090/`.

## 6. Web Stack

The `stacks/web/` stack (Caddy + status-api) provides:

| Page | URL | Purpose |
|------|-----|---------|
| Dashboard | `http://192.168.1.48:8080/` | Service status + quick links |
| Status | `http://192.168.1.48:8080/status.html` | Host metrics, containers, git, cameras |
| Camera Map | `http://192.168.1.48:8080/camera-map.html` | Interactive map of all cameras |
| Infrastructure | `http://192.168.1.48:8080/infrastructure.html` | Ports, networks, devices |

Start the web stack:

```bash
cd web
docker compose up -d
```

Caddy reverse proxies:
- `/api/*` → `status-api:8000`
- `/frigate/*` → Frigate `:5000` (camera map snapshots)

## 7. Configuration Checklist
- [x] Define camera streams in `cameras.json`
- [x] Generate `config.yml` and `camera-map.html` from registry
- [x] Deploy Frigate stack
- [x] Deploy web stack with status API and reverse proxy
- [x] Add Camera Control Panel link to dashboard/status pages
- [ ] Configure objects to detect — `person`, `car` work; `animal`, `package` need custom model
- [ ] Enable MQTT for Home Assistant
- [ ] Set up notifications and automations

## 8. Verification
- [x] Web UI loads at `http://192.168.1.48:5000`
- [x] Camera map loads at `http://192.168.1.48:8080/camera-map.html`
- [x] Status page shows host CPU/memory/load/temperature
- [x] Recording segments saved to disk (H.264 transcoded from H.265)
- [ ] Object detection runs and logs appear
- [ ] Home Assistant integration shows camera entities and sensors

## 9. Local VSTARCAM Details

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

## 10. Next Steps
1. Upgrade detector to Coral/OpenVINO/TensorRT for better performance
2. Tune detection zones / masks for the local camera view
3. Remove unsupported objects (`animal`, `package`) or install a custom model
4. Enable MQTT and integrate with Home Assistant
