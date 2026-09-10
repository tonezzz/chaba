# Ultralytics YOLOv8 on xiaomi_c201

Pulls frames from the `xiaomi_c201` go2rtc stream, runs `yolov8n` every 2 seconds, and exposes the results on `0.0.0.0:8780`.

## Quick start

```bash
./run.sh
```

The first run creates `~/.cache/ultralytics-yolo-venv` and installs `ultralytics` (downloads `yolov8n.pt` on first inference).

## Endpoints

- `http://<host>:8780/` — status
- `http://<host>:8780/detect` — latest detections JSON
- `http://<host>:8780/image` — latest annotated JPEG

## Systemd

```bash
systemctl --user link $(pwd)/yolo-xiaomi.service
systemctl --user daemon-reload
systemctl --user enable --now yolo-xiaomi
```

## Home Assistant

Add the `rest` and `camera` snippets from `ha-config-snippet.yaml` to `configuration.yaml` and restart HA. Adjust the host from `192.168.2.67` to `tony-dell` or `host.containers.internal` if needed.
