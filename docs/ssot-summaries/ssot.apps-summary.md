# SSOT Apps Summary

**Purpose**: Summary of SSOT apps configuration for searchability via MCP docs server.

## Master Apps Registry

**File**: `docs/ssot/apps/ssot.apps.yml`

**Purpose**: App registry with all app names and per-host deployment mappings.

**Apps Defined**:
- cams: Camera monitor
- chatllama: ChatLlama
- chatlocal: ChatLocal
- docs: Docs
- imagen2: Imagen2
- map: Camera map
- map3d: 3D map viewer with point clouds and tiltable overlays
- neo-chat: Neo Chat
- overview: Overview
- raceman: Race management system with course editor and simulation
- reefriders: Reef Riders
- reefriders-01: Reef Riders 01
- test-pwa: Progressive Web App demo for iPad testing with full-screen support
- test-splat: 3D Gaussian Splat test page
- tony-omen-temp: Tony Omen Temp
- temp-graph: Temp Graph
- thailegal: Thai Legal AI Assistant
- track: Track
- track2: Track2 (legacy, superseded by track4)
- track3: Track3 (legacy, superseded by track4)
- track4: Track4 (modularized race simulation)
- wind: Wind forecast map and hourly table for race course locations
- yomi: Yomi
- playlive: Playlive

**Host Configurations**:
- tony-omen: Apps testing on tony-omen (http://tony-omen.local:8080/apps)
- tony-omen-chaba-h3: Chaba-h3 preview on tony-omen (http://tony-omen.local:8081/apps)
- tony-dell: Apps on testing tony-dell (http://tony-dell.local:8080/apps)
- chaba-h3-apps: Apps on chaba-h3 (https://chaba.h3.gizmo-thailand.com/apps)
- chaba-h3-demos: Apps demos on chaba-h3 (https://chaba.h3.gizmo-thailand.com/demos)

## Individual App SSOT Files

### Track4
**File**: `docs/ssot/apps/ssot.apps.track4.yml`
**Purpose**: Track4 course simulator modularization documentation
**Key Features**: 5-module extraction, 40 tests, simulation replay, wind simulation
**Status**: Active, modularized, comprehensive testing

### Raceman
**File**: `docs/ssot/apps/ssot.apps.raceman.yml`
**Purpose**: Race management system documentation
**Key Features**: Course editor, simulation, visualization, YAML support
**Status**: Active, deployed on chaba-h3 and chaba-raceman

### Wind
**File**: `docs/ssot/apps/ssot.apps.wind.yml`
**Purpose**: Wind forecast page documentation
**Key Features**: Open-Meteo API, hourly table, map visualization
**Status**: Active, minimal static page

### Map3D
**File**: `docs/ssot/apps/ssot.apps.map3d.yml`
**Purpose**: 3D map viewer documentation
**Key Features**: Point clouds, Gaussian splats, tiltable overlays
**Status**: Active, experimental 3D rendering

### Test PWA
**File**: `docs/ssot/apps/ssot.apps.test-pwa.yml`
**Purpose**: Progressive Web App demo documentation
**Key Features**: Full-screen iPad support, interactive demo, status detection
**Status**: Active, PWA testing reference

### Other App SSOT Files
- `ssot.apps.playlive.yml`: Playlive browser automation
- `ssot.apps.aihub.yml`: AI Hub multi-AI automation
- `ssot.apps.chaba.yml`: Main chaba application overview
- `ssot.apps.cams.yml`: Camera monitor application
- `ssot.apps.imagen2.yml`: Image generation service
- `ssot.apps.imagen3.yml`: Image generation service
- `ssot.apps.deka.yml`: Deka application

## Related Documentation

- **App SSOT Standards**: `docs/kb/app-ssot-standards.md` - Standardized structure for app SSOT files
- **App Template**: `docs/ssot/apps/template.app.yml` - Template for creating new app SSOT files
- **SSOT Index**: `docs/ssot/ssot.index.yml` - Master index of all SSOT files

## Search Keywords

app registry, application deployment, host configuration, track4, raceman, wind forecast, map3d, test pwa, progressive web app, race management, 3d visualization, course simulator
