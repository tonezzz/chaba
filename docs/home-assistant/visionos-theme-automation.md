# visionOS / Liquid Glass theme automation

Add this to `configuration.yaml` so the theme is set automatically on Home Assistant startup.

```yaml
automation:
  - alias: "Set visionOS theme on startup"
    id: set_visionos_theme_on_startup
    trigger:
      - platform: homeassistant
        event: start
    action:
      - service: frontend.set_theme
        data:
          name: visionos
```

After installing the theme via HACS, run `ha core check` and restart Home Assistant.

To apply the theme immediately without a restart, call the service manually:

```yaml
service: frontend.set_theme
data:
  name: visionos
```
