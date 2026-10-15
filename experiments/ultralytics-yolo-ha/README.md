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

Deployment: runs on **mn01** since 2026-09-27 (offloaded from tony-omen).
Unit lives at `~/.config/systemd/user/yolo-xiaomi.service` on mn01 with
`GO2RTC_BASE=http://tony-dell.taila0626a.ts.net:1984` and
`HA_BASE=https://tony-dell.taila0626a.ts.net:8123` — tailnet URLs so it
keeps working if mn01 moves off the LAN. HA (tony-ha) polls
`http://mn01.taila0626a.ts.net:8780/detect`.

## Gesture pointer mode (OPS-0440)

The same service can turn **hand bounding boxes into pointer messages** —
the YOLO rebuild of the MediaPipe gesture system. Set `YOLO_MODEL` to a
hand detector (`hand_yolov8n.pt` is vendored — single-class `hand`,
source: huggingface.co/Bingsu/adetailer) and configure `POINTER_SINK`:

- `vcast:<N>` — POSTs `{screen:N, type:"gesture", x,y, wx,wy, hands, conf,
  action?}` to `<INPUT_BRIDGE>/pub`, i.e. the pointer lands on vcast
  display N over its existing room ws. Pair with
  `YOLO_FRAME_URL=…/frame?screen={src}&token=cam` so the display's own
  camera uplink drives its cursor (that's the vcast `gesture=hand` mode).
- `ws://<host>:8794/ws?role=controller` — the service connects to
  gesture-relay as a controller; `/apps/gesture/screen` consumes the same
  contract unchanged. Frame side: `/apps/gesture/?engine=yolo` uplinks
  the iPhone camera to `screen=0 token=gesture` — point
  `YOLO_FRAME_URL` there.
- `http(s)://…` — raw POST of each message (debug/custom).

Semantics (bounding boxes have no landmarks): box centre = pointer
(normalized 0-1, X mirror-flipped by default via `POINTER_FLIP=1` for
front-facing display cams), **two hands sustained ≥3 frames = fist_start**
(grab), drop below = fist_end, hand lost > `POINTER_GONE_MS` emits
`{type:"gesture",gone:1}`. Click is the client's job — screen.html and
vcast implement dwell-click (700 ms parked on an element).

`yolo-gesture.service` is a ready template. Debug: `GET /pointer` shows
sink state + last emitted msg; pointer-class boxes draw cyan on `/image`.

## Home Assistant

Add the `rest` and `camera` snippets from `ha-config-snippet.yaml` to `configuration.yaml` and restart HA. Adjust the host from `192.168.2.67` to `tony-dell` or `host.containers.internal` if needed.
