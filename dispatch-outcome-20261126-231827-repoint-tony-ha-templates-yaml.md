# Dispatch outcome — repoint tony-ha image.yolo_annotated to 127.0.0.1:8780

Card: `ha-template-image-yolo-annotated-points-5af431` · Host work: tony-omen (via ssh from mn01) · Date: 2026-11-26

## What changed

- **Live HA config on tony-omen** (`~/.config/home-assistant/templates.yaml`, mounted into the `tony-ha` rootless-podman container at `/config`):
  `image.yolo_annotated` url changed `http://192.168.2.86:8780/image?t=...` → `http://127.0.0.1:8780/image?t=...`.
  Backup left at `templates.yaml.bak-20261126` on omen. `configuration.yaml` already used `127.0.0.1:8780` for `rest_command.yolo_set_source` and the `/detect` REST sensor — templates.yaml was the only stale reference.
- **HA reload**: `POST /api/services/template/reload` on `http://127.0.0.1:8123` (token from `~/.config/secrets/home-assistant-token.env`); entity re-rendered (new image_proxy token observed).
- **Repo record**: `docs/ssot/jobs/infrastructure/2026-11-25-omen-post-reboot-unit-restore.yml` residual bullet updated to RESOLVED with evidence (commit `53f6401b29` on `dispatch/20261126-231827-repoint-tony-ha-templates-yaml`).

## Route verification (the 404 question)

`experiments/ultralytics-yolo-ha/server.py` `/image` takes **no params** — `GET /image` returns `state["annotated"]` as `image/jpeg`, or **404 "no image yet" (12B text/plain)** when no frame has been annotated yet. The audit's bare-GET 404 was the empty-state response, not a route/param miss. `HEAD /image` behaves the same.

## End-to-end render proof

- `yolo-detect.service` confirmed bound to `127.0.0.1:8780` only (`ss -tln`: 127.0.0.1:8780 + pre-existing jev-student 100.75.102.88:8780; **no LAN bind added**). HA is host-networked (`tony-ha` NetworkMode=host, API on :8123), so loopback reaches yolo-detect.
- Temporarily set yolo source to `omen_cam` via `/set-source` (declared `input_select.yolo_camera_source` is `ip_cam_65_low`, still frameless — camera outage is a separate lane): `GET 127.0.0.1:8780/image` → **200 image/jpeg 74KB**; HA `/api/image_proxy/image.yolo_annotated?token=…` → **200 image/jpeg 80KB** — the exact path the dashboard uses.
- Restored `/set-source?src=ip_cam_65_low`. `/image` still returns 200 serving the last good annotated frame (server keeps `state["annotated"]` on detect failure), so the dashboard renders a stale omen_cam snapshot until `ip_cam_65_low` produces frames again.

## Caveats / follow-ups

- Declared camera source `ip_cam_65_low` remains frameless (remote cameras offline per the 11-25 job doc residual) — `sensor.yolo_person_count` reports 0/error until cameras return; not this card's scope.
- omen `templates.yaml` is live-only (repo `docs/home-assistant/configuration/` feeds mn-ha-dev/michael-ha via `deploy-config.sh`, not tony-ha) — no repo mirror to update.
- Rollback: `cp templates.yaml.bak-20261126 templates.yaml` on omen + `template.reload`.

lessons:
  - "Bare-GET 404 on yolo /image means 'no image yet' (state.annotated empty), not a bad route — server.py /image has no params; verify by reading the handler before assuming param requirements."
  - "yolo-detect keeps serving the LAST annotated frame on /image after detect() starts failing — a stale 200 can mask an upstream camera outage; check / JSON error field for real health."
  - "tony-ha template image entities render through HA /api/image_proxy — verifying that endpoint with its ?token= is the true consumer-surface check, stronger than curling the backend URL."
  - "HA image/template YAML reload needs no restart: POST /api/services/template/reload; entity state timestamp + rotated image_proxy token confirm pickup."
