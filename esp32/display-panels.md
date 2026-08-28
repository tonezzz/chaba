# ESP32 Display Panel Options (CYD 2.8")

> Saved for later reference. Board: ESP32-2432S028 / Airepair 2.8" TFT + XPT2046 touch.

## Candidates found on GitHub

| Repo | What it is | Notes |
|---|---|---|
| [element-software/CYD-ESPHome-HA-Monitor](https://github.com/element-software/CYD-ESPHome-HA-Monitor) | HAMon — clock + 6–8 HA sensor slots, dynamic colors, optional touch, web YAML generator | Cleanest **status monitor** for HA entities |
| [drrcastro/CYD-Smart-Dashboard-for-Home-Assistant](https://github.com/drrcastro/CYD-Smart-Dashboard-for-Home-Assistant) | 6 customizable sensor slots + touch actions + auto-brightness | Interactive **dashboard** with tap-to-trigger |
| [1achy/ESPHOME-esp32-2432s028r-LCD](https://github.com/1achy/ESPHOME-esp32-2432s028r-LCD) | 4-page meteo / wind / HA / **status** UI, LVGL | Has a dedicated **status** page; chosen for next try |
| [Rishi8078/Docky-CYD](https://github.com/Rishi8078/Docky-CYD) | Polished desk dock: time, weather, scenes, transport, media, printer | Full **control panel** look |
| [gubas/cyd_HA](https://github.com/gubas/cyd_HA) | Multi-page weather, sensors, 3D printer, control menu | More elaborate, French/English/Spanish |
| [steemandavid/CYD-HA-display](https://github.com/steemandavid/CYD-HA-display) | Wall control panel for HA: power, temperatures, energy, devices | Good if you want multiple HA pages |

## Chosen for next try: 1achy

- **Repo:** https://github.com/1achy/ESPHOME-esp32-2432s028r-LCD
- **Hardware match:** ESP32-2432S028r / ILI9341V / XPT2046
- **Pages:** weather, wind, Home Assistant, status
- **Approach:** LVGL-based widgets with touch buttons

## Current config note

Our `esp32/config.yaml` currently uses the native `mipi_spi` display with a simple `lambda`. The GitHub dashboards above are **LVGL-based**, so to use one we would add the `lvgl:` component on top of the existing `mipi_spi` display.

## Next steps to try 1achy

```bash
# Clone for reference
cd /home/tony/CascadeProjects/chaba/esp32
git clone --depth 1 https://github.com/1achy/ESPHOME-esp32-2432s028r-LCD.git vendor/1achy

# Inspect the main YAML
cat vendor/1achy/*.yaml 2>/dev/null || cat vendor/1achy/**/*.yaml
```

Then adapt the relevant `display:` / `lvgl:` blocks into `esp32/config.yaml` and re-flash.
