#!/usr/bin/env python3
"""Idempotent mutate() for push-dashboard.py — add/repair the Ada Test tab.

Usage:
  HASS_TOKEN=... python3 scripts/home-assistant/push-dashboard.py \
      <ha_ws_url> chaba-admin --mutate \
      scripts/home-assistant/mutate-ada-ha-ada-test-tab.py

The iframe target comes from the OSWE_URL environment variable (no secrets in
the URL or in this file). OSWE is the first — currently only — tab in Ada Test,
following the ada-ocb panel-view + iframe convention.
"""
import os

VIEW = {
    "title": "Ada Test",
    "path": "ada-test",
    "icon": "mdi:flask-outline",
    "type": "panel",
    "cards": [
        {
            "type": "iframe",
            "url": os.environ.get("OSWE_URL", "https://oswe.surf-thailand.com/?v=1"),
        }
    ],
}


def mutate(config):
    views = config.setdefault("views", [])
    existing = next((v for v in views if v.get("path") == VIEW["path"]), None)
    if existing is not None:
        # Repair in place: keep position, update only the managed fields.
        existing.update(VIEW)
    else:
        # Group with the other code-agent tabs, directly after OpenChamber.
        idx = next(
            (i + 1 for i, v in enumerate(views) if v.get("path") == "ada-ocb"),
            len(views),
        )
        views.insert(idx, dict(VIEW))
