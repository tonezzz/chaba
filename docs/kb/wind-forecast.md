---
title: Wind Forecast App
description: Minimal wind forecast page with map and hourly table for Track4 course locations using Open-Meteo API.
tags: [wind, forecast, weather, track4, race-management, meteorology]
created: 2026-08-06
updated: 2026-08-06
category: implementation
related: [ssot.apps.wind.yml, ssot.apps.track4.yml, h3-pages.md, app-ssot-standards.md]
search_keywords: [wind-forecast, weather-api, open-meteo, race-weather, meteorology]
---

# Wind Forecast App

**Abstract**: A minimal wind forecast application providing map visualization and hourly wind data tables for Track4 race course locations using the Open-Meteo forecast API.

## Overview

The Wind Forecast app is a lightweight, static web application that displays wind speed, direction, and gust information for specific race course locations. It integrates with the Track4 race management system to provide weather context for race planning and simulation.

## Purpose

- **Race Planning**: Provide wind forecasts for race course locations
- **Simulation Context**: Supply wind data for Track4 simulation scenarios
- **Weather Awareness**: Give racers and organizers current and forecast conditions
- **Minimal Interface**: Fast, simple access to essential wind information

## Key Files

| File | Purpose |
|------|---------|
| `chaba-h3/public/apps/wind/index.html` | Main HTML page with map and forecast table |
| `docs/ssot/apps/ssot.apps.wind.yml` | SSOT configuration and detailed documentation |
| `chaba-h3/public/apps/apps.yml` | App registry entry with 💨 icon |

## Implementation/Architecture

### Data Source

**Open-Meteo Forecast API**
- **Provider**: Open-Meteo (free, no API key required)
- **Models**: Global NWP models (ECMWF, GFS, etc.) interpolated for point forecasts
- **Access**: Direct HTTPS API calls from browser
- **Rate Limits**: Generous free tier suitable for race planning use

### Forecast Point

**Location**: tabsai-ws8-track3 (Track4 course)
- **Latitude**: 13.24413075920102
- **Longitude**: 100.92940092086792
- **Elevation**: 10 meters above ground (standard for marine forecasts)
- **Description**: In-buoy mark position for representative course conditions

### Data Display

**Map Visualization**
- Leaflet map centered on forecast point
- Marker showing exact forecast location
- Base map for geographic context

**Hourly Table**
- Next 24 hours of forecast data
- Wind speed (km/h)
- Wind direction (degrees and compass arrow)
- Gust information
- Asia/Bangkok timezone display

### Wind Direction Convention

- **Bearing System**: Direction wind is blowing FROM (meteorological standard)
- **0°** = North wind (blowing from north to south)
- **90°** = East wind (blowing from east to west)
- **Arrow Icon**: Points in same direction as wind source

## Operational Procedures

### Access

**URL**: `https://chaba.h3.gizmo-thailand.com/apps/wind/`

**Local Development**: `http://tony-omen.local:8765/apps/wind/` (Python server)

### Usage

1. Open the Wind Forecast app
2. View map for geographic context
3. Check hourly table for next 24 hours
4. Use wind data for race planning or simulation setup

### Integration with Track4

**Manual Integration**:
1. Check Wind Forecast for current conditions
2. Note wind direction and speed
3. Configure Track4 simulation with matching wind parameters
4. Run simulation with realistic weather context

**Data Flow**:
```
Open-Meteo API → Wind Forecast App → Manual Entry → Track4 Simulation
```

## Limitations

### Model Accuracy

- **Global Models**: No downscaling for local shoreline geometry
- **Sea Breeze**: Local thermal effects not captured
- **Obstacles**: Buildings, terrain, and structures not considered
- **Resolution**: Point forecast, not spatially varied across course

### Temporal Coverage

- **24 Hours**: Limited to next 24 hours of forecast data
- **Update Frequency**: Depends on Open-Meteo model updates
- **Historical Data**: No historical wind data available

### Geographic Scope

- **Single Point**: Forecast for one location only
- **Course Variation**: Wind may vary across different parts of the course
- **Tidal Effects**: No consideration of tidal impacts on wind

## Performance Metrics

- **Load Time**: < 2 seconds (static page + API call)
- **API Response**: ~500ms for Open-Meteo forecast
- **Update Frequency**: On page load (no auto-refresh)
- **Cache**: Browser caching of API responses

## Related Documentation

- **SSOT Configuration**: `docs/ssot/apps/ssot.apps.wind.yml` - Complete technical documentation
- **Track4 Integration**: `docs/ssot/apps/ssot.apps.track4.yml` - Wind simulation features
- **chaba.h3 Pages**: `docs/kb/h3-pages.md` - Deployment patterns
- **Open-Meteo Docs**: https://open-meteo.com/en/docs - API documentation

## Change History

| Date | Change | Author |
|------|--------|--------|
| 2026-08-06 | Initial creation with implementation details and limitations | tony |
